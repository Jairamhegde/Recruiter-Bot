"""Loads seed/*.json into the database. Usage: python -m recruiter_bot.seed"""
import sys
from datetime import date
from pathlib import Path

from recruiter_bot.db import connect
from recruiter_bot.ingest import (
    TermReport,
    build_candidate_batch,
    build_job_batch,
    build_term_report,
    extract_candidates,
    extract_jobs,
    insert_batch,
    log_rejected,
    read_json_records,
    read_taxonomy,
    save_taxonomy,
)
from recruiter_bot.ingest.batch_inserter import INGEST_LOCK_SQL
from recruiter_bot.matching import refresh_all_matches

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"

EXISTING_CANDIDATE_SLUGS_SQL = "SELECT slug FROM candidates WHERE slug = ANY(%s)"

EXISTING_JOB_SLUGS_SQL = "SELECT slug FROM jobs WHERE slug = ANY(%s)"


def _not_yet_stored(conn, existing_slugs_sql: str, records: list) -> list:
    slugs = [record.slug for record in records]
    stored = {slug for (slug,) in conn.execute(existing_slugs_sql, (slugs,)).fetchall()}
    return [record for record in records if record.slug not in stored]


def run(today: date | None = None) -> None:
    # Validated before any write, so a bad taxonomy file changes nothing.
    taxonomy = read_taxonomy(SEED_DIR / "taxonomy.json")

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

        # One transaction for profiles, taxonomy and matches, so readers never see one without the others (D-37).
        with conn.transaction():
            conn.execute(INGEST_LOCK_SQL)
            # The seed only bootstraps: stored records are never overwritten, so edits made
            # through PATCH survive and availability dates don't restart (D-39).
            new_candidates = _not_yet_stored(conn, EXISTING_CANDIDATE_SLUGS_SQL, candidate_extraction.records)
            new_jobs = _not_yet_stored(conn, EXISTING_JOB_SLUGS_SQL, job_extraction.records)
            result = insert_batch(conn, build_candidate_batch(new_candidates), build_job_batch(new_jobs), source="seed")
            taxonomy_result = save_taxonomy(conn, taxonomy)
            match_count = refresh_all_matches(conn)
        term_report = build_term_report(conn, taxonomy)

    kept = len(candidate_extraction.records) - len(new_candidates) + len(job_extraction.records) - len(new_jobs)
    print(
        f"Seeded {result.candidates} new candidates and {result.jobs} new jobs; "
        f"{kept} records were already stored and kept as they are "
        f"({len(candidate_extraction.rejected)} candidate and {len(job_extraction.rejected)} job records rejected)."
    )
    print(
        f"Loaded the taxonomy: {taxonomy_result.concepts} concepts, {taxonomy_result.labels} labels, "
        f"{taxonomy_result.relations} relations (one row per direction)."
    )
    print(f"Stored {match_count} matches.")
    _print_term_report(term_report)


def _print_term_report(report: TermReport) -> None:
    if report.unknown_skills:
        print(f"unknown skills (no taxonomy label): {', '.join(report.unknown_skills)}")
    if report.unknown_traits:
        print(f"unknown traits (no taxonomy label): {', '.join(report.unknown_traits)}")
    for hint in report.hints:
        print(f"review hint: {hint.concept_type} {hint.term} may be a label of {hint.concept} "
              f"(like {', '.join(hint.like)})")

    for vocabulary_name, terms in (("skills", report.unmatched_skills), ("traits", report.unmatched_traits)):
        for side, label in (("candidate", "no job asks for"), ("job", "no candidate covers")):
            slugs = [slug for slug, term_side in terms if term_side == side]
            if slugs:
                print(f"unmatched {vocabulary_name} {label}: {', '.join(slugs)}")


def _print_rejections(entity_type: str, rejected: list) -> None:
    for error in rejected:
        print(f"rejected {entity_type} #{error.index}: {error.message}", file=sys.stderr)


if __name__ == "__main__":
    run()
