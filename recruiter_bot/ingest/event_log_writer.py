import json
from typing import Any

import psycopg

from recruiter_bot.ingest.record_errors import RecordError

INSERT_EVENTS_SQL = """
    INSERT INTO ingestion_events (entity_type, source, entity_slug, payload, status, error)
    SELECT event.entity_type, event.source, event.entity_slug, event.payload::jsonb, event.status, event.error
    FROM unnest(%s::text[], %s::text[], %s::text[], %s::text[], %s::text[], %s::text[])
         AS event (entity_type, source, entity_slug, payload, status, error)
"""


def log_accepted(
    conn: psycopg.Connection, entity_type: str, source: str, slugs: list[str], payloads: list[Any]
) -> None:
    if not slugs:
        return
    count = len(slugs)
    conn.execute(INSERT_EVENTS_SQL, (
        [entity_type] * count,
        [source] * count,
        slugs,
        [json.dumps(payload) for payload in payloads],
        ["accepted"] * count,
        [None] * count,
    ))


def log_rejected(conn: psycopg.Connection, entity_type: str, source: str, errors: list[RecordError]) -> None:
    """Runs in its own transaction, so rejections are recorded even if nothing else is written."""
    if not errors:
        return
    count = len(errors)
    with conn.transaction():
        conn.execute(INSERT_EVENTS_SQL, (
            [entity_type] * count,
            [source] * count,
            [None] * count,
            [json.dumps(error.payload) for error in errors],
            ["rejected"] * count,
            [error.message for error in errors],
        ))
