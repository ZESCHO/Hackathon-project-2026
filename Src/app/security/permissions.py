ROLE_PERMISSIONS = {

    "STUDENT": {
        "view_profile",
        "create_certificate_request",
        "create_maintenance_ticket",
        "view_lab_availability",
        "request_lab_booking",
        "create_grievance",
        "view_own_requests"
    },

    "FACULTY": {
        "view_profile",
        "create_certificate_request",
        "create_maintenance_ticket",
        "view_lab_availability",
        "request_lab_booking",
        "create_grievance",
        "view_own_requests",
        "approve_student_request"
    },

    "STAFF": {
        "view_profile",
        "manage_certificate_requests",
        "manage_maintenance_tickets",
        "manage_lab_bookings",
        "manage_grievances",
        "approve_requests",
        "view_audit_logs"
    },

    "ADMIN": {
        "view_profile",
        "manage_users",
        "manage_certificate_requests",
        "manage_maintenance_tickets",
        "manage_lab_bookings",
        "manage_grievances",
        "approve_requests",
        "manage_policies",
        "manage_documents",
        "view_audit_logs",
        "manage_system"
    }
}


def has_permission(role, permission):
    """
    Check whether a role has a specific permission.
    """

    permissions = ROLE_PERMISSIONS.get(
        role,
        set()
    )

    return permission in permissions
