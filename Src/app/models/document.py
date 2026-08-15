
from datetime import datetime

from app.models.user import db


class InstitutionalDocument(db.Model):
    __tablename__ = "institutional_documents"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    title = db.Column(
        db.String(255),
        nullable=False
    )

    document_type = db.Column(
        db.String(100),
        nullable=False
    )

    source = db.Column(
        db.String(500),
        nullable=False
    )

    version = db.Column(
        db.String(50),
        nullable=True
    )

    content_hash = db.Column(
        db.String(128),
        nullable=True
    )

    verified = db.Column(
        db.Boolean,
        default=False
    )

    verified_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=True
    )

    verified_at = db.Column(
        db.DateTime,
        nullable=True
    )

    uploaded_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    verifier = db.relationship(
        "User",
        foreign_keys=[verified_by]
    )
