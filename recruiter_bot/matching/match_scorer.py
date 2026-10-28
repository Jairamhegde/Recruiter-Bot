from dataclasses import dataclass

from recruiter_bot.matching.experience_matcher import experience_fit
from recruiter_bot.matching.profile_reader import CandidateProfile, JobProfile
from recruiter_bot.matching.term_credit import TermCredit
from recruiter_bot.matching.term_matcher import TermComparison, TermMatch, compare_terms

# D-32: experience and culture keep their D-11 weights; skills hold availability's share until it's scored.
SKILL_WEIGHT = 0.7
EXPERIENCE_WEIGHT = 0.2
CULTURE_WEIGHT = 0.1

# D-34: tiers for a qualifying match. 50 itself counts as a match (D-17).
STRONG_MATCH_SCORE = 70.0
MATCH_SCORE = 50.0

# D-37: bump whenever the formula, weights or credit rules change, so stored scores are recomputed.
ALGORITHM_VERSION = "2"


def tier_for(score: float) -> str:
    """How strong a qualifying match is (D-34). Worked out at read time, never stored."""
    if score >= STRONG_MATCH_SCORE:
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
    reason: str

    @property
    def qualifies(self) -> bool:
        """No skill credit means no match (D-12): experience and culture can't create one."""
        return self.skill_score > 0

    @property
    def tier(self) -> str:
        """How strong a qualifying match is (D-34). Only meaningful when qualifies is true."""
        return tier_for(self.score)


def score_match(candidate: CandidateProfile, job: JobProfile, credit: TermCredit) -> MatchResult:
    """The fit between one candidate and one job. Pure and direction-free (D-32)."""
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
        reason=build_reason(candidate, job, skills, culture),
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
    return match.required_term


def _fraction(value: float) -> str:
    return "½" if value == 0.5 else _number(value)


def _number(value: float) -> str:
    return f"{value:g}"
