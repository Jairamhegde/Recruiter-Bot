from typing import Literal

from pydantic import BaseModel, Field

from recruiter_bot.matching import CandidateProfile, JobProfile, StoredMatch
from recruiter_bot.matching.recruiter_view import open_candidates, proactive_offers, shown_matches


class CandidateSummary(BaseModel):
    candidate_id: int
    name: str
    experience_years: int
    skills: list[str]
    traits: list[str]
    job_preferences: list[str]  # stored, not yet used in matching (D-47)

    @classmethod
    def from_profile(cls, profile: CandidateProfile) -> "CandidateSummary":
        return cls(
            candidate_id=profile.candidate_id,
            name=profile.full_name,
            experience_years=profile.experience_years,
            skills=profile.skills,
            traits=profile.traits,
            job_preferences=profile.job_preferences,
        )


class JobSummary(BaseModel):
    job_id: int
    title: str
    min_experience_years: int
    required_skills: list[str]
    culture_keywords: list[str]

    @classmethod
    def from_profile(cls, profile: JobProfile) -> "JobSummary":
        return cls(
            job_id=profile.job_id,
            title=profile.title,
            min_experience_years=profile.min_experience_years,
            required_skills=profile.required_skills,
            culture_keywords=profile.culture_keywords,
        )


class JobMatch(BaseModel):
    job_id: int
    job_title: str
    score: float
    skill_score: float
    experience_score: float
    culture_score: float | None
    matched_skills: list[str]
    missing_skills: list[str]
    reason: str
    tagline: str | None  # shown to the candidate, never scored (D-06)

    @classmethod
    def from_result(cls, result: StoredMatch) -> "JobMatch":
        return cls(
            job_id=result.job_id,
            job_title=result.job_title,
            score=result.score,
            skill_score=result.skill_score,
            experience_score=result.experience_score,
            culture_score=result.culture_score,
            matched_skills=result.matched_skills,
            missing_skills=result.missing_skills,
            reason=result.reason,
            tagline=result.job_tagline,
        )


class CandidateMatch(BaseModel):
    candidate_id: int
    candidate_name: str
    score: float
    skill_score: float
    experience_score: float
    culture_score: float | None
    matched_skills: list[str]
    missing_skills: list[str]
    reason: str
    quirk: str | None  # shown to the recruiter, never scored (D-06)

    @classmethod
    def from_result(cls, result: StoredMatch) -> "CandidateMatch":
        return cls(
            candidate_id=result.candidate_id,
            candidate_name=result.candidate_name,
            score=result.score,
            skill_score=result.skill_score,
            experience_score=result.experience_score,
            culture_score=result.culture_score,
            matched_skills=result.matched_skills,
            missing_skills=result.missing_skills,
            reason=result.reason,
            quirk=result.candidate_quirk,
        )


class JobMatchesByTier(BaseModel):
    """The three tiers of D-34, each best first. A tier with no matches is an empty list.
    Near misses appear only when there is no strong or possible match (D-17, D-49)."""
    strong_match: list[JobMatch] = Field(default_factory=list)
    possible_match: list[JobMatch] = Field(default_factory=list)
    near_miss: list[JobMatch] = Field(default_factory=list)
    near_misses_included: bool = False

    @classmethod
    def from_results(cls, results: list[StoredMatch]) -> "JobMatchesByTier":
        shown, near_misses_included = shown_matches(results)
        groups = cls(near_misses_included=near_misses_included)
        # Results arrive sorted, so each tier stays best first.
        for result in shown:
            getattr(groups, result.tier).append(JobMatch.from_result(result))
        return groups


class CandidateMatchesByTier(BaseModel):
    """The three tiers of D-34, each best first. A tier with no matches is an empty list.
    Near misses appear only when there is no strong or possible match (D-17, D-49)."""
    strong_match: list[CandidateMatch] = Field(default_factory=list)
    possible_match: list[CandidateMatch] = Field(default_factory=list)
    near_miss: list[CandidateMatch] = Field(default_factory=list)
    near_misses_included: bool = False

    @classmethod
    def from_results(cls, results: list[StoredMatch]) -> "CandidateMatchesByTier":
        shown, near_misses_included = shown_matches(results)
        groups = cls(near_misses_included=near_misses_included)
        for result in shown:
            getattr(groups, result.tier).append(CandidateMatch.from_result(result))
        return groups


class ProactiveOffer(CandidateMatch):
    """A candidate who isn't looking, but beats everyone who is (D-49)."""
    tier: str
    recommended_action: Literal["proactive-offer"] = "proactive-offer"

    @classmethod
    def from_result(cls, result: StoredMatch) -> "ProactiveOffer":
        candidate = CandidateMatch.from_result(result)
        return cls(**candidate.model_dump(), tier=result.tier)


class CandidateMatches(BaseModel):
    candidate_id: int
    matches: JobMatchesByTier


class JobMatches(BaseModel):
    """The recruiter's view of one job (D-49):
    - matches: candidates open to opportunities, who can be hired now;
    - proactive_offers: candidates not looking who score higher than the best open candidate."""
    job_id: int
    matches: CandidateMatchesByTier
    proactive_offers: list[ProactiveOffer]

    @classmethod
    def from_results(cls, job_id: int, results: list[StoredMatch]) -> "JobMatches":
        return cls(
            job_id=job_id,
            matches=CandidateMatchesByTier.from_results(open_candidates(results)),
            proactive_offers=[ProactiveOffer.from_result(result) for result in proactive_offers(results)],
        )
