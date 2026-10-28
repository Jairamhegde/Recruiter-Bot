from pydantic import BaseModel, Field

from recruiter_bot.matching import CandidateProfile, JobProfile, MatchResult, StoredMatch


class CandidateSummary(BaseModel):
    candidate_id: int
    name: str
    experience_years: int
    skills: list[str]
    traits: list[str]

    @classmethod
    def from_profile(cls, profile: CandidateProfile) -> "CandidateSummary":
        return cls(
            candidate_id=profile.candidate_id,
            name=profile.full_name,
            experience_years=profile.experience_years,
            skills=profile.skills,
            traits=profile.traits,
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

    @classmethod
    def from_result(cls, result: MatchResult | StoredMatch) -> "JobMatch":
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

    @classmethod
    def from_result(cls, result: MatchResult | StoredMatch) -> "CandidateMatch":
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
        )


class JobMatchesByTier(BaseModel):
    """The three tiers of D-34, each best first. A tier with no matches is an empty list."""
    strong_match: list[JobMatch] = Field(default_factory=list)
    possible_match: list[JobMatch] = Field(default_factory=list)
    near_miss: list[JobMatch] = Field(default_factory=list)

    @classmethod
    def from_results(cls, results: list[MatchResult] | list[StoredMatch]) -> "JobMatchesByTier":
        groups = cls()
        # Results arrive sorted, so each tier stays best first.
        for result in results:
            getattr(groups, result.tier).append(JobMatch.from_result(result))
        return groups


class CandidateMatchesByTier(BaseModel):
    """The three tiers of D-34, each best first. A tier with no matches is an empty list."""
    strong_match: list[CandidateMatch] = Field(default_factory=list)
    possible_match: list[CandidateMatch] = Field(default_factory=list)
    near_miss: list[CandidateMatch] = Field(default_factory=list)

    @classmethod
    def from_results(cls, results: list[MatchResult] | list[StoredMatch]) -> "CandidateMatchesByTier":
        groups = cls()
        for result in results:
            getattr(groups, result.tier).append(CandidateMatch.from_result(result))
        return groups


class CandidateMatches(BaseModel):
    candidate_id: int
    matches: JobMatchesByTier


class JobMatches(BaseModel):
    job_id: int
    matches: CandidateMatchesByTier
