from dataclasses import dataclass

import psycopg

from recruiter_bot.ingest.candidates.candidate_batch import CandidateBatch
from recruiter_bot.ingest.candidates.candidate_writer import save_candidates
from recruiter_bot.ingest.event_log_writer import log_accepted
from recruiter_bot.ingest.jobs.job_batch import JobBatch
from recruiter_bot.ingest.jobs.job_writer import save_jobs
from recruiter_bot.ingest.vocabulary_writer import resolve_skill_ids, resolve_trait_ids

INGEST_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtext('recruiter_bot.ingest'))"


@dataclass(frozen=True)
class BatchResult:
    candidates: int
    jobs: int
    skills: int
    traits: int


def insert_batch(
    conn: psycopg.Connection,
    candidate_batch: CandidateBatch,
    job_batch: JobBatch,
    source: str = "seed",
) -> BatchResult:
    """Writes candidates and jobs in one transaction: all of it, or none of it."""
    with conn.transaction():
        conn.execute(INGEST_LOCK_SQL)

        skill_slugs = []
        for _, skill_slug in candidate_batch.skill_links + job_batch.skill_links:
            skill_slugs.append(skill_slug)
        trait_slugs = []
        for _, trait_slug in candidate_batch.trait_links + job_batch.culture_trait_links:
            trait_slugs.append(trait_slug)

        skill_ids = resolve_skill_ids(conn, skill_slugs)
        trait_ids = resolve_trait_ids(conn, trait_slugs)

        candidate_ids = save_candidates(conn, candidate_batch, skill_ids, trait_ids)
        job_ids = save_jobs(conn, job_batch, skill_ids, trait_ids)

        log_accepted(conn, "candidate", source, candidate_batch.slugs, candidate_batch.payloads)
        log_accepted(conn, "job", source, job_batch.slugs, job_batch.payloads)

    return BatchResult(
        candidates=len(candidate_ids),
        jobs=len(job_ids),
        skills=len(set(skill_ids.values())),
        traits=len(set(trait_ids.values())),
    )
