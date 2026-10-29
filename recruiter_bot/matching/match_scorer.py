from dataclasses import dataclass

from recruiter_bot.matching.experience_matcher import experience_fit
from recruiter_bot.matching.profile_reader import CandidateProfile, JobProfile
from recruiter_bot.matching.term_credit import TermCredit
from recruiter_bot.matching.term_matcher import TermComparison, TermMatch, compare_terms

# Experience and culture keep their original weights; skills hold availability's share until it's scored.
SKILL_WEIGHT = 0.7
EXPERIENCE_WEIGHT = 0.2
CULTURE_WEIGHT = 0.1

# Tiers for a qualifying match. 50 itself counts as a match.
STRONG_MATCH_SCORE = 70.0
MATCH_SCORE = 50.0

# Bump when the formula, weights or credit rules change, so stored scores are recomputed.
ALGORITHM_VERSION = "6"


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
    job_title: str
    candidate_id: int
    candidate_name: str
    score: float
    skill_score: float
    experience_score: float
    culture_score: float | None  # None when the job lists no culture keywords
    skill_matches: list[TermMatch]
    culture_matches: list[TermMatch]
    matched_skills: list[str]
    missing_skills: list[str]
    matched_culture: list[str]
    missing_culture: list[str]
    reason: str
    meets_minimum_experience: bool = True   # the candidate has at least the job's minimum years
    experience_required: bool = False       # the job made the minimum a hard requirement

    @property
    def qualifies(self) -> bool:
        """At least one skill must match through the taxonomy itself."""
        if self.experience_required and not self.meets_minimum_experience:
            return False  # The job owner made the minimum a hard requirement
        return any(match.credit.kind != "suggested" for match in self.skill_matches)

    @property
    def tier(self) -> str:
        """How strong a qualifying match is. Only meaningful when qualifies is true."""
        return tier_for(self.score, self.meets_minimum_experience)


def score_match(candidate: CandidateProfile, job: JobProfile, credit: TermCredit) -> MatchResult:
    """The fit between one candidate and one job. Pure and direction-free."""
    skills = compare_terms(candidate.skills, job.required_skills, "skill", credit)
    experience_score = experience_fit(candidate.experience_years, job.min_experience_years)

    if job.culture_keywords:
        culture = compare_terms(candidate.traits, job.culture_keywords, "trait", credit)
        weighted_score = SKILL_WEIGHT * skills.score + EXPERIENCE_WEIGHT * experience_score + CULTURE_WEIGHT * culture.score
        culture_score = round(culture.score, 3)
        culture_matches = culture.matches
    else:
        # Missing culture data neither helps nor hurts: rescale the other two weights.
        weighted_score = (SKILL_WEIGHT * skills.score + EXPERIENCE_WEIGHT * experience_score) / (
            SKILL_WEIGHT + EXPERIENCE_WEIGHT
        )
        culture = None
        culture_score = None
        culture_matches = []

    return MatchResult(
        job_id=job.job_id,
        job_title=job.title,
        candidate_id=candidate.candidate_id,
        candidate_name=candidate.full_name,
        score=round(100 * weighted_score, 1),
        skill_score=round(skills.score, 3),
        experience_score=round(experience_score, 3),
        culture_score=culture_score,
        skill_matches=skills.matches,
        culture_matches=culture_matches,
        matched_skills=skills.matched_terms,
        missing_skills=skills.missing_terms,
        matched_culture=culture.matched_terms if culture is not None else [],
        missing_culture=culture.missing_terms if culture is not None else [],
        reason=build_reason(candidate, job, skills, culture),
        meets_minimum_experience=candidate.experience_years >= job.min_experience_years,
        experience_required=job.experience_requirement == "required",
    )


def build_reason(
    candidate: CandidateProfile, job: JobProfile, skills: TermComparison, culture: TermComparison | None
) -> str:
    """'2.5/3 skills (crisis-management, negotiation ≈ persuasion ½) · missing strategy · 6y vs 4y min · culture 1/2 (decisive)'"""
    parts = [_coverage(skills, len(job.required_skills), "skills")]
    if skills.missing_terms:
        parts.append(f"missing {', '.join(skills.missing_terms)}")
    parts.append(f"{candidate.experience_years}y vs {job.min_experience_years}y min")
    if culture is not None:
        parts.append(_coverage(culture, len(job.culture_keywords), "culture", noun_first=True))
    return " · ".join(parts)


def _coverage(comparison: TermComparison, required_count: int, noun: str, noun_first: bool = False) -> str:
    earned = _number(sum(match.credit.value for match in comparison.matches))
    text = f"{noun} {earned}/{required_count}" if noun_first else f"{earned}/{required_count} {noun}"
    if comparison.matches:
        text += f" ({', '.join(_describe(match) for match in comparison.matches)})"
    return text


def _describe(match: TermMatch) -> str:
    """Names where partial or indirect credit came from, so the reason can be checked."""
    if match.credit.kind == "synonym":
        return f"{match.required_term} = {match.candidate_term}"
    if match.credit.kind == "related":
        return f"{match.required_term} ≈ {match.candidate_term} {_fraction(match.credit.value)}"
    if match.credit.kind == "suggested":
        return f"{match.required_term} ≈ {match.candidate_term} (suggested {_fraction(match.credit.value)})"
    return match.required_term


def _fraction(value: float) -> str:
    if value == 0.5:
        return "½"
    if value == 0.25:
        return "¼"
    return _number(value)


def _number(value: float) -> str:
    return f"{value:g}"
