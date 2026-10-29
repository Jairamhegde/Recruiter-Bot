"""Why a match has its score (D-50).

One calculation, two views of it:
- the default response shows only what matched and what is missing;
- with ?explain=true it also shows the score, weight and points of each factor.

    score = skills points + experience points + culture points
    points = 100 x weight x factor score

So with explain, a recruiter can check every number: Michael for Sales Engineer is
46.7 (skills) + 20.0 (experience) + 5.0 (culture) = 71.7.
"""
from dataclasses import dataclass

from recruiter_bot.matching.match_scorer import CULTURE_WEIGHT, EXPERIENCE_WEIGHT, SKILL_WEIGHT
from recruiter_bot.matching.match_store import StoredMatch


@dataclass(frozen=True)
class FactorEvidence:
    score: float          # 0 to 1
    weight: float         # its share of the total; the weights add up to 1
    points: float         # 100 x weight x score: what this factor adds to the total
    detail: str           # the same fact in words, e.g. "2 of 3 required skills"
    matched: list[str]    # what earned credit (empty for experience)
    missing: list[str]    # what earned none (empty for experience)


@dataclass(frozen=True)
class MatchEvidence:
    skills: FactorEvidence
    experience: FactorEvidence
    culture: FactorEvidence | None  # None when the job lists no culture keywords


def evidence_for(match: StoredMatch) -> MatchEvidence:
    if match.culture_score is None:
        # The job has no culture keywords: the other two weights are rescaled to add up to 1 (D-32).
        skills_weight = SKILL_WEIGHT / (SKILL_WEIGHT + EXPERIENCE_WEIGHT)
        experience_weight = EXPERIENCE_WEIGHT / (SKILL_WEIGHT + EXPERIENCE_WEIGHT)
    else:
        skills_weight = SKILL_WEIGHT
        experience_weight = EXPERIENCE_WEIGHT

    return MatchEvidence(
        skills=FactorEvidence(
            score=match.skill_score,
            weight=round(skills_weight, 3),
            points=_points(skills_weight, match.skill_score),
            detail=_coverage_in_words(match.skill_score, match.matched_skills, match.missing_skills, "required skills"),
            matched=match.matched_skills,
            missing=match.missing_skills,
        ),
        experience=FactorEvidence(
            score=match.experience_score,
            weight=round(experience_weight, 3),
            points=_points(experience_weight, match.experience_score),
            detail=_experience_in_words(match.candidate_experience_years, match.job_min_experience_years),
            matched=[],
            missing=[],
        ),
        culture=None if match.culture_score is None else FactorEvidence(
            score=match.culture_score,
            weight=CULTURE_WEIGHT,
            points=_points(CULTURE_WEIGHT, match.culture_score),
            detail=_coverage_in_words(match.culture_score, match.matched_culture, match.missing_culture,
                                      "culture keywords"),
            matched=match.matched_culture,
            missing=match.missing_culture,
        ),
    )


def _points(weight: float, score: float) -> float:
    return round(100 * weight * score, 1)


def _coverage_in_words(score: float, matched: list[str], missing: list[str], noun: str) -> str:
    """'1.5 of 3 required skills': partial credit (a related skill, D-29) can make the first number a fraction."""
    listed = len(matched) + len(missing)
    earned = round(score * listed, 2)
    return f"{earned:g} of {listed} {noun}"


def _experience_in_words(years: int, minimum: int) -> str:
    if years >= minimum:
        return f"{years} years, meets the {minimum}-year minimum"
    return f"{years} years, below the {minimum}-year minimum"
