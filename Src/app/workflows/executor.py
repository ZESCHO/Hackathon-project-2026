"""
Workflow execution.

Runs the steps of an approved request's plan, calling one controlled
tool per step and writing an audit entry for each. Execution stops at
the first failure; nothing later in the plan is attempted.

Nothing here decides whether an action is permitted. Approval is
checked by the route before this is called and again inside every tool.
"""

from datetime import datetime

from app.models import db
from app.models.audit_log import AuditLog
from app.models.workflow import Workflow
from app.models.approval import Approval
from app.workflows.planner import build_plan
from app.tools.actions import TOOLS, ToolError


def _audit(service_request, event_type, action, description,
           status, tool_name=None, actor_type="AGENT", metadata=None):
    """
    Write one audit row.
    """

    entry = AuditLog(
        request_id=service_request.id,
        user_id=service_request.user_id,
        event_type=event_type,
        action=action,
        description=description,
        actor_type=actor_type,
        status=status,
        policy_checked=True,
        approval_required=True,
        approval_status=service_request.status,
        tool_name=tool_name,
        metadata_json=metadata
    )

    db.session.add(entry)

    return entry


# =========================================================
# PLANNING
# =========================================================

def create_workflow(service_request, category, fields):
    """
    Build a plan for a newly filed request and persist it.

    Called when the request is created, so a reviewer can see the whole
    intended sequence before approving any part of it.
    """

    plan = build_plan(category, fields)

    if not plan["steps"]:
        return None, plan

    workflow = Workflow(
        request_id=service_request.id,
        workflow_type=category,
        status="PLANNED",
        current_step=1,
        total_steps=len(plan["steps"]),
        plan=_serializable(plan)
    )

    db.session.add(workflow)

    db.session.flush()

    # Route the decision to the office policy says owns it, instead of
    # dropping everything into one queue.
    department = plan["derived"].get("department") or "Approval Center"

    # A sentence a reviewer can read, not a snippet id.
    routing_reason = plan["derived"].get("routing_reason")

    source = plan["derived"].get("routing_source")

    if routing_reason and source:
        routing_reason = f"{routing_reason} (policy {source})"

    approval = Approval(
        request_id=service_request.id,
        workflow_id=workflow.id,
        action=f"Approve {category} request #{service_request.id}",
        description=service_request.request_text,
        routed_to=department,
        routing_reason=routing_reason,
        required_permission="approve_requests",
        status="PENDING"
    )

    db.session.add(approval)

    _audit(
        service_request,
        "APPROVAL_REQUESTED",
        "Approval Routed",
        f"Routed to {department} for human approval.",
        "Pending Approval",
        tool_name="Routing Engine",
        metadata={"routed_to": department}
    )

    _audit(
        service_request,
        "PLAN_CREATED",
        "Plan Created",
        f"Planned {len(plan['steps'])} steps for a {category} request.",
        "Planned",
        metadata={"steps": [s["action"] for s in plan["steps"]]}
    )

    # Policy findings are recorded at planning time so a reviewer sees
    # them before deciding, not after something has been done.
    for note in plan["policy_notes"]:

        _audit(
            service_request,
            "POLICY_CHECKED",
            "Policy Conflict" if note["blocking"] else "Policy Note",
            f"[{note['source']}] {note['message']}",
            "Blocking" if note["blocking"] else "Advisory",
            tool_name="Policy Engine",
            metadata={"source": note["source"]}
        )

    return workflow, plan


def _serializable(plan):
    """
    Strip values that cannot be stored as JSON.

    The plan carries parsed dates and times for the executor; only the
    display-safe parts are persisted.
    """

    derived = {}

    for key, value in plan.get("derived", {}).items():

        if isinstance(value, (datetime,)):
            derived[key] = value.isoformat()

        elif hasattr(value, "isoformat"):
            derived[key] = value.isoformat()

        else:
            derived[key] = value

    return {
        "steps": plan["steps"],
        "policy_notes": plan["policy_notes"],
        "policy_conflict": plan["policy_conflict"],
        "derived": derived
    }


# =========================================================
# EXECUTION
# =========================================================

def execute_workflow(service_request, actor=None):
    """
    Run the tool-backed steps of an approved request's plan.

    Returns a dict with:
        ok       - True if every step completed
        results  - one entry per step that ran
        error    - the failure reason when ok is False
    """

    category = (service_request.category or "").lower().strip()

    fields = service_request.fields_json or {}

    # Rebuilt rather than read back from the stored plan so that the
    # policy in force at execution time is the one that applies.
    plan = build_plan(category, fields)

    if not plan["steps"]:
        return {
            "ok": False,
            "results": [],
            "error": (
                f"No workflow is defined for category "
                f"'{service_request.category}'."
            )
        }

    workflow = Workflow.query.filter_by(
        request_id=service_request.id
    ).first()

    if workflow is None:
        workflow, _ = create_workflow(service_request, category, fields)

    results = []

    for step in plan["steps"]:

        action = step["action"]

        # Steps before the approval gate were satisfied when the
        # request was filed and reviewed; the gate itself is the human
        # decision that has already happened.
        if action == "human_approval":

            results.append({
                "step": step["step"],
                "action": action,
                "status": "SATISFIED",
                "summary": "Human approval recorded before execution."
            })

            continue

        tool = TOOLS.get(action)

        if tool is None:

            results.append({
                "step": step["step"],
                "action": action,
                "status": "SKIPPED",
                "summary": step["description"]
            })

            continue

        try:
            outcome = tool(service_request, fields, plan["derived"])

        except ToolError as error:

            # The rollback undoes every record written by earlier steps
            # in this run, so they must not be reported as done.
            db.session.rollback()

            for earlier in results:
                if earlier["status"] == "DONE":
                    earlier["status"] = "ROLLED_BACK"
                    earlier["summary"] = (
                        f"Undone because a later step failed: "
                        f"{earlier['summary']}"
                    )

            workflow = Workflow.query.filter_by(
                request_id=service_request.id
            ).first()

            if workflow:
                workflow.status = "FAILED"

            _audit(
                service_request,
                "WORKFLOW_FAILED",
                "Execution Failed",
                f"Step {step['step']} ({action}) failed: {error}",
                "Failed",
                tool_name=action,
                actor_type="Controlled Execution"
            )

            db.session.commit()

            return {
                "ok": False,
                "results": results,
                "error": str(error)
            }

        results.append({
            "step": step["step"],
            "action": action,
            "status": "DONE",
            "summary": outcome["summary"],
            "reference": outcome.get("reference"),
            "detail": outcome.get("detail", {})
        })

        _audit(
            service_request,
            "TOOL_EXECUTED",
            step["description"],
            outcome["summary"],
            "Executed",
            tool_name=action,
            actor_type="Controlled Execution",
            metadata={
                "reference": outcome.get("reference"),
                "record_id": outcome.get("record_id")
            }
        )

        if workflow:
            workflow.current_step = step["step"]

    if workflow:
        workflow.status = "COMPLETED"
        workflow.completed_at = datetime.utcnow()

    _audit(
        service_request,
        "WORKFLOW_COMPLETED",
        "Workflow Completed",
        f"All {len(results)} planned steps completed for request "
        f"#{service_request.id}.",
        "Executed",
        tool_name="Workflow Engine",
        actor_type="Controlled Execution"
    )

    return {
        "ok": True,
        "results": results,
        "error": None
    }
