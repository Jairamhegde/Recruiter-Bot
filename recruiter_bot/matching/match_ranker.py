import psycopg

from recruiter_bot.matching.match_scorer import MatchResult, score_match
from recruiter_bot.matching.profile_reader import load_candidate_profiles, load_job_profiles
from recruiter_bot.matching.term_credit import TermCredit, load_taxonomy_credit

# Each ranker only fixes one side and orders the other (D-32). A signal that belongs to
# one side, such as candidate preferences, would be added here, never in score_match.


def rank_candidates_for_job(
    conn: psycopg.Connection, job_id: int, credit: TermCredit | None = None
) -> list[MatchResult] | None:
    """Best candidates first. None if the job doesn't exist."""
    jobs = load_job_profiles(conn, job_id)
    if not jobs:
        return None
    job = jobs[0]
    credit = credit or load_taxonomy_credit(conn)

    # One sorted list; each result carries its tier, so callers can group without losing any (D-34).
    results = []
    for candidate in load_candidate_profiles(conn):
        result = score_match(candidate, job, credit)
        if result.qualifies:
            results.append(result)

    results.sort(key=lambda result: (-result.score, -result.skill_score, result.candidate_name))
    return results


def rank_jobs_for_candidate(
    conn: psycopg.Connection, candidate_id: int, credit: TermCredit | None = None
) -> list[MatchResult] | None:
    """Best jobs first. None if the candidate doesn't exist."""
    candidates = load_candidate_profiles(conn, candidate_id)
    if not candidates:
        return None
    candidate = candidates[0]
    credit = credit or load_taxonomy_credit(conn)

    results = []
    for job in load_job_profiles(conn):
        result = score_match(candidate, job, credit)
        if result.qualifies:
            results.append(result)

    results.sort(key=lambda result: (-result.score, -result.skill_score, result.job_title))
    return results
