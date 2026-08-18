"""
Role-based authorization.

One table decides what each role may do. Routes ask for the permission
they need rather than naming roles inline, so adding a role means
editing this table and nothing else.

Checks are on permissions, not on role names. A route that says
`role in ("ADMIN", "REVIEWER")` has to be found and edited every time
the roles change, and one that gets missed is a hole.
"""


# Ordered from least to most privileged. Used only where a genuine
# ranking is meaningful, such as "at least a reviewer".
ROLE_HIERARCHY = [
    "STUDENT",
    "FACULTY",
    "STAFF",
    "REVIEWER",
    "ADMIN"
]


# What each role may do. Permissions are additive: a role's entry lists
# everything it may do, including anything a lesser role may do.
ROLE_PERMISSIONS = {

    "STUDENT": {
        "view_profile",
        "use_assistant",
        "create_certificate_request",
        "create_maintenance_ticket",
        "request_lab_booking",
        "create_grievance",
        "view_own_requests"
    },

    "FACULTY": {
        "view_profile",
        "use_assistant",
        "create_certificate_request",
        "create_maintenance_ticket",
        "request_lab_booking",
        "create_grievance",
        "view_own_requests",
        # Faculty co-sign restricted laboratory bookings.
        "cosign_lab_booking"
    },

    "STAFF": {
        "view_profile",
        "use_assistant",
        "view_own_requests",
        "view_all_requests",
        "view_audit_logs"
    },

    "REVIEWER": {
        "view_profile",
        "use_assistant",
        "view_own_requests",
        "view_all_requests",
        "view_audit_logs",
        "approve_requests",
        "execute_requests"
    },

    "ADMIN": {
        "view_profile",
        "use_assistant",
        "view_own_requests",
        "view_all_requests",
        "view_audit_logs",
        "approve_requests",
        "execute_requests",
        "cosign_lab_booking",
        "manage_users",
        "manage_policies",
        "manage_system"
    }
}


def normalize_role(role):
    """
    Reduce a stored role to a known one, defaulting to the least
    privileged. An unrecognised role must never gain access.
    """

    candidate = (role or "").strip().upper()

    return candidate if candidate in ROLE_PERMISSIONS else "STUDENT"


def permissions_for(role):
    """
    Every permission a role holds.
    """

    return ROLE_PERMISSIONS[normalize_role(role)]


def has_permission(role, permission):
    """
    Whether a role may perform an action.
    """

    return permission in permissions_for(role)


def can(user, permission):
    """
    Whether a user may perform an action.

    A missing or disabled account can do nothing, so callers do not
    have to remember to check is_active separately.
    """

    if user is None or not getattr(user, "is_active", False):
        return False

    return has_permission(getattr(user, "role", None), permission)


def outranks(role, other):
    """
    Whether `role` sits above `other` in the hierarchy.
    """

    order = {name: index for index, name in enumerate(ROLE_HIERARCHY)}

    return order[normalize_role(role)] > order[normalize_role(other)]


# =========================================================
# DEPARTMENT SCOPE
# =========================================================

# Only this role oversees every department. Master status is decided
# by the role, never by an empty department: a reviewer whose
# department was never filled in is a misconfigured account, and
# reading that as "sees everything" would hand it the whole system.
MASTER_ROLE = "ADMIN"


def is_master_reviewer(user):
    """
    Whether this user oversees every department.
    """

    if not can(user, "approve_requests"):
        return False

    return normalize_role(getattr(user, "role", None)) == MASTER_ROLE


def reviewer_department(user):
    """
    The office a reviewer belongs to, or None for a master admin.
    """

    return (getattr(user, "department", None) or "").strip() or None


def can_act_on(user, routed_to):
    """
    Whether this user may decide a request routed to a given office.

    This is the actual control. Which page a reviewer lands on is
    navigation; anyone can post a request id at an endpoint. The
    Registrar must not be able to approve a maintenance ticket by
    guessing its number, whatever page they came from.
    """

    if not can(user, "approve_requests"):
        return False

    if is_master_reviewer(user):
        return True

    # A scoped reviewer with no department set can act on nothing.
    # Failing closed is the safe direction: a half-configured account
    # should approve nothing rather than everything.
    department = reviewer_department(user)

    if not department:
        return False

    return department.strip().lower() == (routed_to or "").strip().lower()
