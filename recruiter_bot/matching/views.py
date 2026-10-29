"""How stored matches are shown: the recruiter's view of a job, and the candidate's view of their jobs."""
import hashlib
from dataclasses import dataclass
from datetime import datetime

import psycopg

from recruiter_bot.matching.scorer import CULTURE_WEIGHT, EXPERIENCE_WEIGHT, MATCH_SCORE, SKILL_WEIGHT
from recruiter_bot.matching.store import StoredMatch

# Near misses are shown only when nothing reaches a match, and then at most this many.
NEAR_MISS_LIMIT = 3


# ---- Both views: which matches are shown

def is_a_match(match: StoredMatch) -> bool:
    """A strong or possible match, i.e. a score of 50 or more."""
    return match.tier in ("strong_match", "possible_match")


def shown_matches(matches: list[StoredMatch]) -> tuple[list[StoredMatch], bool]:
    """The matches worth showing, best first; near misses only when nothing better exists."""
    real_matches = [match for match in matches if is_a_match(match)]
    if real_matches:
        # Strong before possible, so ranks follow the tiers, not the score alone.
        real_matches.sort(key=lambda match: match.tier != "strong_match")
        return real_matches, False
    near_misses = [match for match in matches if match.tier == "near_miss"]
    return near_misses[:NEAR_MISS_LIMIT], bool(near_misses)


# ---- The recruiter's view of one job

def open_candidates(matches: list[StoredMatch]) -> list[StoredMatch]:
    """Candidates who are open to opportunities, whatever their start date."""
    return [match for match in matches if match.candidate_is_open]


def proactive_offers(matches: list[StoredMatch]) -> list[StoredMatch]:
    """Candidates not looking who score higher than the best open candidate: worth approaching."""
    best_open_score = max((match.score for match in open_candidates(matches)), default=None)
    return [
        match for match in matches
        if not match.candidate_is_open and is_a_match(match)
        and (best_open_score is None or match.score > best_open_score)
    ]


# ---- The candidate's view: score, top applicant, newest posting, then a neutral hash

@dataclass(frozen=True)
class Standing:
    above: int  # open rivals with a real match who score higher
    posted_at: datetime

    @property
    def is_top_applicant(self) -> bool:
        """Nobody competing scores higher; shown as yes or no, so others' scores stay private."""
        return self.above == 0


# Per job, how many open rivals (scoring 50 or more) score above this candidate.
STANDINGS_SQL = """
    SELECT mine.job_id,
           count(rival.candidate_id) FILTER (WHERE rival.score > mine.score) AS above,
           jobs.created_at
    FROM matches AS mine
    JOIN jobs ON jobs.job_id = mine.job_id
    LEFT JOIN (
        SELECT matches.job_id, matches.candidate_id, matches.score
        FROM matches
        JOIN candidates ON candidates.candidate_id = matches.candidate_id
        WHERE matches.score >= %(match_score)s AND candidates.open_to_opportunities
    ) AS rival ON rival.job_id = mine.job_id AND rival.candidate_id <> mine.candidate_id
    WHERE mine.candidate_id = %(candidate_id)s
    GROUP BY mine.job_id, jobs.created_at
"""


def standings_for_candidate(conn: psycopg.Connection, candidate_id: int) -> dict[int, Standing]:
    """Job id -> this candidate's standing among that job's rivals. One query for all their jobs."""
    rows = conn.execute(STANDINGS_SQL, {"candidate_id": candidate_id, "match_score": MATCH_SCORE}).fetchall()
    return {job_id: Standing(above, posted_at) for job_id, above, posted_at in rows}


def order_for_candidate(matches: list[StoredMatch], standings: dict[int, Standing]) -> list[StoredMatch]:
    def sort_key(match: StoredMatch):
        standing = standings[match.job_id]
        return (
            -match.score,                       # 1. best fit first
            not standing.is_top_applicant,      # 2. top applicant first (False sorts before True)
            -standing.posted_at.timestamp(),    # 3. newest posting first
            # 4. still tied: the same md5 the recruiter's view uses in SQL, fixed but favouring no one
            hashlib.md5(f"{match.job_id}:{match.candidate_id}".encode()).hexdigest(),
        )

    return sorted(matches, key=sort_key)


# ---- Evidence: matched and missing by default, points with ?explain=true

@dataclass(frozen=True)
class FactorEvidence:
    score: float          # 0 to 1
    weight: float         # its share of the total; the weights add up to 1
    points: float         # 100 x weight x score: what this factor adds to the total
    detail: str           # the same fact in words, e.g. "2 of 3 required skills"
    matched: list[str]
    missing: list[str]


@dataclass(frozen=True)
class MatchEvidence:
    skills: FactorEvidence
    experience: FactorEvidence
    culture: FactorEvidence | None  # None when the job lists no culture keywords


def evidence_for(match: StoredMatch) -> MatchEvidence:
    skills_weight, experience_weight = SKILL_WEIGHT, EXPERIENCE_WEIGHT
    if match.culture_score is None:
        # The job has no culture keywords: the other two weights are rescaled to add up to 1.
        skills_weight = SKILL_WEIGHT / (SKILL_WEIGHT + EXPERIENCE_WEIGHT)
        experience_weight = EXPERIENCE_WEIGHT / (SKILL_WEIGHT + EXPERIENCE_WEIGHT)

    years, minimum = match.candidate_experience_years, match.job_min_experience_years
    experience_detail = f"{years} years, {'meets' if years >= minimum else 'below'} the {minimum}-year minimum"

    return MatchEvidence(
        skills=_factor(match.skill_score, skills_weight, match.matched_skills, match.missing_skills,
                       "required skills"),
        experience=FactorEvidence(
            score=match.experience_score,
            weight=round(experience_weight, 3),
            points=round(100 * experience_weight * match.experience_score, 1),
            detail=experience_detail,
            matched=[],
            missing=[],
        ),
        culture=None if match.culture_score is None else _factor(
            match.culture_score, CULTURE_WEIGHT, match.matched_culture, match.missing_culture, "culture keywords",
        ),
    )


def _factor(score: float, weight: float, matched: list[str], missing: list[str], noun: str) -> FactorEvidence:
    """'1.5 of 3 required skills': a related skill can make the first number a fraction."""
    listed = len(matched) + len(missing)
    return FactorEvidence(
        score=score,
        weight=round(weight, 3),
        points=round(100 * weight * score, 1),
        detail=f"{round(score * listed, 2):g} of {listed} {noun}",
        matched=matched,
        missing=missing,
    )
