from fastapi import APIRouter, HTTPException

from recruiter_bot.api.schemas import CandidateMatches, JobMatchesByTier
from recruiter_bot.db import connect
from recruiter_bot.matching import rank_jobs_for_candidate

router = APIRouter(prefix="/candidates", tags=["candidates"])


@router.get("/{candidate_id}/matches", response_model=CandidateMatches)
def candidate_matches(candidate_id: int) -> CandidateMatches:
    """Jobs that match the candidate, grouped by tier (D-34), each with its score breakdown and reason."""
    with connect() as conn:
        results = rank_jobs_for_candidate(conn, candidate_id)

    if results is None:
        raise HTTPException(status_code=404, detail=f"No candidate with id {candidate_id}")
    return CandidateMatches(
        candidate_id=candidate_id,
        matches=JobMatchesByTier.from_results(results),
    )
