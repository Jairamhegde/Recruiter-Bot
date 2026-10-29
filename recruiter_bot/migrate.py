"""Applies pending SQL migrations in name order. Usage: python -m recruiter_bot.migrate [--mark-applied]"""
import sys
from pathlib import Path

import psycopg

from recruiter_bot.db import connect

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

CREATE_HISTORY_SQL = """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        filename    TEXT         NOT NULL,
        applied_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),

        CONSTRAINT schema_migrations_pk PRIMARY KEY (filename)
    )
"""

APPLIED_SQL = "SELECT filename FROM schema_migrations"

RECORD_SQL = "INSERT INTO schema_migrations (filename) VALUES (%s)"

# Held for the whole run, so two copies starting at once (say, two containers) can't apply a file twice.
LOCK_SQL = "SELECT pg_advisory_lock(hashtext('recruiter_bot.migrate'))"
UNLOCK_SQL = "SELECT pg_advisory_unlock(hashtext('recruiter_bot.migrate'))"


def migration_files() -> list[Path]:
    """001_init.sql, 002_..., ...: the numbered prefix fixes the order."""
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def pending_files(conn: psycopg.Connection) -> list[Path]:
    applied = {filename for (filename,) in conn.execute(APPLIED_SQL).fetchall()}
    return [path for path in migration_files() if path.name not in applied]


def apply_pending(conn: psycopg.Connection) -> list[str]:
    """Each file runs in its own transaction with its history row: it's applied completely, or not at all."""
    applied = []
    for path in pending_files(conn):
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute(RECORD_SQL, (path.name,))
        applied.append(path.name)
    return applied


def mark_all_applied(conn: psycopg.Connection) -> list[str]:
    marked = []
    for path in pending_files(conn):
        with conn.transaction():
            conn.execute(RECORD_SQL, (path.name,))
        marked.append(path.name)
    return marked


def main() -> None:
    mark_only = sys.argv[1:] == ["--mark-applied"]
    if sys.argv[1:] and not mark_only:
        print(__doc__)
        raise SystemExit(2)

    with connect() as conn:
        conn.autocommit = True  # each file manages its own transaction
        conn.execute(CREATE_HISTORY_SQL)
        conn.execute(LOCK_SQL)
        try:
            names = mark_all_applied(conn) if mark_only else apply_pending(conn)
        finally:
            conn.execute(UNLOCK_SQL)

    verb = "Marked as applied" if mark_only else "Applied"
    if names:
        print(f"{verb}: {', '.join(names)}")
    else:
        print("The database is up to date.")


if __name__ == "__main__":
    main()
