"""
Create the departmental reviewer accounts.

Each reviewer is scoped to one office and sees only the requests
routed there. The master administrator carries no department and
oversees every queue.

    venv/bin/python seed_reviewers.py

Passwords are generated and printed once. Pass --password to set them
all to a known value for a demo:

    venv/bin/python seed_reviewers.py --password Demo!2026

Running it again leaves existing accounts alone unless --reset-passwords
is given.
"""

import os
import sys
import runpy
import secrets


# Reviewers to create, as (username, department). Departments must
# match the strings the router produces in app/workflows/planner.py,
# or the reviewer will see an empty queue.
REVIEWERS = [
    ("dean", "Dean of Student Affairs"),
    ("registrar", "Registrar"),
    ("academics", "Academic Office"),
    ("accounts", "Accounts Department"),
    ("hostel", "Hostel Administration"),
    ("labs", "Laboratory Administration"),
    ("research.labs", "Faculty Co-signature (Research Labs)"),
    ("electrical", "Electrical"),
    ("plumbing", "Plumbing"),
    ("maintenance", "General Maintenance"),
]


def main():

    fixed_password = None
    reset = "--reset-passwords" in sys.argv

    if "--password" in sys.argv:
        index = sys.argv.index("--password")
        if index + 1 >= len(sys.argv):
            print("--password needs a value")
            return 1
        fixed_password = sys.argv[index + 1]

    module = runpy.run_path("app.py", run_name="not_main")

    app = module["app"]
    db = module["db"]

    from app.models.user import User
    from app.workflows.planner import DEPARTMENTS

    created = []
    updated = []

    with app.app_context():

        for index, (username, department) in enumerate(REVIEWERS, start=1):

            if department not in DEPARTMENTS:
                print(
                    f"  SKIPPED {username}: '{department}' is not a "
                    f"known department"
                )
                continue

            user = User.query.filter_by(username=username).first()

            password = fixed_password or secrets.token_urlsafe(9)

            if user is None:

                user = User(
                    username=username,
                    registration_number=f"REV-{index:04d}",
                    name=username.replace(".", " ").title(),
                    role="REVIEWER",
                    department=department,
                    is_active=True
                )

                user.set_password(password)

                db.session.add(user)

                created.append((username, department, password))

            else:

                user.role = "REVIEWER"
                user.department = department
                user.is_active = True

                if fixed_password or reset:
                    user.set_password(password)
                    updated.append((username, department, password))
                else:
                    updated.append((username, department, "unchanged"))

        db.session.commit()

    width = 74

    print()
    print("=" * width)
    print("DEPARTMENTAL REVIEWERS")
    print("=" * width)

    for username, department, password in created:
        print(f"  {username:<16} {department:<38} {password}")

    for username, department, password in updated:
        print(f"  {username:<16} {department:<38} {password}")

    print("=" * width)
    print(f"  {len(created)} created, {len(updated)} already existed")
    print()
    print("  Each signs in at the normal login page and lands on their")
    print("  own queue. They can only act on requests routed to them.")
    print("=" * width)
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
