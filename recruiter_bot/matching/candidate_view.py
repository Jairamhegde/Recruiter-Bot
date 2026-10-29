"""The order of a candidate's jobs: score, top applicant, newest posting, then a hash."""
import hashlib
from dataclasses import dataclass
from datetime import datetime

import psycopg

from recruiter_bot.matching.match_scorer import ALGORITHM_VERSION, MATCH_SCORE
from recruiter_bot.matching.match_store import StoredMatch


@dataclass(frozen=True)
class Standing:
    above: int        # rivals who score higher
    job_slug: str     # the normalized title, to compare with the candidate's preferences
    posted_at: datetime

    @property
    def is_top_applicant(self) -> bool:
        """Nobody competing scores higher; shown as yes or no, so others' scores stay private."""
        return self.above == 0


# Per job, how many open rivals (scoring 50 or more) score above this candidate.
STANDINGS_SQL = """
    SELECT mine.job_id,
           count(rival.candidate_id) FILTER (WHERE rival.score > mine.score) AS above,
           jobs.slug,
           jobs.created_at
    FROM matches AS mine
    JOIN jobs ON jobs.job_id = mine.job_id
    LEFT JOIN (
        SELECT matches.job_id, matches.candidate_id, matches.score
        FROM matches
        JOIN candidates ON candidates.candidate_id = matches.candidate_id
        WHERE matches.score >= %(match_score)s
          AND matches.algorithm_version = %(version)s
          AND candidates.open_to_opportunities
    ) AS rival ON rival.job_id = mine.job_id AND rival.candidate_id <> mine.candidate_id
    WHERE mine.candidate_id = %(candidate_id)s AND mine.algorithm_version = %(version)s
    GROUP BY mine.job_id, jobs.slug, jobs.created_at
"""

PREFERENCES_SQL = "SELECT preference FROM candidate_job_preferences WHERE candidate_id = %s"


def standings_for_candidate(conn: psycopg.Connection, candidate_id: int) -> dict[int, Standing]:
    """Job id -> this candidate's standing among that job's rivals. One query for all their jobs."""
    standings = {}
    parameters = {"candidate_id": candidate_id, "version": ALGORITHM_VERSION, "match_score": MATCH_SCORE}
    for job_id, above, job_slug, posted_at in conn.execute(STANDINGS_SQL, parameters).fetchall():
        standings[job_id] = Standing(above, job_slug, posted_at)
    return standings


def preferences_of(conn: psycopg.Connection, candidate_id: int) -> set[str]:
    return {preference for (preference,) in conn.execute(PREFERENCES_SQL, (candidate_id,)).fetchall()}


def neutral_hash(job_id: int, candidate_id: int) -> str:
    """The same md5 as the recruiter's view uses in SQL: fixed, but favouring no one."""
    return hashlib.md5(f"{job_id}:{candidate_id}".encode()).hexdigest()


def order_for_candidate(matches: list[StoredMatch], standings: dict[int, Standing]) -> list[StoredMatch]:
    """The candidate's matches in ranked order."""

    def sort_key(match: StoredMatch):
        standing = standings[match.job_id]
        return (
            -match.score,                                  # 1. best fit first
            not standing.is_top_applicant,                 # 2. top applicant first (False sorts before True)
            -standing.posted_at.timestamp(),               # 3. newest posting first
            neutral_hash(match.job_id, match.candidate_id),  # 4. still tied: neutral, deterministic
        )

    return sorted(matches, key=sort_key)
