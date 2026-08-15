from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


# =========================================================
# SERVICE REQUEST
# =========================================================

class ServiceRequest(db.Model):

    __tablename__ = "service_requests"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    service = db.Column(
        db.String(100),
        nullable=False
    )

    description = db.Column(
        db.Text,
        nullable=False
    )

    user_name = db.Column(
        db.String(150),
        nullable=False
    )

    status = db.Column(
        db.String(50),
        nullable=False,
        default="Pending Approval"
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )


# =========================================================
# AUDIT LOG
# =========================================================

class AuditLog(db.Model):

    __tablename__ = "audit_logs"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    action = db.Column(
        db.String(100),
        nullable=False
    )

    description = db.Column(
        db.Text,
        nullable=False
    )

    status = db.Column(
        db.String(50),
        nullable=False
    )

    user = db.Column(
        db.String(150),
        nullable=False,
        default="System"
    )

    timestamp = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )