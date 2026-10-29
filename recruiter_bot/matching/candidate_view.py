"""The order of a candidate's jobs (D-51).

1. Score: the fit, the same number the recruiter sees (D-15).
2. Preference: jobs whose title the candidate listed in job_preferences come first.
3. Standing: where the candidate has the best chance, i.e. beats the largest share of rivals.
4. Posting date: newer first, since older ads are more likely already filled.
5. A neutral hash of the job and candidate ids, as in the recruiter's view (D-16).

Score stays first: standing measures competition, not fit, and sorting by it first would push
weak-fit jobs with few rivals above strong-fit ones.
"""
import hashlib
from dataclasses import dataclass
from datetime import datetime

import psycopg

from recruiter_bot.matching.match_scorer import ALGORITHM_VERSION, MATCH_SCORE
from recruiter_bot.matching.match_store import StoredMatch


@dataclass(frozen=True)
class Standing:
    above: int        # rivals who score higher
    below: int        # rivals who score lower
    level: int        # rivals with the same score
    job_slug: str     # the normalized title, to compare with the candidate's preferences
    posted_at: datetime

    @property
    def share_beaten(self) -> float:
        """The share of rivals this candidate beats, ties counting half. 1.0 with no rivals."""
        rivals = self.above + self.below + self.level
        if rivals == 0:
            return 1.0
        return (self.below + 0.5 * self.level) / rivals

    @property
    def is_top_applicant(self) -> bool:
        """Nobody competing scores higher. The only part of the standing shown to the candidate,
        since a percentage in a small pool would reveal other candidates' scores."""
        return self.above == 0


# For each job this candidate matches: how many rivals score above, below, or level with them.
# A rival is another candidate with a strong or possible match (50 or more) for the same job who
# is open to opportunities: someone not looking isn't competing for the role right now.
STANDINGS_SQL = """
    SELECT mine.job_id,
           count(rival.candidate_id) FILTER (WHERE rival.score > mine.score) AS above,
           count(rival.candidate_id) FILTER (WHERE rival.score < mine.score) AS below,
           count(rival.candidate_id) FILTER (WHERE rival.score = mine.score) AS level,
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
    for job_id, above, below, level, job_slug, posted_at in conn.execute(STANDINGS_SQL, parameters).fetchall():
        standings[job_id] = Standing(above, below, level, job_slug, posted_at)
    return standings


def preferences_of(conn: psycopg.Connection, candidate_id: int) -> set[str]:
    return {preference for (preference,) in conn.execute(PREFERENCES_SQL, (candidate_id,)).fetchall()}


def neutral_hash(job_id: int, candidate_id: int) -> str:
    """The same md5 as the recruiter's view uses in SQL (D-16): fixed, but favouring no one."""
    return hashlib.md5(f"{job_id}:{candidate_id}".encode()).hexdigest()


def order_for_candidate(
    matches: list[StoredMatch], standings: dict[int, Standing], preferences: set[str],
) -> list[StoredMatch]:
    """The candidate's matches in the order of D-51."""

    def sort_key(match: StoredMatch):
        standing = standings[match.job_id]
        is_preferred = standing.job_slug in preferences
        return (
            -match.score,                                  # 1. best fit first
            not is_preferred,                              # 2. preferred jobs first (False sorts before True)
            -standing.share_beaten,                        # 3. best chance first
            -standing.posted_at.timestamp(),               # 4. newest posting first
            neutral_hash(match.job_id, match.candidate_id),  # 5. still tied: neutral, deterministic
        )

    return sorted(matches, key=sort_key)
