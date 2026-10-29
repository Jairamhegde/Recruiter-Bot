"""Loads seed/*.json into the database, then computes every match. Usage: python -m recruiter_bot.seed

Safe to run again: each seed file is loaded once, like a migration, and recorded in seed_runs.
The taxonomy is reloaded and every match recomputed on every run.
"""
import json
import sys
from pathlib import Path

from pydantic import BaseModel, ValidationError

from recruiter_bot.db import connect
from recruiter_bot.ingest import CandidateInput, JobInput, insert_candidate, insert_job
from recruiter_bot.matching.store import refresh_matches
from recruiter_bot.taxonomy import load_taxonomy_file

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"

# Records the file and tells the caller whether this run is the one that loads it.
# Two runs at once can't both load it: the primary key lets only one insert succeed.
CLAIM_SEED_FILE_SQL = "INSERT INTO seed_runs (filename) VALUES (%s) ON CONFLICT DO NOTHING RETURNING filename"


def read_records(filename: str, model: type[BaseModel]) -> list[BaseModel]:
    """Valid records only; each bad one is reported and skipped, so it doesn't block the rest."""
    records = []
    for index, raw in enumerate(json.loads((SEED_DIR / filename).read_text(encoding="utf-8"))):
        try:
            records.append(model.model_validate(raw))
        except ValidationError as error:
            print(f"rejected {filename} #{index}: {error.errors()[0]['msg']}", file=sys.stderr)
    return records


def run() -> None:
    # One transaction for profiles, taxonomy and matches, so readers never see one without the others.
    with connect() as conn, conn.transaction():
        loaded = []
        for filename, model, insert in (("candidate_data.json", CandidateInput, insert_candidate),
                                        ("job_data.json", JobInput, insert_job)):
            if conn.execute(CLAIM_SEED_FILE_SQL, (filename,)).fetchone() is None:
                continue  # loaded on an earlier run; edits made since through the API are kept
            records = read_records(filename, model)
            for record in records:
                insert(conn, record)
            loaded.append(f"{len(records)} records from {filename}")
        concepts, relations = load_taxonomy_file(conn, SEED_DIR / "taxonomy.json")
        match_count = refresh_matches(conn)

    print(f"Seeded {', '.join(loaded)}." if loaded else "Seed files were already loaded; nothing added.")
    print(f"Loaded the taxonomy: {concepts} concepts, {relations} related pairs. Stored {match_count} matches.")


if __name__ == "__main__":
    run()
