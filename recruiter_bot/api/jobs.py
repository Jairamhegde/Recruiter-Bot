from fastapi import APIRouter, HTTPException, Query, status

from recruiter_bot.api.schemas import JobMatches, JobSummary
from recruiter_bot.db import connect
from recruiter_bot.ingest import JobInput, JobPatch, insert_job, update_job
from recruiter_bot.matching.store import load_job_profiles, refresh_matches, stored_matches_for_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobSummary])
def list_jobs() -> list[JobSummary]:
    """Every job with its id, sorted by id, so a client can find the id to match."""
    with connect() as conn:
        profiles = load_job_profiles(conn)
    return [JobSummary.from_profile(profile) for profile in profiles]


@router.post("", response_model=JobMatches, status_code=status.HTTP_201_CREATED)
def create_job(job: JobInput) -> JobMatches:
    """Stores a new job opening and returns its matching candidates, grouped by tier."""
    with connect() as conn:
        # One transaction, so the job never appears without its matches.
        with conn.transaction():
            job_id = insert_job(conn, job)
            refresh_matches(conn, job_id=job_id)
        results = stored_matches_for_job(conn, job_id)
    return JobMatches.from_results(job_id, results)


@router.patch("/{job_id}", response_model=JobMatches)
def patch_job(job_id: int, patch: JobPatch) -> JobMatches:
    """Changes only the fields sent, then returns the job's refreshed matches."""
    with connect() as conn:
        with conn.transaction():
            if not update_job(conn, job_id, patch):
                raise HTTPException(status_code=404, detail=f"No job with id {job_id}")
            refresh_matches(conn, job_id=job_id)
        results = stored_matches_for_job(conn, job_id)
    return JobMatches.from_results(job_id, results)


@router.get("/{job_id}/matches", response_model=JobMatches)
def job_matches(
    job_id: int,
    explain: bool = Query(False, description="Add the score, weight and points of each factor to every match."),
) -> JobMatches:
    """Open candidates grouped by tier, then candidates not looking who are worth a proactive offer."""
    with connect() as conn:
        results = stored_matches_for_job(conn, job_id)

    if results is None:
        raise HTTPException(status_code=404, detail=f"No job with id {job_id}")
    return JobMatches.from_results(job_id, results, explain)
