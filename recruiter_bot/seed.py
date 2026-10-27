"""Loads seed/*.json into the database. Usage: python -m recruiter_bot.seed"""
import sys
from datetime import date
from pathlib import Path

from recruiter_bot.db import connect
from recruiter_bot.ingest import (
    build_candidate_batch,
    build_job_batch,
    extract_candidates,
    extract_jobs,
    insert_batch,
    log_rejected,
    read_json_records,
)

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"


def run(today: date | None = None) -> None:
    with connect() as conn:
        # The database clock is the single source of "today", so availability
        # dates don't shift with the timezone of whoever runs the seed.
        if today is None:
            today = conn.execute("SELECT current_date").fetchone()[0]
            conn.commit()

        candidate_extraction = extract_candidates(read_json_records(SEED_DIR / "candidate_data.json"), today)
        job_extraction = extract_jobs(read_json_records(SEED_DIR / "job_data.json"))

        log_rejected(conn, "candidate", "seed", candidate_extraction.rejected)
        log_rejected(conn, "job", "seed", job_extraction.rejected)
        _print_rejections("candidate", candidate_extraction.rejected)
        _print_rejections("job", job_extraction.rejected)

        candidate_batch = build_candidate_batch(candidate_extraction.records)
        job_batch = build_job_batch(job_extraction.records)
        result = insert_batch(conn, candidate_batch, job_batch, source="seed")

    print(
        f"Seeded {result.candidates} candidates, {result.jobs} jobs, "
        f"{result.skills} skills, {result.traits} traits "
        f"({len(candidate_extraction.rejected)} candidate and {len(job_extraction.rejected)} job records rejected)."
    )


def _print_rejections(entity_type: str, rejected: list) -> None:
    for error in rejected:
        print(f"rejected {entity_type} #{error.index}: {error.message}", file=sys.stderr)


if __name__ == "__main__":
    run()
