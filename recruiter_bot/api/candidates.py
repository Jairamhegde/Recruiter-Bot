from fastapi import APIRouter, HTTPException, Query, status

from recruiter_bot.api.schemas import CandidateMatches, CandidateSummary
from recruiter_bot.db import connect
from recruiter_bot.ingest.candidates.candidate_creator import CandidateExists, CandidateRejected, add_candidate
from recruiter_bot.ingest.candidates.candidate_extractor import CandidateInput
from recruiter_bot.ingest.candidates.candidate_updater import CandidateNotFound, CandidatePatch, update_candidate
from recruiter_bot.matching import stored_matches_for_candidate
from recruiter_bot.matching.candidate_view import preferences_of, standings_for_candidate
from recruiter_bot.matching.profile_reader import load_candidate_profiles

router = APIRouter(prefix="/candidates", tags=["candidates"])


def matches_for(conn, candidate_id: int, explain: bool = False) -> CandidateMatches | None:
    """The candidate's jobs in ranked order, or None if the candidate doesn't exist."""
    results = stored_matches_for_candidate(conn, candidate_id)
    if results is None:
        return None
    standings = standings_for_candidate(conn, candidate_id)
    preferences = preferences_of(conn, candidate_id)
    return CandidateMatches.from_results(candidate_id, results, standings, preferences, explain)


@router.get("", response_model=list[CandidateSummary])
def list_candidates() -> list[CandidateSummary]:
    """Every candidate with its id, sorted by id, so a client can find the id to match."""
    with connect() as conn:
        profiles = load_candidate_profiles(conn)
    return [CandidateSummary.from_profile(profile) for profile in profiles]


@router.post("", response_model=CandidateMatches, status_code=status.HTTP_201_CREATED)
def create_candidate(candidate: CandidateInput) -> CandidateMatches:
    """Stores a new candidate profile and returns its matching jobs, grouped by tier."""
    with connect() as conn:
        try:
            candidate_id = add_candidate(conn, candidate.model_dump())
        except CandidateExists as error:
            raise HTTPException(status_code=409, detail=str(error))
        except CandidateRejected as error:
            raise HTTPException(status_code=422, detail=str(error))
        response = matches_for(conn, candidate_id)
    return response


@router.patch("/{candidate_id}", response_model=CandidateMatches)
def patch_candidate(candidate_id: int, patch: CandidatePatch) -> CandidateMatches:
    """Changes only the fields sent, then returns the candidate's refreshed matches."""
    with connect() as conn:
        try:
            update_candidate(conn, candidate_id, patch)
        except CandidateNotFound as error:
            raise HTTPException(status_code=404, detail=str(error))
        except CandidateExists as error:
            raise HTTPException(status_code=409, detail=str(error))
        except CandidateRejected as error:
            raise HTTPException(status_code=422, detail=str(error))
        response = matches_for(conn, candidate_id)
    return response


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
