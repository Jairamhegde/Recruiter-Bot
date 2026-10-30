"""The Recruiter Bot API. Run it with: uvicorn recruiter_bot.api.main:app --reload"""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from recruiter_bot.api import candidates, jobs

# The address to open in a browser; uvicorn's own "0.0.0.0" line can't be opened.
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://127.0.0.1:8000")

# The demo page: one static file over this same API, so it needs no CORS and no build step.
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.getLogger("uvicorn.error").info("Recruiter Bot is ready: open %s/ui (demo) or %s/docs (API) in your browser", PUBLIC_URL, PUBLIC_URL)
    yield


app = FastAPI(
    title="Recruiter Bot",
    description="Matches candidates and jobs, with a score and a reason.",
    lifespan=lifespan,
)
app.include_router(jobs.router)
app.include_router(candidates.router)

if FRONTEND_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=FRONTEND_DIR, html=True), name="ui")

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/ui/")
