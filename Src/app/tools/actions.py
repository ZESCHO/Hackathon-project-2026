"""
Controlled tools.

Each function here performs one real institutional action. They are the
only place the agent may change institutional state, and none of them
may be called until a human has approved the request they belong to.

Every tool takes the ServiceRequest it is acting on so that the record
it creates can be traced back to the approved request and its audit
trail.
"""

from datetime import datetime, timedelta

from app.models import db
from app.models.certificate import CertificateRequest
from app.models.maintenance import MaintenanceTicket
from app.models.laboratory import LaboratoryBooking
from app.models.grievance import Grievance
from app.workflows.planner import parse_date, parse_time


class ToolError(Exception):
    """
    Raised when a tool cannot complete its action.
    """


# Maximum session length permitted by knowledge_base/laboratories.json.
MAX_BOOKING_HOURS = 3


def _require_approved(service_request):
    """
    Refuse to act on anything a human has not approved.

    This is the last line of defence. The route checks approval too,
    but a tool must never depend on its caller having done so.
    """

    status = (service_request.status or "").strip().lower()

    if status != "approved":
        raise ToolError(
            "Refused: this action requires an approved request "
            f"(current status: {service_request.status})."
        )


# =========================================================
# CERTIFICATE
# =========================================================

def issue_certificate(service_request, fields, derived):

    _require_approved(service_request)

    certificate_type = (
        str(fields.get("certificate_type", "")).strip()
        or "Certificate"
    )

    record = CertificateRequest(
        user_id=service_request.user_id,
        request_id=service_request.id,
        certificate_type=certificate_type,
        purpose=str(fields.get("purpose", "")).strip() or "Not stated",
        status="ISSUED",
        submitted_at=service_request.created_at,
        completed_at=datetime.utcnow()
    )

    db.session.add(record)
    db.session.flush()

    reference = f"CERT-{datetime.now():%Y}-{record.id:04d}"

    return {
        "record_id": record.id,
        "reference": reference,
        "summary": f"{certificate_type} issued as {reference}.",
        "detail": {
            "Reference": reference,
            "Certificate": certificate_type,
            "Purpose": record.purpose
        }
    }


# =========================================================
# MAINTENANCE
# =========================================================

def create_ticket(service_request, fields, derived):

    _require_approved(service_request)

    location = str(fields.get("location", "")).strip() or "Not stated"
    room = str(fields.get("room", "")).strip()

    full_location = f"{location}, Room {room}" if room else location

    issue = (
        str(fields.get("description", "")).strip()
        or service_request.request_text
    )

    record = MaintenanceTicket(
        ticket_number="PENDING",
        user_id=service_request.user_id,
        location=full_location,
        issue=issue,
        priority=derived.get("priority", "NORMAL"),
        status="OPEN",
        assigned_department=derived.get(
            "department",
            "General Maintenance"
        )
    )

    db.session.add(record)
    db.session.flush()

    record.ticket_number = f"MNT-{datetime.now():%Y}-{record.id:04d}"

    return {
        "record_id": record.id,
        "reference": record.ticket_number,
        "summary": (
            f"Ticket {record.ticket_number} opened with "
            f"{record.assigned_department} at {record.priority} priority."
        ),
        "detail": {
            "Ticket": record.ticket_number,
            "Location": full_location,
            "Priority": record.priority,
            "Department": record.assigned_department,
            "Target": derived.get("sla", "Not stated")
        }
    }


# =========================================================
# LABORATORY
# =========================================================

def find_booking_conflict(laboratory, booking_date, start, end,
                          exclude_request_id=None):
    """
    Return an existing booking that overlaps the requested slot.

    knowledge_base/laboratories.json states labs cannot be double
    booked, so this must run before any booking is confirmed.
    """

    if not (laboratory and booking_date and start and end):
        return None

    candidates = LaboratoryBooking.query.filter(
        LaboratoryBooking.laboratory.ilike(laboratory),
        LaboratoryBooking.booking_date == booking_date,
        LaboratoryBooking.status.in_(["PENDING", "CONFIRMED"])
    ).all()

    for booking in candidates:

        # Two slots overlap unless one ends before the other begins.
        if booking.start_time < end and start < booking.end_time:
            return booking

    return None


def create_booking(service_request, fields, derived):

    _require_approved(service_request)

    laboratory = (
        str(fields.get("laboratory_name", "")).strip()
        or "Unspecified Laboratory"
    )

    booking_date = derived.get("booking_date") or parse_date(
        fields.get("booking_date")
    )

    start = derived.get("booking_time") or parse_time(
        fields.get("booking_time")
    )

    if not booking_date or not start:
        raise ToolError(
            "Refused: the booking date or time could not be read, so "
            "the slot cannot be reserved."
        )

    end_dt = (
        datetime.combine(booking_date, start)
        + timedelta(hours=MAX_BOOKING_HOURS)
    )

    end = end_dt.time()

    conflict = find_booking_conflict(
        laboratory,
        booking_date,
        start,
        end
    )

    if conflict is not None:
        raise ToolError(
            f"Refused: {laboratory} is already booked on "
            f"{booking_date:%d %b %Y} from "
            f"{conflict.start_time:%H:%M} to {conflict.end_time:%H:%M}."
        )

    record = LaboratoryBooking(
        user_id=service_request.user_id,
        laboratory=laboratory,
        booking_date=booking_date,
        start_time=start,
        end_time=end,
        purpose=str(fields.get("purpose", "")).strip() or "Not stated",
        status="CONFIRMED"
    )

    db.session.add(record)
    db.session.flush()

    reference = f"LAB-{datetime.now():%Y}-{record.id:04d}"

    return {
        "record_id": record.id,
        "reference": reference,
        "summary": (
            f"{laboratory} reserved on {booking_date:%d %b %Y} "
            f"from {start:%H:%M} to {end:%H:%M} ({reference})."
        ),
        "detail": {
            "Reference": reference,
            "Laboratory": laboratory,
            "Date": f"{booking_date:%d %b %Y}",
            "Slot": f"{start:%H:%M} - {end:%H:%M}",
            "Purpose": record.purpose
        }
    }


# =========================================================
# GRIEVANCE
# =========================================================

def record_grievance(service_request, fields, derived):

    _require_approved(service_request)

    subject = str(fields.get("subject", "")).strip() or "Grievance"

    description = (
        str(fields.get("description", "")).strip()
        or service_request.request_text
    )

    record = Grievance(
        user_id=service_request.user_id,
        subject=subject,
        description=description,
        category=derived.get("department", "Student Grievance Cell"),
        priority=derived.get("priority", "NORMAL"),
        status="OPEN",
        assigned_department=derived.get(
            "department",
            "Student Grievance Cell"
        ),
        escalation_level=derived.get("escalation_level", 0)
    )

    db.session.add(record)
    db.session.flush()

    reference = f"GRV-{datetime.now():%Y}-{record.id:04d}"

    escalated = record.escalation_level > 0

    return {
        "record_id": record.id,
        "reference": reference,
        "summary": (
            f"Grievance {reference} recorded and routed to "
            f"{record.assigned_department}"
            + (" and escalated to the Dean's office."
               if escalated else ".")
        ),
        "detail": {
            "Reference": reference,
            "Subject": subject,
            "Priority": record.priority,
            "Routed to": record.assigned_department,
            "Escalated": "Yes" if escalated else "No"
        }
    }


# =========================================================
# NOTIFICATION
# =========================================================

def notify_requester(service_request, fields, derived):
    """
    Notify the requester of the outcome.

    There is no mail server wired up, so this records the notification
    in the audit trail rather than pretending a message was delivered.
    """

    recipient = (
        service_request.user.email
        if service_request.user
        else f"user #{service_request.user_id}"
    )

    return {
        "record_id": None,
        "reference": None,
        "summary": (
            f"Outcome recorded for {recipient}. No mail service is "
            f"configured, so no message was sent."
        ),
        "detail": {"Recipient": recipient}
    }


TOOLS = {
    "issue_certificate": issue_certificate,
    "create_ticket": create_ticket,
    "create_booking": create_booking,
    "record_grievance": record_grievance,
    "notify_requester": notify_requester
}
