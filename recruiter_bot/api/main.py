"""The Recruiter Bot API. Run it with: uvicorn recruiter_bot.api.main:app --reload"""
from fastapi import FastAPI

from recruiter_bot.api import candidates

app = FastAPI(title="Recruiter Bot", description="Matches candidates and jobs, with a score and a reason.")
app.include_router(candidates.router)
