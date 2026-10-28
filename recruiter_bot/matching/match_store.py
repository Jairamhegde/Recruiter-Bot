from dataclasses import dataclass

import psycopg

from recruiter_bot.ingest.batch_inserter import INGEST_LOCK_SQL
from recruiter_bot.matching.match_scorer import ALGORITHM_VERSION, MatchResult, score_match, tier_for
from recruiter_bot.matching.profile_reader import load_candidate_profiles, load_job_profiles
from recruiter_bot.matching.term_credit import TermCredit, load_taxonomy_credit

# ---- Writing (D-37): replace an entity's rows, never append

DELETE_CANDIDATE_MATCHES_SQL = "DELETE FROM matches WHERE candidate_id = %s"

DELETE_JOB_MATCHES_SQL = "DELETE FROM matches WHERE job_id = %s"

DELETE_ALL_MATCHES_SQL = "DELETE FROM matches"

INSERT_MATCH_SQL = """
    INSERT INTO matches (job_id, candidate_id, skill_score, experience_score, culture_score,
                         score, reason, algorithm_version, matched_skills, missing_skills)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def refresh_candidate_matches(conn: psycopg.Connection, candidate_id: int, credit: TermCredit | None = None) -> int:
    """Replaces one candidate's stored matches, against every job. Returns how many qualify."""
    with conn.transaction():
        conn.execute(INGEST_LOCK_SQL)
        conn.execute(DELETE_CANDIDATE_MATCHES_SQL, (candidate_id,))
        credit = credit or load_taxonomy_credit(conn)
        results = []
        for candidate in load_candidate_profiles(conn, candidate_id):
            for job in load_job_profiles(conn):
                results.append(score_match(candidate, job, credit))
        return _insert_qualifying(conn, results)


def refresh_job_matches(conn: psycopg.Connection, job_id: int, credit: TermCredit | None = None) -> int:
    """Replaces one job's stored matches, against every candidate. Returns how many qualify."""
    with conn.transaction():
        conn.execute(INGEST_LOCK_SQL)
        conn.execute(DELETE_JOB_MATCHES_SQL, (job_id,))
        credit = credit or load_taxonomy_credit(conn)
        results = []
        for job in load_job_profiles(conn, job_id):
            for candidate in load_candidate_profiles(conn):
                results.append(score_match(candidate, job, credit))
        return _insert_qualifying(conn, results)


def refresh_all_matches(conn: psycopg.Connection) -> int:
    """Replaces every stored match: after a seed run, a taxonomy reload or a formula change."""
    with conn.transaction():
        conn.execute(INGEST_LOCK_SQL)
        conn.execute(DELETE_ALL_MATCHES_SQL)
        credit = load_taxonomy_credit(conn)
        jobs = load_job_profiles(conn)
        results = []
        for candidate in load_candidate_profiles(conn):
            for job in jobs:
                results.append(score_match(candidate, job, credit))
        return _insert_qualifying(conn, results)


def _insert_qualifying(conn: psycopg.Connection, results: list[MatchResult]) -> int:
    # Row by row, because matched and missing skills differ in length per pair.
    rows = []
    for result in results:
        if result.qualifies:
            rows.append((
                result.job_id, result.candidate_id, result.skill_score, result.experience_score,
                result.culture_score, result.score, result.reason, ALGORITHM_VERSION,
                result.matched_skills, result.missing_skills,
            ))
    if rows:
        with conn.cursor() as cursor:
            cursor.executemany(INSERT_MATCH_SQL, rows)
    return len(rows)


# ---- Staleness check, at startup

STALE_OR_EMPTY_SQL = """
    SELECT NOT EXISTS (SELECT 1 FROM matches)
        OR EXISTS (SELECT 1 FROM matches WHERE algorithm_version <> %s)
"""


def refresh_if_stale(conn: psycopg.Connection) -> bool:
    """Recomputes everything when the table is empty or holds another algorithm version. Returns whether it did."""
    if conn.execute(STALE_OR_EMPTY_SQL, (ALGORITHM_VERSION,)).fetchone()[0]:
        refresh_all_matches(conn)
        return True
    return False


# ---- Reading: only rows from the current algorithm version, best first (D-16)

@dataclass(frozen=True)
class StoredMatch:
    job_id: int
    job_title: str
    candidate_id: int
    candidate_name: str
    score: float
    skill_score: float
    experience_score: float
    culture_score: float | None
    matched_skills: list[str]
    missing_skills: list[str]
    reason: str

    @property
    def tier(self) -> str:
        return tier_for(self.score)


STORED_MATCHES_SELECT = """
    SELECT matches.job_id, jobs.title, matches.candidate_id, candidates.full_name,
           matches.score, matches.skill_score, matches.experience_score, matches.culture_score,
           matches.matched_skills, matches.missing_skills, matches.reason
    FROM matches
    JOIN jobs       ON jobs.job_id             = matches.job_id
    JOIN candidates ON candidates.candidate_id = matches.candidate_id
"""

MATCHES_FOR_CANDIDATE_SQL = STORED_MATCHES_SELECT + """
    WHERE matches.candidate_id = %s AND matches.algorithm_version = %s
    ORDER BY matches.score DESC, matches.skill_score DESC, jobs.title
"""

# D-16: the best fit first; among equal fits, whoever can start soonest.
# Open candidates come before those not looking, then the earliest start date. A date
# in the past counts as today, since "Immediate" is stored as the day it was loaded.
MATCHES_FOR_JOB_SQL = STORED_MATCHES_SELECT + """
    WHERE matches.job_id = %s AND matches.algorithm_version = %s
    ORDER BY matches.score DESC,
             matches.skill_score DESC,
             candidates.open_to_opportunities DESC,
             GREATEST(candidates.available_from, current_date),
             candidates.full_name
"""

CANDIDATE_EXISTS_SQL = "SELECT EXISTS (SELECT 1 FROM candidates WHERE candidate_id = %s)"

JOB_EXISTS_SQL = "SELECT EXISTS (SELECT 1 FROM jobs WHERE job_id = %s)"


def stored_matches_for_candidate(conn: psycopg.Connection, candidate_id: int) -> list[StoredMatch] | None:
    """Best jobs first. None if the candidate doesn't exist."""
    if not conn.execute(CANDIDATE_EXISTS_SQL, (candidate_id,)).fetchone()[0]:
        return None
    return _stored_matches(conn, MATCHES_FOR_CANDIDATE_SQL, candidate_id)


def stored_matches_for_job(conn: psycopg.Connection, job_id: int) -> list[StoredMatch] | None:
    """Best candidates first. None if the job doesn't exist."""
    if not conn.execute(JOB_EXISTS_SQL, (job_id,)).fetchone()[0]:
        return None
    return _stored_matches(conn, MATCHES_FOR_JOB_SQL, job_id)


def _stored_matches(conn: psycopg.Connection, sql: str, entity_id: int) -> list[StoredMatch]:
    matches = []
    for row in conn.execute(sql, (entity_id, ALGORITHM_VERSION)).fetchall():
        (job_id, job_title, candidate_id, candidate_name, score, skill_score, experience_score,
         culture_score, matched_skills, missing_skills, reason) = row
        matches.append(StoredMatch(
            job_id=job_id,
            job_title=job_title,
            candidate_id=candidate_id,
            candidate_name=candidate_name,
            score=float(score),
            skill_score=float(skill_score),
            experience_score=float(experience_score),
            culture_score=None if culture_score is None else float(culture_score),
            matched_skills=matched_skills,
            missing_skills=missing_skills,
            reason=reason,
        ))
    return matches
