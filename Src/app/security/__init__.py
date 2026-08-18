"""
Security helpers.

Authentication lives in app.py, which owns the session. This package
holds authorization only: what a signed-in user is allowed to do.
"""

from app.security.permissions import (
    can_act_on,
    is_master_reviewer,
    reviewer_department,
    ROLE_HIERARCHY,
    ROLE_PERMISSIONS,
    can,
    has_permission,
    normalize_role,
    outranks,
    permissions_for
)


__all__ = [
    "can_act_on",
    "is_master_reviewer",
    "reviewer_department",
    "ROLE_HIERARCHY",
    "ROLE_PERMISSIONS",
    "can",
    "has_permission",
    "normalize_role",
    "outranks",
    "permissions_for"
]
