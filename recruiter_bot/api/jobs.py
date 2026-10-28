from fastapi import APIRouter, HTTPException, status

from recruiter_bot.api.schemas import CandidateMatchesByTier, JobMatches, JobSummary
from recruiter_bot.db import connect
from recruiter_bot.ingest.jobs.job_creator import JobExists, JobRejected, add_job
from recruiter_bot.ingest.jobs.job_extractor import JobInput
from recruiter_bot.ingest.jobs.job_updater import JobNotFound, JobPatch, update_job
from recruiter_bot.matching import stored_matches_for_job
from recruiter_bot.matching.profile_reader import load_job_profiles

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobSummary])
def list_jobs() -> list[JobSummary]:
    """Every job with its id, sorted by id, so a client can find the id to match (D-36)."""
    with connect() as conn:
        profiles = load_job_profiles(conn)
    return [JobSummary.from_profile(profile) for profile in profiles]


@router.post("", response_model=JobMatches, status_code=status.HTTP_201_CREATED)
def create_job(job: JobInput) -> JobMatches:
    """Stores a new job opening and returns its matching candidates, grouped by tier (D-40)."""
    with connect() as conn:
        try:
            job_id = add_job(conn, job.model_dump())
        except JobExists as error:
            raise HTTPException(status_code=409, detail=str(error))
        except JobRejected as error:
            raise HTTPException(status_code=422, detail=str(error))
        results = stored_matches_for_job(conn, job_id)

    return JobMatches(job_id=job_id, matches=CandidateMatchesByTier.from_results(results))


@router.patch("/{job_id}", response_model=JobMatches)
def patch_job(job_id: int, patch: JobPatch) -> JobMatches:
    """Changes only the fields sent, then returns the job's refreshed matches (D-38)."""
    with connect() as conn:
        try:
            update_job(conn, job_id, patch)
        except JobNotFound as error:
            raise HTTPException(status_code=404, detail=str(error))
        except JobExists as error:
            raise HTTPException(status_code=409, detail=str(error))
        except JobRejected as error:
            raise HTTPException(status_code=422, detail=str(error))
        results = stored_matches_for_job(conn, job_id)

    return JobMatches(job_id=job_id, matches=CandidateMatchesByTier.from_results(results))


@router.get("/{job_id}/matches", response_model=JobMatches)
def job_matches(job_id: int) -> JobMatches:
    """Candidates that match the job, grouped by tier (D-34), each with its score breakdown and reason."""
    with connect() as conn:
        results = stored_matches_for_job(conn, job_id)

    if results is None:
        raise HTTPException(status_code=404, detail=f"No job with id {job_id}")
    return JobMatches(
        job_id=job_id,
        matches=CandidateMatchesByTier.from_results(results),
    )
