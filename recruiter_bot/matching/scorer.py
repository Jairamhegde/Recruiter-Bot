"""The score of one candidate for one job. Pure: no database, and the same in both directions.

score = 100 x (0.7 x skills + 0.2 x experience + 0.1 x culture)
"""
from dataclasses import dataclass, field
from typing import Protocol

from recruiter_bot.matching.assignment import best_assignment
from recruiter_bot.taxonomy import Credit

SKILL_WEIGHT = 0.7
EXPERIENCE_WEIGHT = 0.2
CULTURE_WEIGHT = 0.1

# Tiers for a qualifying match. 50 itself counts as a match.
STRONG_MATCH_SCORE = 70.0
MATCH_SCORE = 50.0

# A required minimum still admits someone up to this many years short: scored in proportion,
# at most a possible match, and flagged in the reason. Further below, no match.
EXPERIENCE_GRACE_YEARS = 1


class TermCredit(Protocol):
    """How much a candidate term earns toward a job term. The scorer only sees this."""

    def credit(self, concept_type: str, candidate_term: str, job_term: str) -> Credit: ...


@dataclass(frozen=True)
class JobProfile:
    job_id: int
    title: str
    min_experience_years: int
    required_skills: list[str]
    culture_keywords: list[str] = field(default_factory=list)
    experience_requirement: str = "required"  # "required" (the default) or "preferred"


@dataclass(frozen=True)
class CandidateProfile:
    candidate_id: int
    full_name: str
    experience_years: int
    skills: list[str]
    traits: list[str] = field(default_factory=list)


# ---- Comparing two lists of terms

@dataclass(frozen=True)
class TermMatch:
    required_term: str
    candidate_term: str
    credit: Credit


@dataclass(frozen=True)
class TermComparison:
    matches: list[TermMatch]
    missing_terms: list[str]
    score: float  # credit earned / number of required terms

    @property
    def matched_terms(self) -> list[str]:
        return [match.required_term for match in self.matches]


def compare_terms(
    candidate_terms: list[str], required_terms: list[str], concept_type: str, credit: TermCredit,
) -> TermComparison:
    """Each candidate term covers one requirement at most, so one `persuasion` can't count twice."""
    if not required_terms:
        return TermComparison([], [], 0.0)

    terms = sorted(set(candidate_terms))  # a fixed order, so ties are always settled the same way
    credits = [[credit.credit(concept_type, term, required) for term in terms] for required in required_terms]
    pairing = best_pairing([[c.value for c in row] for row in credits])

    matches = []
    missing_terms = []
    for row, required_term in enumerate(required_terms):
        column = pairing[row]
        if column is None:
            missing_terms.append(required_term)
        else:
            matches.append(TermMatch(required_term, terms[column], credits[row][column]))
    total = sum(match.credit.value for match in matches)
    return TermComparison(matches, missing_terms, total / len(required_terms))


def best_pairing(credits: list[list[float]]) -> list[int | None]:
    """For each requirement (row), the candidate term (column) it is paired with, or None.

    This is the assignment problem, solved exactly by the Hungarian algorithm in O(n³).
    The weights put total credit first; a much smaller penalty then settles ties the same way
    every time: the earlier requirement decides, unpaired first, then its best term
    (most credit, then alphabetical).
    """
    rows = len(credits)
    if rows == 0:
        return []
    # Only terms that earn credit for something can be part of the answer.
    useful = [column for column in range(len(credits[0])) if any(row[column] > 0 for row in credits)]

    base = len(useful) + 1  # a rank never reaches this
    big = base ** rows      # more than all the penalties added together
    weights = []
    for row in range(rows):
        earning = [position for position, column in enumerate(useful) if credits[row][column] > 0]
        earning.sort(key=lambda position: (-credits[row][useful[position]], position))
        rank_of = {position: rank for rank, position in enumerate(earning, start=1)}
        penalty_unit = base ** (rows - 1 - row)
        weights.append([
            # Whole numbers, so equal totals compare as exactly equal: 0.5 -> 500.
            round(credits[row][column] * 1000) * big - rank_of[position] * penalty_unit
            if position in rank_of else 0
            for position, column in enumerate(useful)
        ])

    return [None if column is None else useful[column] for column in best_assignment(weights)]


# ---- The score

def experience_fit(experience_years: int, min_experience_years: int) -> float:
    """1.0 at or above the minimum; proportional below it. Extra years earn nothing extra."""
    if min_experience_years == 0 or experience_years >= min_experience_years:
        return 1.0
    return experience_years / min_experience_years


def tier_for(score: float, meets_minimum_experience: bool = True) -> str:
    """The tier of a qualifying match; below the minimum experience, at most possible."""
    if score >= STRONG_MATCH_SCORE and meets_minimum_experience:
        return "strong_match"
    if score >= MATCH_SCORE:
        return "possible_match"
    return "near_miss"


@dataclass(frozen=True)
class MatchResult:
    job_id: int
    candidate_id: int
    score: float
    skill_score: float
    experience_score: float
    culture_score: float | None  # None when the job lists no culture keywords
    skill_matches: list[TermMatch]
    matched_skills: list[str]
    missing_skills: list[str]
    matched_culture: list[str]
    missing_culture: list[str]
    reason: str
    meets_minimum_experience: bool
    years_short: int  # how far below the job's minimum; 0 when it is met
    experience_required: bool  # the job made the minimum a hard requirement

    @property
    def qualifies(self) -> bool:
        """Needs at least one skill in common, and, when the job requires its minimum, at most 1 year short."""
        if self.experience_required and self.years_short > EXPERIENCE_GRACE_YEARS:
            return False
        return len(self.skill_matches) > 0


def score_match(candidate: CandidateProfile, job: JobProfile, credit: TermCredit) -> MatchResult:
    skills = compare_terms(candidate.skills, job.required_skills, "skill", credit)
    experience_score = experience_fit(candidate.experience_years, job.min_experience_years)

    if job.culture_keywords:
        culture = compare_terms(candidate.traits, job.culture_keywords, "trait", credit)
        weighted = SKILL_WEIGHT * skills.score + EXPERIENCE_WEIGHT * experience_score + CULTURE_WEIGHT * culture.score
    else:
        # Missing culture data neither helps nor hurts: rescale the other two weights.
        culture = None
        weighted = (SKILL_WEIGHT * skills.score + EXPERIENCE_WEIGHT * experience_score) / (
            SKILL_WEIGHT + EXPERIENCE_WEIGHT
        )

    return MatchResult(
        job_id=job.job_id,
        candidate_id=candidate.candidate_id,
        score=round(100 * weighted, 1),
        skill_score=round(skills.score, 3),
        experience_score=round(experience_score, 3),
        culture_score=None if culture is None else round(culture.score, 3),
        skill_matches=skills.matches,
        matched_skills=skills.matched_terms,
        missing_skills=skills.missing_terms,
        matched_culture=[] if culture is None else culture.matched_terms,
        missing_culture=[] if culture is None else culture.missing_terms,
        reason=build_reason(candidate, job, skills, culture),
        meets_minimum_experience=candidate.experience_years >= job.min_experience_years,
        years_short=max(0, job.min_experience_years - candidate.experience_years),
        experience_required=job.experience_requirement == "required",
    )


def build_reason(
    candidate: CandidateProfile, job: JobProfile, skills: TermComparison, culture: TermComparison | None,
) -> str:
    """'2.5/3 skills (crisis-management, negotiation ≈ persuasion ½) · missing strategy · 6y vs 4y min · culture 1/2 (decisive)'"""
    parts = [_coverage(skills, len(job.required_skills), "skills")]
    if skills.missing_terms:
        parts.append(f"missing {', '.join(skills.missing_terms)}")
    experience = f"{candidate.experience_years}y vs {job.min_experience_years}y min"
    years_short = job.min_experience_years - candidate.experience_years
    if years_short > 0:
        experience += f" ({years_short}y short)"
    parts.append(experience)
    if culture is not None:
        parts.append(_coverage(culture, len(job.culture_keywords), "culture", noun_first=True))
    return " · ".join(parts)


def _coverage(comparison: TermComparison, required_count: int, noun: str, noun_first: bool = False) -> str:
    earned = f"{sum(match.credit.value for match in comparison.matches):g}"
    text = f"{noun} {earned}/{required_count}" if noun_first else f"{earned}/{required_count} {noun}"
    if comparison.matches:
        text += f" ({', '.join(_describe(match) for match in comparison.matches)})"
    return text


def _describe(match: TermMatch) -> str:
    """Names where indirect credit came from, so the reason can be checked."""
    if match.credit.kind == "synonym":
        return f"{match.required_term} = {match.candidate_term}"
    if match.credit.kind == "related":
        half = "½" if match.credit.value == 0.5 else f"{match.credit.value:g}"
        return f"{match.required_term} ≈ {match.candidate_term} {half}"
    return match.required_term
