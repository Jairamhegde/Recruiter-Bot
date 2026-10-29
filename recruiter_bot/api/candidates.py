from fastapi import APIRouter, HTTPException, Query, status

from recruiter_bot.api.schemas import CandidateMatches, CandidateSummary
from recruiter_bot.db import connect
from recruiter_bot.ingest import CandidateInput, CandidatePatch, insert_candidate, update_candidate
from recruiter_bot.matching.store import load_candidate_profiles, refresh_matches, stored_matches_for_candidate
from recruiter_bot.matching.views import standings_for_candidate

router = APIRouter(prefix="/candidates", tags=["candidates"])


def matches_for(conn, candidate_id: int, explain: bool = False) -> CandidateMatches | None:
    """The candidate's jobs in ranked order, or None if the candidate doesn't exist."""
    results = stored_matches_for_candidate(conn, candidate_id)
    if results is None:
        return None
    return CandidateMatches.from_results(candidate_id, results, standings_for_candidate(conn, candidate_id), explain)


@router.get("", response_model=list[CandidateSummary])
def list_candidates() -> list[CandidateSummary]:
    """Every candidate with its id, sorted by id, so a client can find the id to match."""
    with connect() as conn:
        profiles = load_candidate_profiles(conn)
    return [CandidateSummary.from_profile(profile) for profile in profiles]


@router.post("", response_model=CandidateMatches, status_code=status.HTTP_201_CREATED)
def create_candidate(candidate: CandidateInput) -> CandidateMatches:
    """Stores a new candidate profile and returns their matching jobs, grouped by tier."""
    with connect() as conn:
        # One transaction, so the candidate never appears without their matches.
        with conn.transaction():
            candidate_id = insert_candidate(conn, candidate)
            refresh_matches(conn, candidate_id=candidate_id)
        return matches_for(conn, candidate_id)


@router.patch("/{candidate_id}", response_model=CandidateMatches)
def patch_candidate(candidate_id: int, patch: CandidatePatch) -> CandidateMatches:
    """Changes only the fields sent, then returns the candidate's refreshed matches."""
    with connect() as conn:
        with conn.transaction():
            if not update_candidate(conn, candidate_id, patch):
                raise HTTPException(status_code=404, detail=f"No candidate with id {candidate_id}")
            refresh_matches(conn, candidate_id=candidate_id)
        return matches_for(conn, candidate_id)


@router.get("/{candidate_id}/matches", response_model=CandidateMatches)
def candidate_matches(
    candidate_id: int,
    explain: bool = Query(False, description="Add the score, weight and points of each factor to every match."),
) -> CandidateMatches:
    """The candidate's jobs by tier: score first, then top applicant and posting date."""
    with connect() as conn:
        response = matches_for(conn, candidate_id, explain)

    if response is None:
        raise HTTPException(status_code=404, detail=f"No candidate with id {candidate_id}")
    return response
