
from datetime import datetime

from app.models.user import db


class Approval(db.Model):
    """
    One human decision, and who it was routed to.

    A request does not go into a single flat queue. Policy in the
    knowledge base decides which office owns it, and that decision is
    recorded here so the routing is visible and auditable rather than
    implied by whoever happens to open the page.
    """

    __tablename__ = "approvals"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    request_id = db.Column(
        db.Integer,
        db.ForeignKey("service_requests.id"),
        nullable=False,
        index=True
    )

    workflow_id = db.Column(
        db.Integer,
        db.ForeignKey("workflows.id"),
        nullable=True
    )

    action = db.Column(
        db.String(150),
        nullable=False
    )

    description = db.Column(
        db.Text,
        nullable=True
    )

    # The office this request belongs to, derived from policy rather
    # than chosen by the requester.
    routed_to = db.Column(
        db.String(120),
        nullable=False,
        default="Approval Center",
        index=True
    )

    # Why it went there, citing the knowledge base entry when policy
    # decided it.
    routing_reason = db.Column(
        db.String(255),
        nullable=True
    )

    # What a reviewer must hold to act on it.
    required_permission = db.Column(
        db.String(60),
        nullable=False,
        default="approve_requests"
    )

    status = db.Column(
        db.String(30),
        nullable=False,
        default="PENDING",
        index=True
    )

    decided_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
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

    request = db.relationship(
        "ServiceRequest",
        backref="approvals"
    )

    decider = db.relationship(
        "User",
        foreign_keys=[decided_by]
    )

    def decide(self, approved, user):
        self.status = "APPROVED" if approved else "REJECTED"
        self.decided_by = getattr(user, "id", None)
        self.decided_at = datetime.utcnow()

    def __repr__(self):
        return f"<Approval {self.id} -> {self.routed_to} ({self.status})>"
