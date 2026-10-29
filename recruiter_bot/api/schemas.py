from typing import Literal

from pydantic import BaseModel, Field, model_serializer

from recruiter_bot.matching import CandidateProfile, JobProfile, StoredMatch
from recruiter_bot.matching.candidate_view import Standing, order_for_candidate
from recruiter_bot.matching.evidence import evidence_for
from recruiter_bot.matching.recruiter_view import open_candidates, proactive_offers, shown_matches


class CandidateSummary(BaseModel):
    candidate_id: int
    name: str             # names may repeat; candidate_id and email tell people apart
    email: str | None
    experience_years: int
    skills: list[str]
    traits: list[str]
    job_preferences: list[str]  # stored, not yet used in matching

    @classmethod
    def from_profile(cls, profile: CandidateProfile) -> "CandidateSummary":
        return cls(
            candidate_id=profile.candidate_id,
            name=profile.full_name,
            email=profile.email,
            experience_years=profile.experience_years,
            skills=profile.skills,
            traits=profile.traits,
            job_preferences=profile.job_preferences,
        )


class JobSummary(BaseModel):
    job_id: int
    title: str
    company: str | None   # a title is unique within a company
    min_experience_years: int
    experience_requirement: str  # "required" or "preferred"
    required_skills: list[str]
    culture_keywords: list[str]

    @classmethod
    def from_profile(cls, profile: JobProfile) -> "JobSummary":
        return cls(
            job_id=profile.job_id,
            title=profile.title,
            company=profile.company,
            min_experience_years=profile.min_experience_years,
            experience_requirement=profile.experience_requirement,
            required_skills=profile.required_skills,
            culture_keywords=profile.culture_keywords,
        )


class TermEvidence(BaseModel):
    """What matched and what didn't, for skills or culture keywords."""
    matched: list[str]
    missing: list[str]


class ExperienceEvidence(BaseModel):
    """Experience has no list of terms, so it gets one sentence."""
    detail: str  # e.g. "11 years, meets the 3-year minimum"


class MatchEvidenceOut(BaseModel):
    """The default evidence: only what matched and what didn't. The score is shown separately."""
    skills: TermEvidence
    experience: ExperienceEvidence
    culture: TermEvidence | None  # None when the job lists no culture keywords

    @classmethod
    def from_result(cls, result: StoredMatch) -> "MatchEvidenceOut":
        evidence = evidence_for(result)
        culture = evidence.culture
        return cls(
            skills=TermEvidence(matched=evidence.skills.matched, missing=evidence.skills.missing),
            experience=ExperienceEvidence(detail=evidence.experience.detail),
            culture=None if culture is None else TermEvidence(matched=culture.matched, missing=culture.missing),
        )


class FactorBreakdown(BaseModel):
    score: float          # 0 to 1
    weight: float         # its share of the total
    points: float         # 100 x weight x score: what this factor adds to the total score
    detail: str           # the same fact in words, e.g. "2 of 3 required skills"
    matched: list[str]
    missing: list[str]


class ScoreBreakdown(BaseModel):
    """Only with ?explain=true: how the score is built. The points add up to the score."""
    skills: FactorBreakdown
    experience: FactorBreakdown
    culture: FactorBreakdown | None  # None when the job lists no culture keywords

    @classmethod
    def from_result(cls, result: StoredMatch) -> "ScoreBreakdown":
        evidence = evidence_for(result)

        def factor(part) -> FactorBreakdown:
            return FactorBreakdown(score=part.score, weight=part.weight, points=part.points,
                                   detail=part.detail, matched=part.matched, missing=part.missing)

        return cls(
            skills=factor(evidence.skills),
            experience=factor(evidence.experience),
            culture=None if evidence.culture is None else factor(evidence.culture),
        )


class OmitsEmptyBreakdown(BaseModel):
    """A match entry whose score_breakdown is left out of the response, not sent as null, unless requested."""

    @model_serializer(mode="wrap")
    def _leave_out_breakdown_unless_requested(self, handler):
        data = handler(self)
        if data.get("score_breakdown") is None:
            data.pop("score_breakdown", None)
        return data


class JobMatch(OmitsEmptyBreakdown):
    rank: int             # 1 is the best job shown to this candidate
    job_id: int
    job_title: str
    company: str | None
    score: float
    reason: str
    evidence: MatchEvidenceOut
    score_breakdown: ScoreBreakdown | None = None  # only with ?explain=true
    meets_minimum_experience: bool  # false: the candidate is below the job's minimum years
    tagline: str | None   # shown to the candidate, never scored
    # A yes or no only, so other candidates' scores stay private.
    top_applicant: bool       # no open rival with a strong or possible match scores higher; orders tied jobs
    matches_preference: bool  # the job's title is one of the candidate's job_preferences

    @classmethod
    def from_result(
        cls, result: StoredMatch, rank: int, standing: Standing, preferences: set[str], explain: bool,
    ) -> "JobMatch":
        return cls(
            rank=rank,
            job_id=result.job_id,
            job_title=result.job_title,
            company=result.job_company,
            score=result.score,
            reason=result.reason,
            evidence=MatchEvidenceOut.from_result(result),
            score_breakdown=ScoreBreakdown.from_result(result) if explain else None,
            meets_minimum_experience=result.meets_minimum_experience,
            tagline=result.job_tagline,
            top_applicant=standing.is_top_applicant,
            matches_preference=standing.job_slug in preferences,
        )


class CandidateMatch(OmitsEmptyBreakdown):
    rank: int             # 1 is the best candidate shown in this section
    candidate_id: int
    candidate_name: str
    score: float
    reason: str
    evidence: MatchEvidenceOut
    score_breakdown: ScoreBreakdown | None = None  # only with ?explain=true
    meets_minimum_experience: bool  # false: the candidate is below the job's minimum years
    quirk: str | None     # shown to the recruiter, never scored

    @classmethod
    def from_result(cls, result: StoredMatch, rank: int, explain: bool) -> "CandidateMatch":
        return cls(
            rank=rank,
            candidate_id=result.candidate_id,
            candidate_name=result.candidate_name,
            score=result.score,
            reason=result.reason,
            evidence=MatchEvidenceOut.from_result(result),
            score_breakdown=ScoreBreakdown.from_result(result) if explain else None,
            meets_minimum_experience=result.meets_minimum_experience,
            quirk=result.candidate_quirk,
        )


class JobMatchesByTier(BaseModel):
    """The three tiers, best first; near misses only when nothing better exists."""
    strong_match: list[JobMatch] = Field(default_factory=list)
    possible_match: list[JobMatch] = Field(default_factory=list)
    near_miss: list[JobMatch] = Field(default_factory=list)
    near_misses_included: bool = False

    @classmethod
    def from_results(
        cls, results: list[StoredMatch], standings: dict[int, Standing], preferences: set[str], explain: bool,
    ) -> "JobMatchesByTier":
        """Results must already be in the candidate's order, so the rank is simply the position."""
        shown, near_misses_included = shown_matches(results)
        groups = cls(near_misses_included=near_misses_included)
        for rank, result in enumerate(shown, start=1):
            job = JobMatch.from_result(result, rank, standings[result.job_id], preferences, explain)
            getattr(groups, result.tier).append(job)
        return groups


class CandidateMatchesByTier(BaseModel):
    """The three tiers, best first; near misses only when nothing better exists."""
    strong_match: list[CandidateMatch] = Field(default_factory=list)
    possible_match: list[CandidateMatch] = Field(default_factory=list)
    near_miss: list[CandidateMatch] = Field(default_factory=list)
    near_misses_included: bool = False

    @classmethod
    def from_results(cls, results: list[StoredMatch], explain: bool) -> "CandidateMatchesByTier":
        shown, near_misses_included = shown_matches(results)
        groups = cls(near_misses_included=near_misses_included)
        for rank, result in enumerate(shown, start=1):
            getattr(groups, result.tier).append(CandidateMatch.from_result(result, rank, explain))
        return groups


class ProactiveOffer(CandidateMatch):
    """A candidate who isn't looking, but beats everyone who is. Ranked within the offers."""
    tier: str
    recommended_action: Literal["proactive-offer"] = "proactive-offer"

    @classmethod
    def from_result(cls, result: StoredMatch, rank: int, explain: bool) -> "ProactiveOffer":
        candidate = CandidateMatch.from_result(result, rank, explain)
        return cls(**candidate.model_dump(), tier=result.tier)


class CandidateMatches(BaseModel):
    """The candidate's view: jobs ordered by score, top applicant, posting date."""
    candidate_id: int
    matches: JobMatchesByTier

    @classmethod
    def from_results(
        cls, candidate_id: int, results: list[StoredMatch], standings: dict[int, Standing],
        preferences: set[str], explain: bool = False,
    ) -> "CandidateMatches":
        ordered = order_for_candidate(results, standings)
        matches = JobMatchesByTier.from_results(ordered, standings, preferences, explain)
        return cls(candidate_id=candidate_id, matches=matches)


class JobMatches(BaseModel):
    """The recruiter's view of one job: open candidates, plus proactive offers."""
    job_id: int
    matches: CandidateMatchesByTier
    proactive_offers_included: bool
    proactive_offers: list[ProactiveOffer]

    @classmethod
    def from_results(cls, job_id: int, results: list[StoredMatch], explain: bool = False) -> "JobMatches":
        offers = [
            ProactiveOffer.from_result(result, rank, explain)
            for rank, result in enumerate(proactive_offers(results), start=1)
        ]
        return cls(
            job_id=job_id,
            matches=CandidateMatchesByTier.from_results(open_candidates(results), explain),
            proactive_offers_included=len(offers) > 0,
            proactive_offers=offers,
        )
