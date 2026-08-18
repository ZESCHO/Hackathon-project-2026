"""
Multi-step planning for institutional service requests.

A plan is produced when a request is filed, before anything is done.
It states every step the platform intends to take, which steps need a
human, and which institutional policies were consulted.

The plan is stored on the Workflow row so a reviewer can see the whole
intended sequence before approving any of it, and so the audit trail
records what was planned rather than only what happened.
"""

from datetime import datetime, timedelta

from app.rag.retriever import search


# =========================================================
# POLICY CONSTANTS
#
# These mirror rules stated in knowledge_base/*.json. Each one records
# the snippet id it came from so a decision can be traced back to the
# verified source that justified it.
# =========================================================

LAB_MIN_ADVANCE_HOURS = 24
LAB_SOURCE_ADVANCE = "lab-001"

RESTRICTED_LAB_KEYWORDS = ["advanced chemistry", "robotics", "research"]
LAB_SOURCE_RESTRICTED = "lab-003"

LAB_SOURCE_CONFLICT = "lab-002"

HIGH_PRIORITY_GRIEVANCE_KEYWORDS = [
    "harass", "assault", "threat", "abuse", "safety",
    "unsafe", "violence", "discriminat", "rag"
]
GRIEVANCE_SOURCE_PRIORITY = "griev-002"

HIGH_PRIORITY_MAINTENANCE_KEYWORDS = [
    "fire", "shock", "electrocut", "flood", "leak", "gas",
    "no power", "power cut", "short circuit", "spark", "hazard"
]
MEDIUM_PRIORITY_MAINTENANCE_KEYWORDS = [
    "ac", "air condition", "hvac", "furniture", "chair", "desk",
    "fan", "light", "internet", "network", "wifi", "plumbing", "water"
]
MAINTENANCE_SOURCE_SLA = "maint-002"

CLEARANCE_CERTIFICATES = ["transfer"]
CERTIFICATE_SOURCE_CLEARANCE = "cert-002"


DEPARTMENT_BY_KEYWORD = [
    (["electric", "light", "power", "socket", "fan", "spark"], "Electrical"),
    (["plumb", "water", "leak", "tap", "drain", "toilet"], "Plumbing"),
    (["ac", "air condition", "hvac", "heating", "cooling"], "HVAC"),
    (["furniture", "chair", "desk", "table", "bench", "door"], "Furniture"),
    (["internet", "network", "wifi", "lan", "router"], "Internet/Network")
]


GRIEVANCE_DEPARTMENT_BY_KEYWORD = [
    (["harass", "assault", "threat", "abuse", "safety", "discriminat"],
     "Dean of Student Affairs"),
    (["hostel", "warden", "mess", "room"], "Hostel Administration"),
    (["fee", "scholarship", "refund", "payment", "financial"],
     "Accounts Department"),
    (["exam", "marks", "grade", "attendance", "faculty", "class"],
     "Academic Office")
]


# Every office a request can be routed to. Reviewer accounts are
# assigned one of these, and a reviewer only ever sees the queue for
# their own. Kept here beside the rules that produce them so the two
# cannot drift apart.
DEPARTMENTS = [
    "Dean of Student Affairs",
    "Registrar",
    "Academic Office",
    "Accounts Department",
    "Hostel Administration",
    "Student Grievance Cell",
    "Laboratory Administration",
    "Faculty Co-signature (Research Labs)",
    "Electrical",
    "Plumbing",
    "HVAC",
    "Furniture",
    "Internet/Network",
    "General Maintenance"
]


# =========================================================
# HELPERS
# =========================================================

DATE_FORMATS = ["%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]

TIME_FORMATS = ["%H:%M", "%H.%M", "%I:%M %p", "%I %p"]


def parse_date(value):
    """
    Parse a booking date written in any of the forms we accept.
    """

    value = (value or "").strip()

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    return None


def parse_time(value):
    """
    Parse a booking time written in any of the forms we accept.
    """

    value = (value or "").strip().upper().replace(".", ":")

    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue

    return None


def _matches(text, keywords):
    """
    Return the keywords present in the text.
    """

    lowered = (text or "").lower()

    return [word for word in keywords if word in lowered]


def _field_text(fields):
    """
    Flatten a field dict into one searchable string.
    """

    return " ".join(
        str(value)
        for value in (fields or {}).values()
        if value
    )


def _step(number, action, description, actor="AGENT", tool=None):
    """
    Build one plan step.
    """

    return {
        "step": number,
        "action": action,
        "description": description,
        "actor": actor,
        "tool": tool,
        "status": "PLANNED"
    }


def _cite(snippet_id):
    """
    Look up a knowledge base snippet by id so a policy note can quote
    the verified text it is based on.
    """

    for hit in search(snippet_id, top_k=8, min_score=0.0):
        if hit["id"] == snippet_id:
            return hit

    return None


def _note(snippet_id, message, blocking=False):
    """
    Build a policy note tied to the verified snippet that justifies it.
    """

    hit = _cite(snippet_id)

    return {
        "source": snippet_id,
        "title": hit["title"] if hit else "",
        "message": message,
        "blocking": blocking
    }


# =========================================================
# PER-CATEGORY POLICY EVALUATION
# =========================================================

def _certificate_policy(fields):

    notes = []

    certificate_type = str(fields.get("certificate_type", "")).lower()

    # knowledge_base/certificates.json names who issues what.
    if "character" in certificate_type:
        department = "Dean of Student Affairs"

    elif any(word in certificate_type for word in CLEARANCE_CERTIFICATES):
        department = "Registrar"

    else:
        department = "Academic Office"

    if any(word in certificate_type for word in CLEARANCE_CERTIFICATES):

        notes.append(_note(
            CERTIFICATE_SOURCE_CLEARANCE,
            "A Transfer Certificate is issued only after all dues are "
            "cleared and a signed no-dues form is on file. The reviewer "
            "must confirm clearance before approving.",
            blocking=False
        ))

    if "character" in certificate_type:

        notes.append(_note(
            "cert-003",
            "Character Certificates require no disciplinary record in "
            "the current academic year and are issued by the Dean of "
            "Student Affairs."
        ))

    return notes, {
        "department": department,
        "routing_reason": (
            f"{certificate_type.title() or 'This certificate'} is "
            f"issued by the {department}."
        ),
        "routing_source": (
            "cert-003" if "character" in certificate_type
            else CERTIFICATE_SOURCE_CLEARANCE
            if any(w in certificate_type for w in CLEARANCE_CERTIFICATES)
            else "cert-004"
        )
    }


def _maintenance_policy(fields):

    notes = []

    text = _field_text(fields)

    if _matches(text, HIGH_PRIORITY_MAINTENANCE_KEYWORDS):
        priority = "HIGH"
        target = "4 hours"

    elif _matches(text, MEDIUM_PRIORITY_MAINTENANCE_KEYWORDS):
        priority = "MEDIUM"
        target = "2 working days"

    else:
        priority = "LOW"
        target = "5 working days"

    notes.append(_note(
        MAINTENANCE_SOURCE_SLA,
        f"Classified {priority} priority; the stated resolution "
        f"target is {target}."
    ))

    department = "General Maintenance"

    for keywords, name in DEPARTMENT_BY_KEYWORD:
        if _matches(text, keywords):
            department = name
            break

    return notes, {
        "priority": priority,
        "sla": target,
        "department": department,
        "routing_reason": (
            f"Reported fault handled by {department}. "
            f"{priority.title()} priority, target {target}."
        ),
        "routing_source": MAINTENANCE_SOURCE_SLA
    }


def _laboratory_policy(fields, now=None):

    notes = []
    derived = {}

    now = now or datetime.now()

    laboratory = str(fields.get("laboratory_name", ""))

    booking_date = parse_date(fields.get("booking_date"))
    booking_time = parse_time(fields.get("booking_time"))

    derived["booking_date"] = booking_date
    derived["booking_time"] = booking_time

    # ---- restricted laboratories ----

    if _matches(laboratory, RESTRICTED_LAB_KEYWORDS):

        derived["restricted"] = True
        derived["department"] = "Faculty Co-signature (Research Labs)"
        derived["routing_reason"] = (
            f"{laboratory} is a research laboratory, so a faculty "
            f"co-signature is required in addition to the booking."
        )
        derived["routing_source"] = LAB_SOURCE_RESTRICTED

        notes.append(_note(
            LAB_SOURCE_RESTRICTED,
            f"{laboratory} is a research laboratory and requires "
            f"faculty co-signature approval in addition to the standard "
            f"booking.",
            blocking=True
        ))

    else:
        derived["restricted"] = False
        derived["department"] = "Laboratory Administration"
        derived["routing_reason"] = (
            "Standard teaching laboratory booking, handled by "
            "Laboratory Administration."
        )
        derived["routing_source"] = LAB_SOURCE_ADVANCE

    # ---- advance notice ----

    if booking_date and booking_time:

        starts_at = datetime.combine(booking_date, booking_time)

        derived["starts_at"] = starts_at

        if starts_at - now < timedelta(hours=LAB_MIN_ADVANCE_HOURS):

            notes.append(_note(
                LAB_SOURCE_ADVANCE,
                f"Bookings must be made at least "
                f"{LAB_MIN_ADVANCE_HOURS} hours in advance. This "
                f"request is inside that window.",
                blocking=True
            ))

    else:

        notes.append(_note(
            LAB_SOURCE_ADVANCE,
            "The booking date or time could not be read, so the "
            "24 hour advance notice rule could not be verified.",
            blocking=True
        ))

    return notes, derived


def _grievance_policy(fields):

    notes = []

    text = _field_text(fields)

    matched = _matches(text, HIGH_PRIORITY_GRIEVANCE_KEYWORDS)

    if matched:
        priority = "HIGH"
        escalation_level = 1

        notes.append(_note(
            GRIEVANCE_SOURCE_PRIORITY,
            "Harassment and safety related grievances are always high "
            "priority and are escalated to the Dean's office within "
            "24 hours, bypassing normal queue order."
        ))

    else:
        priority = "NORMAL"
        escalation_level = 0

    department = "Student Grievance Cell"

    for keywords, name in GRIEVANCE_DEPARTMENT_BY_KEYWORD:
        if _matches(text, keywords):
            department = name
            break

    return notes, {
        "priority": priority,
        "escalation_level": escalation_level,
        "department": department,
        "routing_reason": (
            f"{priority.title()} priority grievance for the "
            f"{department}."
            + (
                " Safety related, so escalated within 24 hours."
                if escalation_level else ""
            )
        ),
        "routing_source": (
            GRIEVANCE_SOURCE_PRIORITY if escalation_level else "griev-001"
        )
    }


POLICY_EVALUATORS = {
    "certificate": _certificate_policy,
    "maintenance": _maintenance_policy,
    "laboratory": _laboratory_policy,
    "grievance": _grievance_policy
}


# =========================================================
# PLAN CONSTRUCTION
# =========================================================

PLAN_TEMPLATES = {

    "certificate": [
        ("validate_request", "Check that every required detail is present"),
        ("check_policy", "Check certificate rules in the knowledge base"),
        ("human_approval", "Wait for a reviewer to approve issuing it"),
        ("issue_certificate", "Record the certificate as issued"),
        ("notify_requester", "Tell the requester the outcome")
    ],

    "maintenance": [
        ("validate_request", "Check that every required detail is present"),
        ("check_policy", "Classify priority and routing department"),
        ("human_approval", "Wait for a reviewer to approve the ticket"),
        ("create_ticket", "Open a maintenance ticket"),
        ("notify_requester", "Tell the requester the ticket number")
    ],

    "laboratory": [
        ("validate_request", "Check that every required detail is present"),
        ("check_policy", "Check eligibility, notice period and restrictions"),
        ("check_availability", "Check the slot is not already booked"),
        ("human_approval", "Wait for a reviewer to approve the booking"),
        ("create_booking", "Reserve the laboratory slot"),
        ("notify_requester", "Tell the requester the booking is confirmed")
    ],

    "grievance": [
        ("validate_request", "Check that every required detail is present"),
        ("check_policy", "Classify priority and routing department"),
        ("human_approval", "Wait for a reviewer to accept the grievance"),
        ("record_grievance", "Record and route the grievance"),
        ("notify_requester", "Confirm receipt to the submitter")
    ]
}


# Steps the agent may run on its own. Everything else is either a human
# decision or an action that may only run after one.
AUTONOMOUS_STEPS = {
    "validate_request",
    "check_policy",
    "check_availability"
}


def canonical_category(value):
    """
    Reduce a stored category label to one of the four service keys.

    Requests have been filed under several labels over time
    ("Certificate", "Certificate Request", "Laboratory Booking"), so
    matching on a substring is more reliable than exact equality.
    """

    lowered = (value or "").lower()

    for key in ("certificate", "maintenance", "laborator", "grievance"):

        if key in lowered:
            return "laboratory" if key == "laborator" else key

    return lowered.strip()


def build_plan(category, fields, now=None):
    """
    Produce the plan and policy assessment for a request.

    Returns a dict with:
        steps            - the ordered plan
        policy_notes     - findings, each citing a knowledge base id
        policy_conflict  - True if a note blocks straight-through action
        derived          - values the executor needs (priority, dates)
        requires_approval- always True for the four service categories
    """

    category = canonical_category(category)

    template = PLAN_TEMPLATES.get(category)

    if not template:
        return {
            "steps": [],
            "policy_notes": [],
            "policy_conflict": False,
            "derived": {},
            "requires_approval": True
        }

    evaluator = POLICY_EVALUATORS.get(category)

    if category == "laboratory":
        notes, derived = evaluator(fields, now=now)
    else:
        notes, derived = evaluator(fields)

    steps = []

    for index, (action, description) in enumerate(template, start=1):

        actor = "AGENT" if action in AUTONOMOUS_STEPS else (
            "HUMAN" if action == "human_approval" else "AGENT"
        )

        steps.append(_step(
            index,
            action,
            description,
            actor=actor,
            tool=None if action in AUTONOMOUS_STEPS else action
        ))

    return {
        "steps": steps,
        "policy_notes": notes,
        "policy_conflict": any(note["blocking"] for note in notes),
        "derived": derived,
        "requires_approval": True
    }


def plan_summary(plan):
    """
    Render a plan as a short human readable list.
    """

    return "\n".join(
        f"{step['step']}. {step['description']}"
        for step in plan.get("steps", [])
    )
