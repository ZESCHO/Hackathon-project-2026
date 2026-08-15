
from flask import Blueprint, request, jsonify

from app.models import db, User

from app.security.authentication import (
    login_user,
    logout_user,
    get_current_user
)


auth_bp = Blueprint(
    "auth",
    __name__,
    url_prefix="/api/auth"
)


# --------------------------------------------------
# REGISTER
# --------------------------------------------------

@auth_bp.route("/register", methods=["POST"])
def register():

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "success": False,
            "error": "JSON request body is required"
        }), 400

    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    student_id = data.get("student_id", "").strip()

    if not name:
        return jsonify({
            "success": False,
            "error": "Name is required"
        }), 400

    if not email:
        return jsonify({
            "success": False,
            "error": "Email is required"
        }), 400

    if not password:
        return jsonify({
            "success": False,
            "error": "Password is required"
        }), 400

    if len(password) < 8:
        return jsonify({
            "success": False,
            "error": "Password must contain at least 8 characters"
        }), 400

    existing_user = User.query.filter_by(
        email=email
    ).first()

    if existing_user:
        return jsonify({
            "success": False,
            "error": "An account with this email already exists"
        }), 409

    user = User(
        name=name,
        email=email,
        role="STUDENT",
        student_id=student_id or None
    )

    user.set_password(password)

    db.session.add(user)
    db.session.commit()

    return jsonify({
        "success": True,
        "message": "Account created successfully",
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role
        }
    }), 201


# --------------------------------------------------
# LOGIN
# --------------------------------------------------

@auth_bp.route("/login", methods=["POST"])
def login():

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "success": False,
            "error": "JSON request body is required"
        }), 400

    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({
            "success": False,
            "error": "Email and password are required"
        }), 400

    user = User.query.filter_by(
        email=email
    ).first()

    if user is None:
        return jsonify({
            "success": False,
            "error": "Invalid email or password"
        }), 401

    if not user.check_password(password):
        return jsonify({
            "success": False,
            "error": "Invalid email or password"
        }), 401

    if not user.is_active:
        return jsonify({
            "success": False,
            "error": "This account is inactive"
        }), 403

    login_user(user)

    return jsonify({
        "success": True,
        "message": "Login successful",
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role
        }
    })


# --------------------------------------------------
# LOGOUT
# --------------------------------------------------

@auth_bp.route("/logout", methods=["POST"])
def logout():

    logout_user()

    return jsonify({
        "success": True,
        "message": "Logout successful"
    })


# --------------------------------------------------
# CURRENT USER
# --------------------------------------------------

@auth_bp.route("/me", methods=["GET"])
def current_user():

    user = get_current_user()

    if user is None:
        return jsonify({
            "success": False,
            "error": "Not authenticated"
        }), 401

    return jsonify({
        "success": True,
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "student_id": user.student_id,
            "department": user.department
        }
    })
