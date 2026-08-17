
from datetime import datetime

from app.models.user import db


class ServiceRequest(db.Model):
    __tablename__ = "service_requests"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )

    request_text = db.Column(
        db.Text,
        nullable=False
    )

    intent = db.Column(
        db.String(100),
        nullable=True
    )

    category = db.Column(
        db.String(50),
        nullable=True
    )

    status = db.Column(
        db.String(30),
        nullable=False,
        default="PENDING"
    )

    confidence = db.Column(
        db.Float,
        nullable=True
    )

    requires_approval = db.Column(
        db.Boolean,
        default=False
    )

    # The structured values collected for this request, keyed by the
    # canonical field names in app/ai_agent.py. Execution reads these
    # rather than trying to parse them back out of request_text.
    fields_json = db.Column(
        db.JSON,
        nullable=True
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
        backref="service_requests"
    )

    def __repr__(self):
        return f"<ServiceRequest {self.id}>"
