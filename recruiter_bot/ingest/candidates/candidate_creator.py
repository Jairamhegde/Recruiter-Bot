from typing import Any

import psycopg

from recruiter_bot.ingest.batch_inserter import INGEST_LOCK_SQL, insert_batch
from recruiter_bot.ingest.candidates.candidate_batch import build_candidate_batch
from recruiter_bot.ingest.candidates.candidate_extractor import extract_candidates
from recruiter_bot.ingest.event_log_writer import log_rejected
from recruiter_bot.ingest.jobs.job_batch import build_job_batch
from recruiter_bot.ingest.taxonomy.term_linker import link_record_terms
from recruiter_bot.matching.match_store import refresh_candidate_matches

CANDIDATE_ID_BY_KEY_SQL = "SELECT candidate_id FROM candidates WHERE source_key = %s"

CANDIDATE_WITH_EMAIL_SQL = "SELECT EXISTS (SELECT 1 FROM candidates WHERE email = %s)"


class CandidateRejected(ValueError):
    """The input breaks an ingestion rule; the message says which."""


class CandidateExists(ValueError):
    """A candidate with the same email is already stored. Names may repeat (D-53)."""


def add_candidate(conn: psycopg.Connection, raw_candidate: Any, source: str = "api") -> int:
    """Validates and stores one new candidate like the seed does (D-35), with its matches (D-37).
    Returns its candidate_id."""
    today = conn.execute("SELECT current_date").fetchone()[0]
    conn.commit()

    extraction = extract_candidates([raw_candidate], today, source)
    if extraction.rejected:
        log_rejected(conn, "candidate", source, extraction.rejected)
        raise CandidateRejected(extraction.rejected[0].message)
    record = extraction.records[0]

    # The lock makes the email check and the insert one step, so two requests can't both pass the check.
    with conn.transaction():
        conn.execute(INGEST_LOCK_SQL)
        if record.email is not None and conn.execute(CANDIDATE_WITH_EMAIL_SQL, (record.email,)).fetchone()[0]:
            raise CandidateExists(f"a candidate with email {record.email!r} already exists")
        insert_batch(conn, build_candidate_batch([record]), build_job_batch([]), source=source)
        candidate_id = conn.execute(CANDIDATE_ID_BY_KEY_SQL, (record.source_key,)).fetchone()[0]
        # Same transaction, so nobody sees the candidate without its matches.
        # Unknown words are linked first, so this record's matches already use the links (D-41).
        link_record_terms(conn, record.skill_slugs, record.trait_slugs)
        refresh_candidate_matches(conn, candidate_id)
        return candidate_id
