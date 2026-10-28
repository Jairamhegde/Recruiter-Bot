from pydantic import BaseModel, Field

from recruiter_bot.matching import MatchResult


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
    def from_result(cls, result: MatchResult) -> "JobMatch":
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


class JobMatchesByTier(BaseModel):
    """The three tiers of D-34, each best first. A tier with no matches is an empty list."""
    strong_match: list[JobMatch] = Field(default_factory=list)
    possible_match: list[JobMatch] = Field(default_factory=list)
    near_miss: list[JobMatch] = Field(default_factory=list)

    @classmethod
    def from_results(cls, results: list[MatchResult]) -> "JobMatchesByTier":
        groups = cls()
        # Results arrive sorted, so each tier stays best first.
        for result in results:
            getattr(groups, result.tier).append(JobMatch.from_result(result))
        return groups


class CandidateMatches(BaseModel):
    candidate_id: int
    matches: JobMatchesByTier
