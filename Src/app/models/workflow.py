
from datetime import datetime

from app.models.user import db


class Workflow(db.Model):
    __tablename__ = "workflows"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    request_id = db.Column(
        db.Integer,
        db.ForeignKey("service_requests.id"),
        nullable=False
    )

    workflow_type = db.Column(
        db.String(100),
        nullable=False
    )

    status = db.Column(
        db.String(30),
        default="PLANNED"
    )

    current_step = db.Column(
        db.Integer,
        default=1
    )

    total_steps = db.Column(
        db.Integer,
        default=1
    )

    plan = db.Column(
        db.JSON,
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    completed_at = db.Column(
        db.DateTime,
        nullable=True
    )

    request = db.relationship(
        "ServiceRequest",
        backref="workflow"
    )

    def __repr__(self):
        return f"<Workflow {self.id}>"
