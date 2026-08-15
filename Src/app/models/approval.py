
from datetime import datetime

from app.models.user import db


class Approval(db.Model):
    __tablename__ = "approvals"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    workflow_id = db.Column(
        db.Integer,
        db.ForeignKey("workflows.id"),
        nullable=False
    )

    requested_from = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )

    action = db.Column(
        db.String(150),
        nullable=False
    )

    description = db.Column(
        db.Text,
        nullable=False
    )

    status = db.Column(
        db.String(30),
        default="PENDING"
    )

    decision = db.Column(
        db.String(30),
        nullable=True
    )

    decided_at = db.Column(
        db.DateTime,
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    workflow = db.relationship(
        "Workflow",
        backref="approvals"
    )

    approver = db.relationship(
        "User",
        foreign_keys=[requested_from]
    )

    def approve(self):
        self.status = "APPROVED"
        self.decision = "APPROVE"
        self.decided_at = datetime.utcnow()

    def reject(self):
        self.status = "REJECTED"
        self.decision = "REJECT"
        self.decided_at = datetime.utcnow()
