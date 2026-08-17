from datetime import datetime, timedelta
import requests

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    session,
    flash
)
import os
from app.ai_agent import understand_request

from app.models import db, AuditLog, User
from app.models.request import ServiceRequest
from app.models.workflow import Workflow
from app.db_migrate import sync_columns
from app.workflows.executor import create_workflow, execute_workflow

# =========================================================
# FLASK APP
# =========================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "secure-agentic-ai-development-key"
)

# Only these categories may result in a filed service request.
# "information" is answered from verified sources and "unknown" is
# small talk; neither may create an institutional action.
ACTIONABLE_CATEGORIES = {
    "certificate",
    "maintenance",
    "laboratory",
    "grievance"
}

# How many turns of chat history to carry into the model.
MAX_HISTORY_TURNS = 12

# Window in which a second request of the same category from the same
# user is treated as an accidental duplicate rather than a new one.
DUPLICATE_WINDOW_SECONDS = 120


def _recent_duplicate(user, category):
    """
    Find a still-pending request this user just filed in this category.
    """

    cutoff = datetime.utcnow() - timedelta(
        seconds=DUPLICATE_WINDOW_SECONDS
    )

    return ServiceRequest.query.filter(
        ServiceRequest.user_id == user.id,
        ServiceRequest.category.ilike(category),
        ServiceRequest.status == "Pending Approval",
        ServiceRequest.created_at >= cutoff
    ).order_by(
        ServiceRequest.created_at.desc()
    ).first()


@app.route("/chat", methods=["POST"])
def chat():

    data = request.get_json(silent=True) or {}

    user = get_current_user()

    if not user:
        return jsonify({
            "reply": {
                "message": "Please login before using the assistant.",
                "status": "complete",
                "category": "unknown",
                "sources": [],
                "grounded": False
            }
        }), 401

    user_message = (data.get("message") or "").strip()

    if not user_message:
        return jsonify({
            "reply": {
                "message": "Please enter a message.",
                "status": "complete",
                "category": "unknown",
                "sources": [],
                "grounded": False
            }
        }), 400

    if len(user_message) > 2000:
        return jsonify({
            "reply": {
                "message": "That message is too long. Please shorten it.",
                "status": "complete",
                "category": "unknown",
                "sources": [],
                "grounded": False
            }
        }), 400

    history = session.get("chat_history", [])
    history.append({"role": "user", "content": user_message})

    user_request = understand_request(
        user_message,
        history[-MAX_HISTORY_TURNS:]
    )

    category = user_request.get("category", "unknown")

    # -----------------------------------------------------
    # FILE THE REQUEST ONCE EVERY REQUIRED FIELD IS PRESENT
    # -----------------------------------------------------

    if (
        user_request.get("status") == "complete"
        and category in ACTIONABLE_CATEGORIES
    ):

        fields = user_request.get("fields", {})

        description = " | ".join(
            f"{key}: {value}"
            for key, value in fields.items()
        )

        # A user answering a follow-up question after their request was
        # already filed would otherwise open a second, near-empty one.
        duplicate = _recent_duplicate(user, category)

        if duplicate is not None:

            user_request["request_id"] = duplicate.id

            user_request["message"] = (
                f"You already have a {category} request filed as "
                f"request #{duplicate.id}, still waiting for approval. "
                f"I haven't filed a duplicate."
            )

            session["chat_history"] = []

            return jsonify({"reply": user_request})

        service_request = create_approval_request(
            user=user,
            service=category.capitalize(),
            description=description,
            fields=fields,
            category=category
        )

        user_request["request_id"] = service_request.id

        user_request["message"] = (
            f"Your {category} request has been filed as "
            f"request #{service_request.id} and is waiting for "
            f"human approval."
        )

        history = []

    else:
        history.append({
            "role": "bot",
            "content": user_request.get("message", "")
        })

    session["chat_history"] = history[-MAX_HISTORY_TURNS:]

    return jsonify({"reply": user_request})


# =========================================================
# DATABASE CONFIGURATION
# =========================================================

app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URI",
    "sqlite:///database.db"
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)


# =========================================================
# CREATE DATABASE TABLES
# =========================================================

with app.app_context():

    db.create_all()

    # Columns added to a model after the database already existed are
    # not created by create_all(); add them in place.
    added_columns = sync_columns(db)

    if added_columns:
        print("Database columns added:", ", ".join(added_columns))

# ============================================================
# AI RISK & POLICY ENGINE
# ============================================================

def assess_request_risk(service_request):
    """
    Analyze a ServiceRequest and determine its risk level,
    reason, approval requirement and execution policy.
    """

    text = (
        (service_request.request_text or "")
        + " "
        + (service_request.category or "")
        + " "
        + (service_request.intent or "")
    ).lower()

    category = (service_request.category or "").lower()

    # --------------------------------------------------------
    # HIGH-RISK KEYWORDS
    # --------------------------------------------------------

    high_risk_keywords = [
        "payment",
        "refund",
        "money",
        "financial",
        "fee",
        "salary",
        "bank",
        "delete",
        "remove",
        "disciplinary",
        "suspend",
        "expel",
        "legal",
        "security",
        "password",
        "account",
        "access",
        "permission",
        "administrator",
    ]

    # --------------------------------------------------------
    # MEDIUM-RISK KEYWORDS
    # --------------------------------------------------------

    medium_risk_keywords = [
        "certificate",
        "bonafide",
        "study certificate",
        "document",
        "maintenance",
        "laboratory",
        "lab",
        "grievance",
        "complaint",
        "approval",
        "institutional",
        "student record",
    ]

    # --------------------------------------------------------
    # HIGH RISK CHECK
    # --------------------------------------------------------

    matched_high = [
        keyword
        for keyword in high_risk_keywords
        if keyword in text
    ]

    if matched_high:

        return {
            "level": "HIGH",
            "emoji": "🔴",
            "color": "high",
            "reason": (
                "The request may affect financial, security, "
                "access-control or other sensitive institutional operations."
            ),
            "approval_required": True,
            "execution_allowed": service_request.status.upper() == "APPROVED",
            "matched_keywords": matched_high,
        }

    # --------------------------------------------------------
    # MEDIUM RISK CHECK
    # --------------------------------------------------------

    matched_medium = [
        keyword
        for keyword in medium_risk_keywords
        if keyword in text
    ]

    if matched_medium or category in [
        "certificate",
        "maintenance",
        "laboratory",
        "grievance",
    ]:

        return {
            "level": "MEDIUM",
            "emoji": "🟡",
            "color": "medium",
            "reason": (
                "This request can result in a consequential "
                "institutional action or official service."
            ),
            "approval_required": True,
            "execution_allowed": service_request.status.upper() == "APPROVED",
            "matched_keywords": matched_medium,
        }

    # --------------------------------------------------------
    # LOW RISK
    # --------------------------------------------------------

    return {
        "level": "LOW",
        "emoji": "🟢",
        "color": "low",
        "reason": (
            "The request appears informational or non-consequential "
            "and does not indicate a sensitive institutional action."
        ),
        "approval_required": False,
        "execution_allowed": True,
        "matched_keywords": [],
    }

# ============================================================
# CURRENT USER
# ============================================================

def get_current_user():

    user_id = session.get("user_id")

    if not user_id:
        return None

    return User.query.get(user_id)

# =========================================================
# HOME / DASHBOARD
# =========================================================

@app.route("/")
def home():

    current_user = get_current_user()

    if not current_user:
        flash("Please login to access the dashboard.")
        return redirect(url_for("login"))

    base_query = ServiceRequest.query

    if current_user and current_user.role.upper() == "STUDENT":
        base_query = base_query.filter_by(user_id=current_user.id)

    total_requests = base_query.count()

    pending_requests = base_query.filter_by(
        status="Pending Approval"
    ).count()

    approved_requests = base_query.filter_by(
        status="Approved"
    ).count()

    rejected_requests = base_query.filter_by(
        status="Rejected"
    ).count()

    executed_requests = base_query.filter_by(
        status="Executed"
    ).count()

    certificate_requests = base_query.filter(
        ServiceRequest.category.ilike("%Certificate%")
    ).count()

    maintenance_requests = base_query.filter(
        ServiceRequest.category.ilike("%Maintenance%")
    ).count()

    laboratory_requests = base_query.filter(
        ServiceRequest.category.ilike("%Laboratory%")
    ).count()

    grievance_requests = base_query.filter(
        ServiceRequest.category.ilike("%Grievance%")
    ).count()

    recent_requests = base_query.order_by(
        ServiceRequest.created_at.desc()
    ).limit(5).all()

    return render_template(
        "dashboard.html",

        total_requests=total_requests,

        pending_requests=pending_requests,

        approved_requests=approved_requests,

        rejected_requests=rejected_requests,

        executed_requests=executed_requests,

        certificate_requests=certificate_requests,

        maintenance_requests=maintenance_requests,

        laboratory_requests=laboratory_requests,

        grievance_requests=grievance_requests,

        recent_requests=recent_requests
    )


# =========================================================
# AI REQUEST UNDERSTANDING
# =========================================================

@app.route(
    "/api/agent/understand",
    methods=["POST"]
)
def understand():
    
    current_user = get_current_user()

    if not current_user:
        return jsonify({
            "success": False,
            "message": "Login required."
        }), 401

    try:

        data = request.get_json(
            silent=True
        )

        print("Received data:", data)


        if not data:

            return jsonify({

                "success": False,

                "message":
                    "No JSON data received."

            }), 400


        user_request = (

            data.get("request")

            or data.get("message")

            or data.get("text")

        )


        if not user_request:

            return jsonify({

                "success": False,

                "message":
                    "Please enter a request."

            }), 400


        print(
            "User request:",
            user_request
        )


        result = understand_request(
            user_request
        )


        print(
            "AI result:",
            result
        )


        return jsonify({

            "success": True,

            "data": result

        })


    except Exception as e:

        print(
            "AI ERROR:",
            str(e)
        )


        return jsonify({

            "success": False,

            "message":
                "Something went wrong while processing your request.",

            "error":
                str(e)

        }), 500


# =========================================================
# CERTIFICATE PAGE
# =========================================================

@app.route("/certificate")
def certificate():

    if not get_current_user():
        flash("Please login to access certificate services.")
        return redirect(url_for("login"))

    return render_template(
        "certificate.html"
    )


# =========================================================
# MAINTENANCE PAGE
# =========================================================

@app.route("/maintenance")
def maintenance():

    if not get_current_user():
        flash("Please login to access maintenance services.")
        return redirect(url_for("login"))

    return render_template(
        "maintenance.html"
    )


# =========================================================
# LABORATORY PAGE
# =========================================================

@app.route("/laboratory")
def laboratory():

    if not get_current_user():
        flash("Please login to access laboratory services.")
        return redirect(url_for("login"))

    return render_template(
        "laboratory.html"
    )


# =========================================================
# GRIEVANCE PAGE
# =========================================================

@app.route("/grievance")
def grievance():

    if not get_current_user():
        flash("Please login to access grievance services.")
        return redirect(url_for("login"))

    return render_template(
        "grievance.html"
    )


# ============================================================
# CREATE APPROVAL REQUEST
# ============================================================

def create_approval_request(
    user,
    service,
    description,
    fields=None,
    category=None
):

    if not user:
        raise ValueError(
            "A logged-in user is required."
        )

    fields = fields or {}

    new_request = ServiceRequest(

        user_id=user.id,

        request_text=description,

        intent=service,

        category=service,

        status="Pending Approval",

        confidence=1.0,

        requires_approval=True,

        fields_json=fields

    )

    db.session.add(new_request)

    db.session.flush()


    # Plan the whole sequence up front, so a reviewer can see what the
    # platform intends to do before approving any part of it.
    workflow, plan = create_workflow(
        new_request,
        (category or service).lower(),
        fields
    )

    db.session.commit()


    audit = AuditLog(

        request_id=new_request.id,

        user_id=user.id,

        event_type="REQUEST_CREATED",

        action="Request Created",

        description=(
            f"{service}: {description}"
        ),

        actor_type="USER",

        status="Pending Approval",

        policy_checked=True,

        approval_required=True,

        approval_status="PENDING"

    )

    db.session.add(audit)

    db.session.commit()


    print()
    print("====================================")
    print("NEW SERVICE REQUEST")
    print("====================================")

    print("Request ID:", new_request.id)

    print("User ID:", user.id)

    print("User:", user.name)

    print("Service:", service)

    print("Status:", new_request.status)

    print("====================================")
    print()


    return new_request


# =========================================================
# GRIEVANCE SUBMISSION
# =========================================================

@app.route(
    "/grievance/submit",
    methods=["POST"]
)
def grievance_submit():

    user = get_current_user()

    if not user:
        flash("Please login before submitting a grievance.")
        return redirect(url_for("login"))

    name = request.form.get("name", "").strip() or user.name
    category = request.form.get("category", "").strip()
    priority = request.form.get("priority", "").strip()
    subject = request.form.get("subject", "").strip()
    description = request.form.get("description", "").strip()

    create_approval_request(
        user=user,
        service="Grievance",
        description=(
            f"{subject} | "
            f"Category: {category} | "
            f"Priority: {priority} | "
            f"{description}"
        ),
        fields={
            "subject": subject,
            "description": description,
            "category": category,
            "priority": priority,
            "reported_by": name
        },
        category="grievance"
    )

    return render_template(
        "success.html",
        title="Grievance Submitted",
        message=(
            "Your grievance has been securely recorded "
            "and is waiting for human review."
        )
    )


# =========================================================
# LABORATORY BOOKING
# =========================================================

@app.route(
    "/laboratory/book",
    methods=["POST"]
)
def laboratory_book():

    user = get_current_user()

    if not user:
        flash("Please login before submitting a laboratory booking.")
        return redirect(url_for("login"))

    name = request.form.get("name", "").strip() or user.name
    student_id = request.form.get("student_id", "").strip() or (user.student_id or "N/A")
    laboratory_name = request.form.get("laboratory", "").strip()
    booking_date = request.form.get("date", "").strip()
    booking_time = request.form.get("time", "").strip()
    purpose = request.form.get("purpose", "").strip()

    create_approval_request(
        user=user,
        service="Laboratory Booking",
        description=(
            f"{laboratory_name} on "
            f"{booking_date} from {booking_time}. "
            f"Student: {name}. "
            f"Student ID: {student_id}. "
            f"Purpose: {purpose}"
        ),
        fields={
            "laboratory_name": laboratory_name,
            "booking_date": booking_date,
            "booking_time": booking_time,
            "purpose": purpose,
            "student_id": student_id,
            "reported_by": name
        },
        category="laboratory"
    )

    return render_template(
        "success.html",
        title="Laboratory Booking Submitted",
        message=(
            "Your laboratory booking request "
            "has been submitted and is waiting "
            "for approval."
        )
    )


# =========================================================
# MAINTENANCE REQUEST
# =========================================================

@app.route(
    "/maintenance/request",
    methods=["POST"]
)
def maintenance_request():

    user = get_current_user()

    if not user:
        flash("Please login before submitting a maintenance request.")
        return redirect(url_for("login"))

    name = request.form.get("name", "").strip() or user.name
    location = request.form.get("location", "").strip()
    room = request.form.get("room", "").strip()
    category = request.form.get("category", "").strip()
    priority = request.form.get("priority", "").strip()
    description = request.form.get("description", "").strip()

    create_approval_request(
        user=user,
        service="Maintenance",
        description=(
            f"Location: {location} | "
            f"Room: {room} | "
            f"Category: {category} | "
            f"Priority: {priority} | "
            f"Reported by: {name} | "
            f"{description}"
        ),
        fields={
            "location": location,
            "room": room,
            "description": description,
            "category": category,
            "priority": priority,
            "reported_by": name
        },
        category="maintenance"
    )

    return render_template(
        "success.html",
        title="Maintenance Ticket Submitted",
        message=(
            "Your maintenance ticket has been "
            "submitted and is waiting for review."
        )
    )


# ============================================================
# CERTIFICATE REQUEST
# ============================================================

@app.route("/certificate/request", methods=["POST"])
def certificate_request():

    # --------------------------------------------------------
    # GET LOGGED-IN USER
    # --------------------------------------------------------

    user = get_current_user()

    if not user:

        flash(
            "Please login before submitting a certificate request."
        )

        return redirect(url_for("login"))


    # --------------------------------------------------------
    # GET FORM DATA
    # --------------------------------------------------------

    student_name = request.form.get(
        "student_name",
        ""
    ).strip()

    student_id = request.form.get(
        "student_id",
        ""
    ).strip()

    certificate_type = request.form.get(
        "certificate_type",
        ""
    ).strip()

    purpose = request.form.get(
        "purpose",
        ""
    ).strip()


    # --------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------

    if not student_name:

        flash("Please enter your name.")

        return redirect(url_for("certificate"))


    if not student_id:

        flash("Please enter your Student ID.")

        return redirect(url_for("certificate"))


    if not certificate_type:

        flash("Please select a certificate type.")

        return redirect(url_for("certificate"))


    if not purpose:

        flash("Please enter the purpose.")

        return redirect(url_for("certificate"))


    # --------------------------------------------------------
    # CREATE SERVICE REQUEST
    # --------------------------------------------------------

    create_approval_request(

        user=user,

        service="Certificate Request",

        description=(
            f"{certificate_type} for {student_name}. "
            f"Student ID: {student_id}. "
            f"Purpose: {purpose}"
        ),

        fields={
            "certificate_type": certificate_type,
            "purpose": purpose,
            "student_id": student_id,
            "reported_by": student_name
        },

        category="certificate"

    )


    # --------------------------------------------------------
    # TERMINAL LOG
    # --------------------------------------------------------

    print()
    print("====================================")
    print("CERTIFICATE REQUEST")
    print("====================================")

    print("User ID:", user.id)

    print("User:", user.name)

    print("Student:", student_name)

    print("Student ID:", student_id)

    print("Certificate:", certificate_type)

    print("Purpose:", purpose)

    print("====================================")
    print()


    # --------------------------------------------------------
    # SUCCESS PAGE
    # --------------------------------------------------------

    return render_template(

        "success.html",

        title="Certificate Request Submitted",

        message=(
            "Your certificate request has been submitted "
            "successfully and is waiting for human approval."
        )

    )


# ============================================================
# ADMIN / REVIEWER ACCESS CONTROL
# ============================================================

def require_reviewer():

    # Get the currently logged-in user
    user = get_current_user()

    # --------------------------------------------------------
    # NOT LOGGED IN
    # --------------------------------------------------------

    if user is None:

        flash(
            "Please login to access the Approval Center."
        )

        return None, redirect(
            url_for("login")
        )


    # --------------------------------------------------------
    # CHECK ROLE
    # --------------------------------------------------------

    role = (user.role or "").upper().strip()


    # --------------------------------------------------------
    # ADMIN / REVIEWER ALLOWED
    # --------------------------------------------------------

    if role in ["ADMIN", "REVIEWER"]:

        return user, None


    # --------------------------------------------------------
    # STUDENT / UNAUTHORIZED
    # --------------------------------------------------------

    flash(
        "You are not authorized to access this area."
    )

    return None, redirect(
        url_for("home")
    )


# =========================================================
# APPROVAL CENTER
# =========================================================

@app.route("/approval")
def approval_page():

    reviewer, response = require_reviewer()

    if response:
        return response

    requests = ServiceRequest.query.order_by(
        ServiceRequest.created_at.desc()
    ).all()

    # The stored plan, so the reviewer can see the intended steps and
    # the policy findings before approving anything.
    request_plans = {}

    for item in requests:

        workflow = Workflow.query.filter_by(
            request_id=item.id
        ).first()

        if workflow and workflow.plan:
            request_plans[item.id] = workflow.plan

    return render_template(
        "approval.html",
        requests=requests,
        request_plans=request_plans
    )


# =========================================================
# APPROVE REQUEST
# =========================================================

@app.route(
    "/approval/<int:request_id>/approve",
    methods=["POST"]
)
def approve_request(request_id):

    reviewer, response = require_reviewer()

    if response:
        return response

    service_request = ServiceRequest.query.get_or_404(

        request_id

    )


    # -----------------------------------------------------
    # UPDATE REQUEST
    # -----------------------------------------------------

    service_request.status = "Approved"

    db.session.commit()


    # -----------------------------------------------------
    # AUDIT LOG
    # -----------------------------------------------------

    audit = AuditLog(

        request_id=service_request.id,

        user_id=service_request.user_id,

        event_type="REQUEST_APPROVED",

        action="Request Approved",

        description=(

            f"{service_request.category} "

            f"(Request #{service_request.id})"

        ),

        actor_type="ADMIN",

        status="Approved",

        policy_checked=True,

        approval_required=True,

        approval_status="Approved",

        tool_name=None

    )


    db.session.add(
        audit
    )

    db.session.commit()


    return render_template(

        "success.html",

        title="Request Approved",

        status_label="Approved",

        request_id=service_request.id,

        message=(
            "The request has been approved and the decision has been "
            "recorded in the audit trail. It can now be executed from "
            "the Execution Center."
        )

    )



# =========================================================
# REJECT REQUEST
# =========================================================

@app.route(
    "/approval/<int:request_id>/reject",
    methods=["POST"]
)
def reject_request(request_id):

    reviewer, response = require_reviewer()

    if response:
        return response

    service_request = ServiceRequest.query.get_or_404(

        request_id

    )


    # -----------------------------------------------------
    # UPDATE REQUEST
    # -----------------------------------------------------

    service_request.status = "Rejected"

    db.session.commit()


    # -----------------------------------------------------
    # AUDIT LOG
    # -----------------------------------------------------

    audit = AuditLog(

        request_id=service_request.id,

        user_id=service_request.user_id,

        event_type="REQUEST_REJECTED",

        action="Request Rejected",

        description=(

            f"{service_request.category} "

            f"(Request #{service_request.id})"

        ),

        actor_type="ADMIN",

        status="Rejected",

        policy_checked=True,

        approval_required=True,

        approval_status="Rejected",

        tool_name=None

    )


    db.session.add(
        audit
    )

    db.session.commit()


    return render_template(

        "success.html",

        title="Request Rejected",

        status_label="Rejected",

        request_id=service_request.id,

        message=(
            "The request has been rejected and the decision has been "
            "recorded in the audit trail. No action will be carried out."
        )

    )


# =========================================================
# AUDIT TRAIL PAGE
# =========================================================

@app.route("/audit")
def audit_page():

    reviewer, response = require_reviewer()

    if response:
        return response

    records = AuditLog.query.order_by(
        AuditLog.timestamp.desc()
    ).all()

    return render_template(
        "audit.html",
        records=records
    )

# =========================================================
# AUDIT API
# =========================================================

@app.route("/api/agent/audit")
def audit():

    reviewer, response = require_reviewer()

    if response:
        return jsonify({
            "status": "error",
            "message": "Unauthorized"
        }), 403

    records = AuditLog.query.order_by(

        AuditLog.timestamp.desc()

    ).all()


    result = []


    for record in records:

        result.append({

            "id":
                record.id,

            "request_id":
                record.request_id,

            "user_id":
                record.user_id,

            "event_type":
                record.event_type,

            "action":
                record.action,

            "description":
                record.description,

            "actor_type":
                record.actor_type,

            "status":
                record.status,

            "policy_checked":
                record.policy_checked,

            "approval_required":
                record.approval_required,

            "approval_status":
                record.approval_status,

            "tool_name":
                record.tool_name,

            "timestamp":
                record.timestamp.strftime(
                    "%d %b %Y, %I:%M:%S %p"
                )

        })


    return jsonify({

        "status": "success",

        "records": result

    })


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route("/api/health")
def health():

    return jsonify({

        "status": "healthy",

        "service":
            "Secure Agentic AI Platform"

    })

# =========================================================
# EXECUTION CENTER
# =========================================================

@app.route("/execution")
def execution_page():

    reviewer, response = require_reviewer()

    if response:
        return response

    # Only human-approved requests are eligible for the execution center.
    requests = ServiceRequest.query.filter_by(
        status="Approved"
    ).order_by(
        ServiceRequest.created_at.desc()
    ).all()

    # Send the policy assessment to the template so the UI can explain
    # why the request is or is not eligible for controlled execution.
    request_policies = {
        item.id: assess_request_risk(item)
        for item in requests
    }

    return render_template(
        "execution.html",
        requests=requests,
        request_policies=request_policies
    )

# =========================================================
# EXECUTE APPROVED REQUEST
# =========================================================

# =========================================================
# SECURITY POLICY CHECK
# =========================================================

def check_execution_policy(service_request):

    # -----------------------------------------------------
    # POLICY 1: Request must exist
    # -----------------------------------------------------

    if service_request is None:

        return {
            "allowed": False,
            "reason": "Request does not exist."
        }

    # -----------------------------------------------------
    # POLICY 2: Human approval is mandatory
    # -----------------------------------------------------

    status = (service_request.status or "").strip().lower()

    if status != "approved":

        return {
            "allowed": False,
            "reason": (
                "Execution blocked: human approval is required."
            )
        }

    # -----------------------------------------------------
    # POLICY 3: Requests explicitly marked as requiring
    # approval must have an approved status.
    # -----------------------------------------------------

    if service_request.requires_approval and status != "approved":

        return {
            "allowed": False,
            "reason": (
                "Execution blocked: required human approval "
                "was not found."
            )
        }

    # -----------------------------------------------------
    # POLICY 4: Run the centralized risk/policy assessment.
    # -----------------------------------------------------

    risk_policy = assess_request_risk(service_request)

    if risk_policy["approval_required"] and status != "approved":

        return {
            "allowed": False,
            "reason": (
                "Execution blocked: the policy engine requires "
                "explicit human approval."
            )
        }

    # -----------------------------------------------------
    # POLICY PASSED
    # -----------------------------------------------------

    return {
        "allowed": True,
        "reason": "All execution security policies passed.",
        "risk_level": risk_policy["level"],
        "risk_reason": risk_policy["reason"]
    }


# =========================================================
# CONTROLLED EXECUTION
# =========================================================

@app.route(
    "/execution/<int:request_id>/execute",
    methods=["POST"]
)
def execute_request(request_id):

    reviewer, response = require_reviewer()

    if response:
        return response

    service_request = ServiceRequest.query.get_or_404(
        request_id
    )


    # -----------------------------------------------------
    # SECURITY POLICY CHECK
    # -----------------------------------------------------

    policy_result = check_execution_policy(
        service_request
    )


    # -----------------------------------------------------
    # BLOCK UNSAFE EXECUTION
    # -----------------------------------------------------

    if not policy_result["allowed"]:

        blocked_audit = AuditLog(

            request_id=service_request.id,

            user_id=service_request.user_id,

            event_type="POLICY_BLOCK",

            action="Execution Blocked",

            description=(
                f"Request #{service_request.id}: "
                f"{policy_result['reason']}"
            ),

            actor_type="Policy Engine",

            status="Blocked",

            policy_checked=True,

            approval_required=True,

            approval_status=service_request.status,

            tool_name="Execution Policy Engine"

        )

        db.session.add(blocked_audit)

        db.session.commit()


        return render_template(

            "success.html",

            title="Execution Blocked",

            status_label=service_request.status,

            message=(
                "This action was blocked by the security policy "
                "engine before anything was carried out."
            ),

            error=policy_result["reason"],

            request_id=service_request.id

        )


    # -----------------------------------------------------
    # POLICY PASSED - RUN THE PLANNED WORKFLOW
    # -----------------------------------------------------

    outcome = execute_workflow(service_request)


    # -----------------------------------------------------
    # A TOOL REFUSED: THE REQUEST IS NOT EXECUTED
    # -----------------------------------------------------

    if not outcome["ok"]:

        db.session.commit()

        return render_template(
            "success.html",
            title="Execution Failed",
            status_label="Approved - not executed",
            message=(
                "The request was approved, but the workflow could not "
                "be completed. Nothing has been changed."
            ),
            error=outcome["error"],
            steps=outcome["results"],
            request_id=service_request.id
        )


    # -----------------------------------------------------
    # EVERY STEP COMPLETED
    # -----------------------------------------------------

    service_request.status = "Executed"

    service_request.updated_at = datetime.utcnow()

    db.session.commit()

    return render_template(

        "success.html",

        title="Action Executed",

        status_label="Executed",

        message=(
            "The request passed the security policy check and every "
            "planned step was carried out."
        ),

        steps=outcome["results"],

        request_id=service_request.id

    )

# =========================================================
# REQUEST TRACKING
# =========================================================

@app.route("/requests")
def requests_page():

    user = get_current_user()

    if not user:
        flash("Please login to view your requests.")
        return redirect(url_for("login"))

    requests = ServiceRequest.query.filter_by(
        user_id=user.id
    ).order_by(
        ServiceRequest.created_at.desc()
    ).all()

    return render_template(
        "requests.html",
        requests=requests
    )


# ============================================================
# REGISTER
# ============================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    # Show registration page
    if request.method == "GET":
        return render_template("register.html")

    # Get form data
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    student_id = request.form.get("student_id", "").strip()
    password = request.form.get("password", "")
    confirm_password = request.form.get(
        "confirm_password",
        ""
    )

    # --------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------

    if not name or not email or not student_id or not password:
        flash("Please fill in all required fields.")
        return redirect(url_for("register"))

    if password != confirm_password:
        flash("Passwords do not match.")
        return redirect(url_for("register"))

    if len(password) < 6:
        flash("Password must contain at least 6 characters.")
        return redirect(url_for("register"))

    # --------------------------------------------------------
    # CHECK EXISTING EMAIL
    # --------------------------------------------------------

    existing_email = User.query.filter_by(
        email=email
    ).first()

    if existing_email:

        flash(
            "An account with this email already exists."
        )

        return redirect(url_for("login"))

    # --------------------------------------------------------
    # CHECK EXISTING STUDENT ID
    # --------------------------------------------------------

    existing_student = User.query.filter_by(
        student_id=student_id
    ).first()

    if existing_student:

        flash(
            "This Student ID is already registered."
        )

        return redirect(url_for("register"))

    # --------------------------------------------------------
    # CREATE USER
    # --------------------------------------------------------

    new_user = User(

        name=name,

        email=email,

        student_id=student_id,

        role="STUDENT",

        is_active=True

    )

    # NEVER store the password directly
    new_user.set_password(password)

    db.session.add(new_user)

    db.session.commit()

    print()
    print("====================================")
    print("NEW USER REGISTERED")
    print("====================================")
    print("User ID:", new_user.id)
    print("Name:", new_user.name)
    print("Email:", new_user.email)
    print("Student ID:", new_user.student_id)
    print("Role:", new_user.role)
    print("====================================")
    print()

    flash(
        "Account created successfully. Please login."
    )

    return redirect(url_for("login"))

# ============================================================
# LOGIN
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    # Show login page
    if request.method == "GET":
        return render_template("login.html")

    # Get login information
    email = request.form.get(
        "email",
        ""
    ).strip().lower()

    password = request.form.get(
        "password",
        ""
    )

    # --------------------------------------------------------
    # BASIC VALIDATION
    # --------------------------------------------------------

    if not email or not password:

        flash(
            "Please enter your email and password."
        )

        return redirect(url_for("login"))

    # --------------------------------------------------------
    # FIND USER
    # --------------------------------------------------------

    user = User.query.filter_by(
        email=email
    ).first()

    # --------------------------------------------------------
    # VERIFY USER
    # --------------------------------------------------------

    if user is None or not user.check_password(password):

        flash(
            "Invalid email or password."
        )

        return redirect(url_for("login"))

    # --------------------------------------------------------
    # CHECK ACCOUNT STATUS
    # --------------------------------------------------------

    if not user.is_active:

        flash(
            "Your account has been disabled."
        )

        return redirect(url_for("login"))

    # --------------------------------------------------------
    # CREATE SESSION
    # --------------------------------------------------------

    session.clear()

    session["user_id"] = user.id
    session["user_name"] = user.name
    session["user_role"] = user.role
    session["user_email"] = user.email

    print()
    print("====================================")
    print("USER LOGIN")
    print("====================================")
    print("User ID:", user.id)
    print("Name:", user.name)
    print("Role:", user.role)
    print("====================================")
    print()

    flash(
        f"Welcome back, {user.name}!"
    )

    return redirect(url_for("home"))

# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    user_name = session.get(
        "user_name",
        "User"
    )

    session.clear()

    flash(
        f"{user_name} has been logged out."
    )

    return redirect(url_for("login"))


# =========================================================
# ADMIN ACCOUNT SETUP + RUN APPLICATION
# =========================================================

def create_default_admin():

    with app.app_context():

        admin = User.query.filter_by(
            email="admin@secureai.com"
        ).first()

        if admin is None:

            admin = User(
                name="System Administrator",
                email="admin@secureai.com",
                role="ADMIN",
                is_active=True
            )

            admin.set_password("Admin@123")

            db.session.add(admin)
            db.session.commit()

            print()
            print("====================================")
            print("✅ ADMIN ACCOUNT CREATED")
            print("====================================")
            print("Email: admin@secureai.com")
            print("Password: Admin@123")
            print("Role: ADMIN")
            print("====================================")
            print()

        else:

            admin.role = "ADMIN"
            admin.is_active = True

            admin.set_password("Admin@123")

            db.session.commit()

            print()
            print("====================================")
            print("✅ ADMIN ACCOUNT READY")
            print("====================================")
            print("Email: admin@secureai.com")
            print("Password: Admin@123")
            print("Role: ADMIN")
            print("====================================")
            print()


if __name__ == "__main__":

    create_default_admin()

    app.run(
        debug=True,
        host="127.0.0.1",
        port=5000
    )