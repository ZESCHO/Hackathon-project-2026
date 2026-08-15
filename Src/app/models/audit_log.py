
from datetime import datetime

from app.models.user import db


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    request_id = db.Column(
        db.Integer,
        db.ForeignKey("service_requests.id"),
        nullable=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=True
    )

    event_type = db.Column(
        db.String(100),
        nullable=False
    )

    action = db.Column(
        db.String(150),
        nullable=True
    )

    description = db.Column(
        db.Text,
        nullable=True
    )

    actor_type = db.Column(
        db.String(30),
        nullable=False
    )

    status = db.Column(
        db.String(30),
        nullable=True
    )

    policy_checked = db.Column(
        db.Boolean,
        default=False
    )

    approval_required = db.Column(
        db.Boolean,
        default=False
    )

    approval_status = db.Column(
        db.String(30),
        nullable=True
    )

    tool_name = db.Column(
        db.String(150),
        nullable=True
    )

    metadata_json = db.Column(
        db.JSON,
        nullable=True
    )

    timestamp = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    user = db.relationship(
        "User",
        foreign_keys=[user_id]
    )

    request = db.relationship(
        "ServiceRequest",
        foreign_keys=[request_id]
    )

    def __repr__(self):
        return f"<AuditLog {self.id} - {self.event_type}>"
