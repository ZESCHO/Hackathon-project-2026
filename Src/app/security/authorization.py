from functools import wraps

from flask import jsonify

from app.security.authentication import get_current_user


ROLE_HIERARCHY = {
    "STUDENT": 1,
    "FACULTY": 2,
    "STAFF": 3,
    "ADMIN": 4
}


def has_role(required_role):
    """
    Check whether the current user has the required role.
    """

    user = get_current_user()

    if user is None:
        return False

    current_level = ROLE_HIERARCHY.get(
        user.role,
        0
    )

    required_level = ROLE_HIERARCHY.get(
        required_role,
        999
    )

    return current_level >= required_level


def role_required(required_role):
    """
    Protect a route using role-based authorization.
    """

    def decorator(function):

        @wraps(function)
        def decorated_function(*args, **kwargs):

            user = get_current_user()

            if user is None:
                return jsonify({
                    "success": False,
                    "error": "Authentication required"
                }), 401

            if not has_role(required_role):
                return jsonify({
                    "success": False,
                    "error": "Insufficient permissions"
                }), 403

            return function(*args, **kwargs)

        return decorated_function

    return decorator
