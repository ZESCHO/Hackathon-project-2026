
from datetime import datetime

from app.models.user import db


class Grievance(db.Model):
    __tablename__ = "grievances"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )

    subject = db.Column(
        db.String(200),
        nullable=False
    )

    description = db.Column(
        db.Text,
        nullable=False
    )

    category = db.Column(
        db.String(100),
        nullable=True
    )

    priority = db.Column(
        db.String(30),
        default="NORMAL"
    )

    status = db.Column(
        db.String(30),
        default="OPEN"
    )

    assigned_department = db.Column(
        db.String(120),
        nullable=True
    )

    escalation_level = db.Column(
        db.Integer,
        default=0
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    user = db.relationship(
        "User",
        backref="grievances"
    )
