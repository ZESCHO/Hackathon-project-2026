
"""
Controlled AI tools.

The AI agent must NOT directly access the database.

Instead, it will use controlled tools that perform
security and permission checks before executing actions.
"""

AVAILABLE_TOOLS = [
    "get_student_profile",
    "check_certificate_eligibility",
    "create_certificate_request",
    "get_lab_availability",
    "create_lab_booking",
    "create_maintenance_ticket",
    "get_ticket_status",
    "create_grievance",
    "escalate_grievance",
    "send_notification"
]
