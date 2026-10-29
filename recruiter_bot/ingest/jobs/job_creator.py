from typing import Any

import psycopg

from recruiter_bot.ingest.batch_inserter import INGEST_LOCK_SQL, insert_batch
from recruiter_bot.ingest.candidates.candidate_batch import build_candidate_batch
from recruiter_bot.ingest.event_log_writer import log_rejected
from recruiter_bot.ingest.jobs.job_batch import build_job_batch
from recruiter_bot.ingest.jobs.job_extractor import extract_jobs
from recruiter_bot.ingest.taxonomy.term_linker import link_record_terms
from recruiter_bot.matching.match_store import refresh_job_matches

JOB_ID_BY_KEY_SQL = "SELECT job_id FROM jobs WHERE source_key = %s"

JOB_AT_COMPANY_SQL = "SELECT EXISTS (SELECT 1 FROM jobs WHERE lower(company) = lower(%s) AND slug = %s)"


class JobRejected(ValueError):
    """The input breaks an ingestion rule; the message says which."""


class JobExists(ValueError):
    """The same company already has a job with this title."""


def add_job(conn: psycopg.Connection, raw_job: Any, source: str = "api") -> int:
    """Validates and stores one new job like the seed does, with its matches. Returns its job_id."""
    extraction = extract_jobs([raw_job], source)
    if extraction.rejected:
        log_rejected(conn, "job", source, extraction.rejected)
        raise JobRejected(extraction.rejected[0].message)
    record = extraction.records[0]

    # The lock makes the title check and the insert one step, so two requests can't both pass the check.
    with conn.transaction():
        conn.execute(INGEST_LOCK_SQL)
        if record.company is not None and conn.execute(JOB_AT_COMPANY_SQL, (record.company, record.slug)).fetchone()[0]:
            raise JobExists(f"{record.company!r} already has a job titled {record.title!r}")
        insert_batch(conn, build_candidate_batch([]), build_job_batch([record]), source=source)
        job_id = conn.execute(JOB_ID_BY_KEY_SQL, (record.source_key,)).fetchone()[0]
        # Same transaction, so the job never appears without its matches.
        link_record_terms(conn, record.skill_slugs, record.culture_trait_slugs)
        refresh_job_matches(conn, job_id)
        return job_id
