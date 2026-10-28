from typing import Any

import psycopg

from recruiter_bot.ingest.batch_inserter import INGEST_LOCK_SQL, insert_batch
from recruiter_bot.ingest.candidates.candidate_batch import build_candidate_batch
from recruiter_bot.ingest.event_log_writer import log_rejected
from recruiter_bot.ingest.jobs.job_batch import build_job_batch
from recruiter_bot.ingest.jobs.job_extractor import extract_jobs
from recruiter_bot.matching.match_store import refresh_job_matches

JOB_ID_BY_SLUG_SQL = "SELECT job_id FROM jobs WHERE slug = %s"


class JobRejected(ValueError):
    """The input breaks an ingestion rule; the message says which."""


class JobExists(ValueError):
    """A job with the same title (slug) is already stored."""


def add_job(conn: psycopg.Connection, raw_job: Any, source: str = "api") -> int:
    """Validates and stores one new job like the seed does, with its matches (D-40). Returns its job_id."""
    extraction = extract_jobs([raw_job])
    if extraction.rejected:
        log_rejected(conn, "job", source, extraction.rejected)
        raise JobRejected(extraction.rejected[0].message)
    record = extraction.records[0]

    # The lock makes the title check and the insert one step, so two requests can't both pass the check.
    with conn.transaction():
        conn.execute(INGEST_LOCK_SQL)
        if conn.execute(JOB_ID_BY_SLUG_SQL, (record.slug,)).fetchone() is not None:
            raise JobExists(f"a job titled {record.title!r} already exists")
        insert_batch(conn, build_candidate_batch([]), build_job_batch([record]), source=source)
        job_id = conn.execute(JOB_ID_BY_SLUG_SQL, (record.slug,)).fetchone()[0]
        # Same transaction, so nobody sees the job without its matches (D-37).
        refresh_job_matches(conn, job_id)
        return job_id
