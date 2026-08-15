
from datetime import datetime

from app.models.user import db


class CertificateRequest(db.Model):
    __tablename__ = "certificate_requests"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )

    request_id = db.Column(
        db.Integer,
        db.ForeignKey("service_requests.id"),
        nullable=True
    )

    certificate_type = db.Column(
        db.String(100),
        nullable=False
    )

    purpose = db.Column(
        db.String(255),
        nullable=False
    )

    status = db.Column(
        db.String(30),
        default="PENDING"
    )

    submitted_at = db.Column(
        db.DateTime,
        nullable=True
    )

    completed_at = db.Column(
        db.DateTime,
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    user = db.relationship(
        "User",
        backref="certificate_requests"
    )
