"""
End to end smoke test for the Secure Agentic-AI platform.

Run it against a scratch database so it never touches real data:

    venv/bin/python smoke_test.py

It checks the behaviour the platform is judged on:

- questions are answered from verified sources, or refused
- questions never create institutional actions
- requests collect their required fields before being filed
- nothing executes without human approval
- execution creates real institutional records
- policy rules from the knowledge base are actually enforced
- messages in other languages are declined, not guessed at

Requires the local Ollama model to be running.
"""

import os
import sys
import runpy
import tempfile


FAILURES = []
CHECKS = [0]


def check(name, condition, detail=""):
    CHECKS[0] += 1

    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))
        FAILURES.append(name)


def section(title):
    print()
    print("=" * 62)
    print(title)
    print("=" * 62)


def main():

    # A scratch database keeps the developer's own data untouched.
    # It must be set before app.py runs, since that is where the
    # database is bound to the application.
    scratch = tempfile.mkdtemp(prefix="secureai-smoke-")

    os.environ["DATABASE_URI"] = (
        "sqlite:///" + os.path.join(scratch, "smoke.db")
    )

    # Thinking mode roughly doubles every call; the tests do not read
    # the reasoning, so keep the suite fast.
    os.environ["OLLAMA_THINK"] = "0"

    # The admin password is generated on first run and never printed
    # again, so the suite supplies its own.
    os.environ["ADMIN_PASSWORD"] = "SmokeTest!2026"

    module = runpy.run_path("app.py", run_name="not_main")

    app = module["app"]
    db = module["db"]

    app.config["TESTING"] = True

    from app.models.request import ServiceRequest
    from app.models.audit_log import AuditLog
    from app.models.workflow import Workflow
    from app.models.maintenance import MaintenanceTicket
    from app.models.laboratory import LaboratoryBooking
    from app.models.certificate import CertificateRequest
    from app.models.grievance import Grievance

    with app.app_context():
        db.create_all()

    module["create_default_admin"]()

    client = app.test_client()

    def count(model):
        with app.app_context():
            return model.query.count()

    def chat(message):
        return client.post(
            "/chat",
            json={"message": message}
        ).json["reply"]

    # ----------------------------------------------------------
    section("AUTHENTICATION")

    check(
        "anonymous chat is refused",
        client.post("/chat", json={"message": "hi"}).status_code == 401
    )

    login = client.post("/login", data={
        "username": "admin",
        "password": "SmokeTest!2026"
    })

    check("admin can log in", login.status_code == 302)

    check(
        "wrong password is rejected",
        client.post("/login", data={
            "username": "admin",
            "password": "not-the-password"
        }).status_code == 302
    )

    # Registration keys on username and registration number.
    registered = client.post("/register", data={
        "username": "smoketest.student",
        "registration_number": "25X000A01",
        "password": "StudentPass!1",
        "confirm_password": "StudentPass!1"
    })

    check("a student can register", registered.status_code == 302)

    from app.models.user import User

    with app.app_context():
        created = User.query.filter_by(
            username="smoketest.student"
        ).first()

        check("registered account is stored", created is not None)
        check(
            "registration number is normalised",
            created is not None
            and created.registration_number == "25X000A01"
        )

    check(
        "duplicate username is refused",
        client.post("/register", data={
            "username": "SmokeTest.Student",
            "registration_number": "25X000A02",
            "password": "StudentPass!1",
            "confirm_password": "StudentPass!1"
        }).status_code == 302
    )

    with app.app_context():
        check(
            "duplicate did not create a second account",
            User.query.filter(
                User.username.ilike("smoketest.student")
            ).count() == 1
        )

    # Sign back in as the administrator for the rest of the suite.
    client.post("/login", data={
        "username": "admin",
        "password": "SmokeTest!2026"
    })

    # ----------------------------------------------------------
    section("GROUNDED ANSWERING")

    before = count(ServiceRequest)

    reply = chat("Is there a fee for a transfer certificate?")

    check("fee question is grounded", reply["grounded"] is True)
    check("fee question cites a source", bool(reply["sources"]))
    check(
        "question creates no request",
        count(ServiceRequest) == before,
        f"{count(ServiceRequest) - before} created"
    )

    reply = chat("Who won the football world cup in 2022?")

    check("off-topic question is refused", reply["grounded"] is False)

    reply = chat("What is the wifi password for the staff network?")

    check("unknown policy question is refused", reply["grounded"] is False)

    # ----------------------------------------------------------
    section("REQUEST INTAKE")

    before = count(ServiceRequest)

    reply = chat("The lights in room 12 of A block keep flickering")

    check(
        "maintenance request is filed",
        count(ServiceRequest) == before + 1
    )
    check("filed request returns an id", bool(reply.get("request_id")))

    request_id = reply.get("request_id")

    with app.app_context():
        record = db.session.get(ServiceRequest, request_id)
        workflow = Workflow.query.filter_by(request_id=request_id).first()

        check("structured fields are stored", bool(record.fields_json))
        check("a plan was created", workflow is not None)
        check(
            "plan has multiple steps",
            workflow is not None and workflow.total_steps >= 4
        )

    # ----------------------------------------------------------
    section("TERSE INPUT MUST ASK, NOT INVENT")

    # A message with no location once filed a ticket against "room 204",
    # a value copied straight out of an example in the prompt. Terse
    # input has to produce a question, never a fabricated request.
    for message, label, expected in [
        ("AC is broken", "maintenance", ["location", "room"]),
        ("lab is dirty", "maintenance-2", ["location", "room"]),
        ("need certificate", "certificate", ["certificate_type", "purpose"]),
        ("book a lab", "laboratory", ["laboratory_name", "booking_date"]),
    ]:
        before = count(ServiceRequest)

        reply = chat(message)

        check(
            f"'{message}' asks instead of filing",
            reply.get("status") == "needs_clarification",
            f"status={reply.get('status')}"
        )
        check(
            f"'{message}' files nothing",
            count(ServiceRequest) == before,
            f"{count(ServiceRequest) - before} created"
        )
        check(
            f"'{message}' asks for the right fields",
            all(f in reply.get("missing", []) for f in expected),
            f"missing={reply.get('missing')}"
        )

        invented = {
            field: value
            for field, value in (reply.get("fields") or {}).items()
            if field in ("location", "room")
            and value.lower() not in message.lower()
        }

        check(
            f"'{message}' invents no location or room",
            not invented,
            str(invented)
        )

    reply = chat("AC is broken")

    check(
        "clarification uses the requested wording",
        "Could you provide the following details"
        in reply.get("clarification_question", "")
    )

    # ----------------------------------------------------------
    section("APPROVAL GATE")

    tickets_before = count(MaintenanceTicket)

    client.post(f"/execution/{request_id}/execute")

    with app.app_context():
        status = db.session.get(ServiceRequest, request_id).status

    check("unapproved request is not executed", status != "Executed", status)
    check(
        "no record created without approval",
        count(MaintenanceTicket) == tickets_before
    )

    client.post(f"/approval/{request_id}/approve")
    client.post(f"/execution/{request_id}/execute")

    with app.app_context():
        record = db.session.get(ServiceRequest, request_id)
        ticket = MaintenanceTicket.query.order_by(
            MaintenanceTicket.id.desc()
        ).first()

        check("approved request executes", record.status == "Executed")
        check(
            "a real ticket is created",
            count(MaintenanceTicket) == tickets_before + 1
        )
        check(
            "ticket has a reference number",
            ticket is not None and ticket.ticket_number.startswith("MNT-")
        )
        check(
            "execution is audited",
            AuditLog.query.filter_by(
                request_id=request_id
            ).count() >= 3
        )

    # ----------------------------------------------------------
    section("POLICY ENFORCEMENT")

    client.post("/laboratory/book", data={
        "name": "Tester", "student_id": "S1",
        "laboratory": "Robotics Lab", "date": "2027-01-20",
        "time": "10:00", "purpose": "project"
    })

    with app.app_context():
        latest = ServiceRequest.query.order_by(
            ServiceRequest.id.desc()
        ).first()
        workflow = Workflow.query.filter_by(request_id=latest.id).first()
        notes = workflow.plan["policy_notes"] if workflow else []

        check(
            "restricted lab raises a policy conflict",
            any(note["source"] == "lab-003" for note in notes)
        )

        first_lab_id = latest.id

    client.post(f"/approval/{first_lab_id}/approve")
    client.post(f"/execution/{first_lab_id}/execute")

    bookings = count(LaboratoryBooking)

    # The same lab and slot again: the knowledge base forbids double
    # booking, so this must be refused even after approval.
    client.post("/laboratory/book", data={
        "name": "Tester", "student_id": "S2",
        "laboratory": "Robotics Lab", "date": "2027-01-20",
        "time": "11:00", "purpose": "clashing"
    })

    with app.app_context():
        clash = ServiceRequest.query.order_by(
            ServiceRequest.id.desc()
        ).first()
        clash_id = clash.id

    client.post(f"/approval/{clash_id}/approve")
    client.post(f"/execution/{clash_id}/execute")

    with app.app_context():
        check(
            "double booking is refused",
            count(LaboratoryBooking) == bookings,
            f"{count(LaboratoryBooking) - bookings} extra bookings"
        )
        check(
            "refused request is not marked executed",
            db.session.get(ServiceRequest, clash_id).status != "Executed"
        )

    client.post("/grievance/submit", data={
        "name": "Tester", "category": "Harassment", "priority": "High",
        "subject": "Ragging", "description":
            "seniors threatened me in the hostel last night"
    })

    with app.app_context():
        grievance_request = ServiceRequest.query.order_by(
            ServiceRequest.id.desc()
        ).first()
        grievance_id = grievance_request.id

    client.post(f"/approval/{grievance_id}/approve")
    client.post(f"/execution/{grievance_id}/execute")

    with app.app_context():
        grievance = Grievance.query.order_by(Grievance.id.desc()).first()

        check(
            "harassment grievance is high priority",
            grievance is not None and grievance.priority == "HIGH"
        )
        check(
            "harassment grievance is escalated",
            grievance is not None and grievance.escalation_level > 0
        )
        check(
            "harassment grievance routes to the Dean",
            grievance is not None
            and "Dean" in (grievance.assigned_department or "")
        )

    # ----------------------------------------------------------
    section("ENGLISH ONLY")

    before = count(ServiceRequest)

    for message, label in [
        ("मुझे बोनाफाइड सर्टिफिकेट चाहिए", "devanagari"),
        ("எனக்கு சான்றிதழ் வேண்டும்", "tamil"),
        ("Necesito un certificado de traslado", "spanish"),
    ]:
        reply = chat(message)

        check(
            f"{label} request is declined",
            reply.get("is_english") is False,
            f"is_english={reply.get('is_english')}"
        )
        check(
            f"{label} reply explains English only",
            "English" in reply.get("message", "")
        )

    check(
        "no request is filed from non-english input",
        count(ServiceRequest) == before,
        f"{count(ServiceRequest) - before} created"
    )

    reply = chat("The fan in room 8 of C block has stopped working")

    check(
        "english request still works",
        reply.get("is_english") is not False
        and reply.get("category") == "maintenance",
        reply.get("category")
    )

    # ----------------------------------------------------------
    section("UNCERTAINTY GATE")

    before = count(ServiceRequest)

    vague = chat("something happened yesterday and I am not happy")

    check(
        "a vague message is judged uncertain",
        vague.get("uncertain") is True,
        f"score={vague.get('confidence_score')}"
    )
    check(
        "an uncertain message files nothing",
        count(ServiceRequest) == before,
        f"{count(ServiceRequest) - before} created"
    )
    check(
        "the user is asked to restate",
        "haven't filed anything yet"
        in vague.get("clarification_question", "")
    )

    clear = chat("The fan in G block room 4 has stopped working")

    check(
        "a clear message is not judged uncertain",
        clear.get("uncertain") is False,
        f"score={clear.get('confidence_score')}"
    )
    check("a clear message is filed", bool(clear.get("request_id")))

    with app.app_context():
        stored = db.session.get(ServiceRequest, clear["request_id"])
        check(
            "the real confidence is stored, not a constant",
            stored.confidence is not None and stored.confidence < 1.0,
            f"confidence={stored.confidence}"
        )

    # ----------------------------------------------------------
    section("APPROVAL ROUTING")

    from app.models.approval import Approval

    routed = [
        ("/grievance/submit", {
            "category": "Harassment", "priority": "High",
            "subject": "Ragging",
            "description": "seniors threatened me in the hostel"
        }, "Dean of Student Affairs"),
        ("/certificate/request", {
            "certificate_type": "Transfer Certificate",
            "purpose": "moving college"
        }, "Registrar"),
        ("/maintenance/request", {
            "location": "K block", "room": "3", "category": "Plumbing",
            "priority": "Medium", "description": "tap is leaking"
        }, "Plumbing"),
    ]

    for path, payload, expected in routed:

        client.post(path, data=payload)

        with app.app_context():
            latest = ServiceRequest.query.order_by(
                ServiceRequest.id.desc()
            ).first()

            approval = Approval.query.filter_by(
                request_id=latest.id
            ).first()

            check(
                f"{expected} receives its request",
                approval is not None and approval.routed_to == expected,
                approval.routed_to if approval else "no approval row"
            )

    with app.app_context():
        pending = Approval.query.filter_by(
            request_id=latest.id
        ).first()
        pending_id = latest.id

    client.post(f"/approval/{pending_id}/approve")

    with app.app_context():
        closed = Approval.query.filter_by(request_id=pending_id).first()

        check(
            "approving closes the routed approval",
            closed.status == "APPROVED",
            closed.status
        )
        check(
            "the decision records who made it",
            closed.decided_by is not None and closed.decided_at is not None
        )

    # ----------------------------------------------------------
    section("AUTHORIZATION")

    # A student holds none of the reviewer permissions. The POST
    # endpoints matter more than the pages: hiding a link is not a
    # control, and a request id is easy to guess.
    student = app.test_client()

    student.post("/register", data={
        "username": "perm.student",
        "registration_number": "25P999P99",
        "password": "StudentPass!1",
        "confirm_password": "StudentPass!1"
    })
    student.post("/login", data={
        "username": "perm.student",
        "password": "StudentPass!1"
    })

    check(
        "student reaches their own requests",
        student.get("/requests").status_code == 200
    )

    for path in ["/approval", "/execution", "/audit"]:
        check(
            f"student is refused {path}",
            student.get(path).status_code == 302,
            student.get(path).status_code
        )

    check(
        "student is refused the audit api",
        student.get("/api/agent/audit").status_code == 403
    )

    # Something still pending, to try to act on.
    reply = chat("The tap in F block room 2 is leaking")
    victim_id = reply.get("request_id")

    if victim_id:
        before_status = None

        with app.app_context():
            before_status = db.session.get(
                ServiceRequest, victim_id
            ).status

        student.post(f"/approval/{victim_id}/approve")

        with app.app_context():
            check(
                "student cannot approve a request",
                db.session.get(
                    ServiceRequest, victim_id
                ).status == before_status,
                "status changed"
            )

        tickets = count(MaintenanceTicket)

        student.post(f"/execution/{victim_id}/execute")

        check(
            "student cannot execute a request",
            count(MaintenanceTicket) == tickets,
            "a record was created"
        )

    # ----------------------------------------------------------
    section("PAGES")

    for path in ["/", "/audit", "/approval", "/execution", "/requests",
                 "/certificate", "/laboratory", "/grievance",
                 "/maintenance", "/api/health", "/api/agent/audit"]:

        check(f"{path} renders", client.get(path).status_code == 200)

    # ----------------------------------------------------------
    print()
    print("=" * 62)

    passed = CHECKS[0] - len(FAILURES)

    print(f"{passed}/{CHECKS[0]} checks passed")

    if FAILURES:
        print()
        print("Failed:")
        for name in FAILURES:
            print(" -", name)

    print(f"\nScratch database: {scratch}")

    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
