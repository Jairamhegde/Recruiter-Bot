"""Prints ranked matches. Usage:
    python -m recruiter_bot.show_matches job 1
    python -m recruiter_bot.show_matches candidate 5
"""
import sys

from recruiter_bot.db import connect
from recruiter_bot.matching import rank_candidates_for_job, rank_jobs_for_candidate


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 3 or sys.argv[1] not in ("job", "candidate") or not sys.argv[2].isdigit():
        print(__doc__)
        raise SystemExit(2)

    direction = sys.argv[1]
    record_id = int(sys.argv[2])

    with connect() as conn:
        if direction == "job":
            results = rank_candidates_for_job(conn, record_id)
        else:
            results = rank_jobs_for_candidate(conn, record_id)

    if results is None:
        print(f"No {direction} with id {record_id}.")
        raise SystemExit(1)
    if not results:
        print("No matches (nobody shares a required skill).")
        return

    for rank, result in enumerate(results, start=1):
        name = result.candidate_name if direction == "job" else result.job_title
        print(f"{rank:>2}. {result.score:5.1f}  {name:<32} {result.reason}")


if __name__ == "__main__":
    main()
