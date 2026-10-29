"""Applies pending SQL migrations in name order. Usage: python -m recruiter_bot.migrate"""
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


def apply_pending(conn: psycopg.Connection) -> list[str]:
    """Each file runs in its own transaction with its history row: it's applied completely, or not at all."""
    conn.execute(CREATE_HISTORY_SQL)
    applied = {filename for (filename,) in conn.execute(APPLIED_SQL).fetchall()}
    names = []
    # 001_init.sql, 002_..., ...: the numbered prefix fixes the order.
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in applied:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute(RECORD_SQL, (path.name,))
        names.append(path.name)
    return names


def main() -> None:
    with connect() as conn:
        conn.autocommit = True  # each file manages its own transaction
        names = apply_pending(conn)
    print(f"Applied: {', '.join(names)}" if names else "The database is up to date.")


if __name__ == "__main__":
    main()
