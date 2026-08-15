
from flask import Blueprint, jsonify


# --------------------------------------------------
# Main API Blueprint
# --------------------------------------------------

main_bp = Blueprint(
    "main",
    __name__,
    url_prefix="/api"
)


@main_bp.route("/status", methods=["GET"])
def status():

    return jsonify({
        "success": True,
        "application": "Secure Agentic-AI Platform",
        "status": "online"
    })


@main_bp.route("/services", methods=["GET"])
def services():

    services_list = [
        {
            "id": "certificate",
            "name": "Certificate Request",
            "description": "Request institutional certificates."
        },
        {
            "id": "maintenance",
            "name": "Maintenance Ticket",
            "description": "Report campus maintenance issues."
        },
        {
            "id": "laboratory",
            "name": "Laboratory Booking",
            "description": "Request laboratory reservations."
        },
        {
            "id": "grievance",
            "name": "Grievance Escalation",
            "description": "Submit and escalate grievances."
        }
    ]

    return jsonify({
        "success": True,
        "services": services_list
    })


# --------------------------------------------------
# Authentication Blueprint
# --------------------------------------------------

from app.routes.auth_routes import auth_bp
from app.routes.agent_routes import agent_bp