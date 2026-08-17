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
