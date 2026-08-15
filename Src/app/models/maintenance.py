
from datetime import datetime

from app.models.user import db


class MaintenanceTicket(db.Model):
    __tablename__ = "maintenance_tickets"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    ticket_number = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )

    location = db.Column(
        db.String(150),
        nullable=False
    )

    issue = db.Column(
        db.Text,
        nullable=False
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
        db.String(100),
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    resolved_at = db.Column(
        db.DateTime,
        nullable=True
    )

    user = db.relationship(
        "User",
        backref="maintenance_tickets"
    )
