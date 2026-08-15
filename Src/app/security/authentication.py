from functools import wraps

from flask import session, jsonify
from app.models import User


def login_user(user):
    """
    Store the authenticated user's ID in the session.
    """

    session["user_id"] = user.id
    session["user_role"] = user.role


def logout_user():
    """
    Remove authentication information from the session.
    """

    session.pop("user_id", None)
    session.pop("user_role", None)


def get_current_user():
    """
    Return the currently authenticated user.

    Returns:
        User object or None
    """

    user_id = session.get("user_id")

    if not user_id:
        return None

    return User.query.get(user_id)


def is_authenticated():
    """
    Check whether a user is logged in.
    """

    return get_current_user() is not None


def login_required(function):
    """
    Protect a route so only authenticated users
    can access it.
    """

    @wraps(function)
    def decorated_function(*args, **kwargs):

        user = get_current_user()

        if user is None:
            return jsonify({
                "success": False,
                "error": "Authentication required"
            }), 401

        if not user.is_active:
            return jsonify({
                "success": False,
                "error": "Account is inactive"
            }), 403

        return function(*args, **kwargs)

    return decorated_function
