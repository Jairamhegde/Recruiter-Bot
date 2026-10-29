"""The Recruiter Bot API. Run it with: uvicorn recruiter_bot.api.main:app --reload"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from recruiter_bot.api import candidates, jobs

# The address to open in a browser; uvicorn's own "0.0.0.0" line can't be opened.
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://127.0.0.1:8000")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.getLogger("uvicorn.error").info("Recruiter Bot is ready: open %s/docs in your browser", PUBLIC_URL)
    yield


app = FastAPI(
    title="Recruiter Bot",
    description="Matches candidates and jobs, with a score and a reason.",
    lifespan=lifespan,
)
app.include_router(jobs.router)
app.include_router(candidates.router)
