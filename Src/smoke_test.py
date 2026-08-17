"""
End to end smoke test for the Secure Agentic-AI platform.

Run it against a scratch database so it never touches real data:

    venv/bin/python smoke_test.py

It checks the behaviour the platform is judged on:

- questions are answered from verified sources, or refused
- questions never create institutional actions
- requests collect their required fields before being filed
- nothing executes without human approval
- execution creates real institutional records
- policy rules from the knowledge base are actually enforced
- the same holds when the user writes in another language

Requires the local Ollama model to be running.
"""

import os
import sys
import runpy
import tempfile


FAILURES = []
CHECKS = [0]


def check(name, condition, detail=""):
    CHECKS[0] += 1

    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))
        FAILURES.append(name)


def section(title):
    print()
    print("=" * 62)
    print(title)
    print("=" * 62)


def main():

    # A scratch database keeps the developer's own data untouched.
    # It must be set before app.py runs, since that is where the
    # database is bound to the application.
    scratch = tempfile.mkdtemp(prefix="secureai-smoke-")

    os.environ["DATABASE_URI"] = (
        "sqlite:///" + os.path.join(scratch, "smoke.db")
    )

    module = runpy.run_path("app.py", run_name="not_main")

    app = module["app"]
    db = module["db"]

    app.config["TESTING"] = True

    from app.models.request import ServiceRequest
    from app.models.audit_log import AuditLog
    from app.models.workflow import Workflow
    from app.models.maintenance import MaintenanceTicket
    from app.models.laboratory import LaboratoryBooking
    from app.models.certificate import CertificateRequest
    from app.models.grievance import Grievance

    with app.app_context():
        db.create_all()

    module["create_default_admin"]()

    client = app.test_client()

    def count(model):
        with app.app_context():
            return model.query.count()

    def chat(message, language=None):
        payload = {"message": message}

        if language:
            payload["language"] = language

        return client.post("/chat", json=payload).json["reply"]

    # ----------------------------------------------------------
    section("AUTHENTICATION")

    check(
        "anonymous chat is refused",
        client.post("/chat", json={"message": "hi"}).status_code == 401
    )

    login = client.post("/login", data={
        "email": "admin@secureai.com",
        "password": "Admin@123"
    })

    check("admin can log in", login.status_code == 302)

    # ----------------------------------------------------------
    section("GROUNDED ANSWERING")

    before = count(ServiceRequest)

    reply = chat("Is there a fee for a transfer certificate?")

    check("fee question is grounded", reply["grounded"] is True)
    check("fee question cites a source", bool(reply["sources"]))
    check(
        "question creates no request",
        count(ServiceRequest) == before,
        f"{count(ServiceRequest) - before} created"
    )

    reply = chat("Who won the football world cup in 2022?")

    check("off-topic question is refused", reply["grounded"] is False)

    reply = chat("What is the wifi password for the staff network?")

    check("unknown policy question is refused", reply["grounded"] is False)

    # ----------------------------------------------------------
    section("REQUEST INTAKE")

    before = count(ServiceRequest)

    reply = chat("The lights in room 12 of A block keep flickering")

    check(
        "maintenance request is filed",
        count(ServiceRequest) == before + 1
    )
    check("filed request returns an id", bool(reply.get("request_id")))

    request_id = reply.get("request_id")

    with app.app_context():
        record = db.session.get(ServiceRequest, request_id)
        workflow = Workflow.query.filter_by(request_id=request_id).first()

        check("structured fields are stored", bool(record.fields_json))
        check("a plan was created", workflow is not None)
        check(
            "plan has multiple steps",
            workflow is not None and workflow.total_steps >= 4
        )

    # ----------------------------------------------------------
    section("APPROVAL GATE")

    tickets_before = count(MaintenanceTicket)

    client.post(f"/execution/{request_id}/execute")

    with app.app_context():
        status = db.session.get(ServiceRequest, request_id).status

    check("unapproved request is not executed", status != "Executed", status)
    check(
        "no record created without approval",
        count(MaintenanceTicket) == tickets_before
    )

    client.post(f"/approval/{request_id}/approve")
    client.post(f"/execution/{request_id}/execute")

    with app.app_context():
        record = db.session.get(ServiceRequest, request_id)
        ticket = MaintenanceTicket.query.order_by(
            MaintenanceTicket.id.desc()
        ).first()

        check("approved request executes", record.status == "Executed")
        check(
            "a real ticket is created",
            count(MaintenanceTicket) == tickets_before + 1
        )
        check(
            "ticket has a reference number",
            ticket is not None and ticket.ticket_number.startswith("MNT-")
        )
        check(
            "execution is audited",
            AuditLog.query.filter_by(
                request_id=request_id
            ).count() >= 3
        )

    # ----------------------------------------------------------
    section("POLICY ENFORCEMENT")

    client.post("/laboratory/book", data={
        "name": "Tester", "student_id": "S1",
        "laboratory": "Robotics Lab", "date": "2027-01-20",
        "time": "10:00", "purpose": "project"
    })

    with app.app_context():
        latest = ServiceRequest.query.order_by(
            ServiceRequest.id.desc()
        ).first()
        workflow = Workflow.query.filter_by(request_id=latest.id).first()
        notes = workflow.plan["policy_notes"] if workflow else []

        check(
            "restricted lab raises a policy conflict",
            any(note["source"] == "lab-003" for note in notes)
        )

        first_lab_id = latest.id

    client.post(f"/approval/{first_lab_id}/approve")
    client.post(f"/execution/{first_lab_id}/execute")

    bookings = count(LaboratoryBooking)

    # The same lab and slot again: the knowledge base forbids double
    # booking, so this must be refused even after approval.
    client.post("/laboratory/book", data={
        "name": "Tester", "student_id": "S2",
        "laboratory": "Robotics Lab", "date": "2027-01-20",
        "time": "11:00", "purpose": "clashing"
    })

    with app.app_context():
        clash = ServiceRequest.query.order_by(
            ServiceRequest.id.desc()
        ).first()
        clash_id = clash.id

    client.post(f"/approval/{clash_id}/approve")
    client.post(f"/execution/{clash_id}/execute")

    with app.app_context():
        check(
            "double booking is refused",
            count(LaboratoryBooking) == bookings,
            f"{count(LaboratoryBooking) - bookings} extra bookings"
        )
        check(
            "refused request is not marked executed",
            db.session.get(ServiceRequest, clash_id).status != "Executed"
        )

    client.post("/grievance/submit", data={
        "name": "Tester", "category": "Harassment", "priority": "High",
        "subject": "Ragging", "description":
            "seniors threatened me in the hostel last night"
    })

    with app.app_context():
        grievance_request = ServiceRequest.query.order_by(
            ServiceRequest.id.desc()
        ).first()
        grievance_id = grievance_request.id

    client.post(f"/approval/{grievance_id}/approve")
    client.post(f"/execution/{grievance_id}/execute")

    with app.app_context():
        grievance = Grievance.query.order_by(Grievance.id.desc()).first()

        check(
            "harassment grievance is high priority",
            grievance is not None and grievance.priority == "HIGH"
        )
        check(
            "harassment grievance is escalated",
            grievance is not None and grievance.escalation_level > 0
        )
        check(
            "harassment grievance routes to the Dean",
            grievance is not None
            and "Dean" in (grievance.assigned_department or "")
        )

    # ----------------------------------------------------------
    section("MULTILINGUAL")

    before = count(ServiceRequest)

    reply = chat("How long does a bonafide certificate take?", "hi")

    check("pinned language answers grounded", reply["grounded"] is True)

    reply = chat("¿Hay que pagar por el certificado de traslado?")

    check("spanish question is detected", reply.get("language") == "es")
    check(
        "spanish question is treated as information",
        reply.get("category") == "information",
        reply.get("category")
    )
    check(
        "non-english question creates no request",
        count(ServiceRequest) == before,
        f"{count(ServiceRequest) - before} created"
    )

    # ----------------------------------------------------------
    section("PAGES")

    for path in ["/", "/audit", "/approval", "/execution", "/requests",
                 "/certificate", "/laboratory", "/grievance",
                 "/maintenance", "/api/health", "/api/agent/audit"]:

        check(f"{path} renders", client.get(path).status_code == 200)

    # ----------------------------------------------------------
    print()
    print("=" * 62)

    passed = CHECKS[0] - len(FAILURES)

    print(f"{passed}/{CHECKS[0]} checks passed")

    if FAILURES:
        print()
        print("Failed:")
        for name in FAILURES:
            print(" -", name)

    print(f"\nScratch database: {scratch}")

    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
