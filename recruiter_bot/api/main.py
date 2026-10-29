"""The Recruiter Bot API. Run it with: uvicorn recruiter_bot.api.main:app --reload"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from recruiter_bot.api import candidates, jobs, suggestions
from recruiter_bot.db import connect
from recruiter_bot.matching import refresh_if_stale


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Stored matches from another algorithm version are never served (D-37).
    with connect() as conn:
        refresh_if_stale(conn)
    yield


app = FastAPI(
    title="Recruiter Bot",
    description="Matches candidates and jobs, with a score and a reason.",
    lifespan=lifespan,
)
app.include_router(jobs.router)
app.include_router(candidates.router)
app.include_router(suggestions.router)
