"""
Minimal schema migration for the SQLite database.

db.create_all() creates missing tables but never alters existing ones,
so a column added to a model after the database was first created is
silently absent at runtime. This adds those columns in place.

It only ever ADDs columns. Nothing is dropped, renamed or rewritten,
so running it against an existing database cannot lose data.
"""

from sqlalchemy import inspect, text


def _column_type_sql(column):
    """
    Render a column's type as SQLite DDL.
    """

    try:
        return column.type.compile(dialect=None)

    except Exception:
        # JSON and a few other types need the bound dialect to compile.
        return "TEXT"


def sync_columns(db):
    """
    Add any model column that is missing from its existing table.

    Returns a list of "table.column" strings describing what was added.
    """

    inspector = inspect(db.engine)

    existing_tables = set(inspector.get_table_names())

    added = []

    for table in db.metadata.sorted_tables:

        if table.name not in existing_tables:
            # create_all() handles brand new tables.
            continue

        present = {
            column["name"]
            for column in inspector.get_columns(table.name)
        }

        for column in table.columns:

            if column.name in present:
                continue

            # A new column must be nullable or carry a default; SQLite
            # cannot add a NOT NULL column to a table holding rows.
            column_type = _column_type_sql(column)

            statement = (
                f'ALTER TABLE "{table.name}" '
                f'ADD COLUMN "{column.name}" {column_type}'
            )

            with db.engine.begin() as connection:
                connection.execute(text(statement))

            added.append(f"{table.name}.{column.name}")

    return added


# =========================================================
# USERS TABLE REBUILD
# =========================================================

def _slug(text):
    """
    Turn a name or email into a usable username.
    """

    import re

    base = (text or "").split("@")[0]

    base = re.sub(r"[^A-Za-z0-9._-]", "", base).strip("._-").lower()

    return base or "user"


def migrate_users(db):
    """
    Move the users table onto username / registration_number.

    Accounts were originally keyed by email with an optional
    student_id. Registration now asks for a username and a
    registration number instead, and email is optional, which SQLite
    cannot express with ALTER TABLE alone: dropping a NOT NULL
    constraint requires rebuilding the table.

    Existing accounts keep their id, password and role. A username is
    derived from the email, and the registration number from the old
    student_id. Nothing is deleted.

    Returns a short description of what happened, or None if the table
    was already migrated.
    """

    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)

    if "users" not in inspector.get_table_names():
        return None

    columns = {c["name"] for c in inspector.get_columns("users")}

    # sync_columns() may already have ADDed the new columns as empty
    # nullable ones. That is not a completed migration: the values are
    # still NULL, student_id is still there, and email is still NOT
    # NULL. Rebuild until the table really matches the model.
    from sqlalchemy import text as _text

    needs_rebuild = (
        "username" not in columns
        or "registration_number" not in columns
        or "student_id" in columns
    )

    if not needs_rebuild:

        with db.engine.connect() as probe:
            unpopulated = probe.execute(_text(
                "SELECT COUNT(*) FROM users "
                "WHERE username IS NULL OR registration_number IS NULL"
            )).scalar()

        needs_rebuild = bool(unpopulated)

    if not needs_rebuild:
        return None

    with db.engine.begin() as connection:

        rows = connection.execute(
            text("SELECT * FROM users")
        ).mappings().all()

        taken_usernames = set()
        taken_numbers = set()

        migrated = []

        for row in rows:

            username = _slug(
                row.get("username")
                or row.get("email")
                or row.get("name")
                or f"user{row['id']}"
            )

            # Usernames are unique; two accounts derived from the same
            # name get a numeric suffix rather than one being dropped.
            candidate = username
            suffix = 2

            while candidate in taken_usernames:
                candidate = f"{username}{suffix}"
                suffix += 1

            taken_usernames.add(candidate)

            number = (
                row.get("registration_number")
                or row.get("student_id")
                or ""
            ).strip()

            if not number or number in taken_numbers:
                number = f"LEGACY-{row['id']:04d}"

            taken_numbers.add(number)

            migrated.append({
                "id": row["id"],
                "username": candidate,
                "registration_number": number,
                "name": row.get("name") or candidate,
                "email": row.get("email"),
                "password_hash": row["password_hash"],
                "role": row.get("role") or "STUDENT",
                "department": row.get("department"),
                "is_active": (
                    1 if row.get("is_active") in (1, True, None) else 0
                ),
                "created_at": row.get("created_at")
            })

        connection.execute(text("ALTER TABLE users RENAME TO users_old"))

        connection.execute(text("""
            CREATE TABLE users (
                id INTEGER NOT NULL PRIMARY KEY,
                username VARCHAR(80) NOT NULL UNIQUE,
                registration_number VARCHAR(50) NOT NULL UNIQUE,
                name VARCHAR(120) NOT NULL,
                email VARCHAR(150) UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                role VARCHAR(30) NOT NULL,
                department VARCHAR(120),
                is_active BOOLEAN,
                created_at DATETIME
            )
        """))

        for record in migrated:
            connection.execute(text("""
                INSERT INTO users (
                    id, username, registration_number, name, email,
                    password_hash, role, department, is_active, created_at
                ) VALUES (
                    :id, :username, :registration_number, :name, :email,
                    :password_hash, :role, :department, :is_active,
                    :created_at
                )
            """), record)

        connection.execute(text("DROP TABLE users_old"))

    return (
        f"users table rebuilt for username/registration_number "
        f"({len(migrated)} accounts kept)"
    )


def migrate_approvals(db):
    """
    Rebuild the approvals table for routed approvals.

    The original table keyed on workflow_id and required a named
    approver, which cannot express "this belongs to the Accounts
    Department". The table has never held a row, so it is rebuilt
    rather than migrated.
    """

    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)

    if "approvals" not in inspector.get_table_names():
        return None

    columns = {c["name"] for c in inspector.get_columns("approvals")}

    if "routed_to" in columns:
        return None

    with db.engine.begin() as connection:

        existing = connection.execute(
            text("SELECT COUNT(*) FROM approvals")
        ).scalar()

        # Refuse to drop real data. If a row ever exists here, this
        # needs to become a copying migration instead.
        if existing:
            print(
                f"SKIPPED approvals rebuild: {existing} row(s) present. "
                f"Migrate them by hand."
            )
            return None

        connection.execute(text("DROP TABLE approvals"))

    return "approvals table rebuilt for routed approvals"
