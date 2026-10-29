"""Matches are computed on every write and stored, so reads are one query and never stale."""
from dataclasses import dataclass

import psycopg

from recruiter_bot.matching.scorer import CandidateProfile, JobProfile, MatchResult, score_match, tier_for
from recruiter_bot.taxonomy import load_taxonomy_credit

# ---- Reading profiles

JOB_PROFILES_SQL = """
    SELECT jobs.job_id,
           jobs.title,
           jobs.min_experience_years,
           ARRAY(
               SELECT skills.slug
               FROM job_skills
               JOIN skills ON skills.skill_id = job_skills.skill_id
               WHERE job_skills.job_id = jobs.job_id
               ORDER BY skills.slug
           ) AS required_skills,
           ARRAY(
               SELECT traits.slug
               FROM job_culture_traits
               JOIN traits ON traits.trait_id = job_culture_traits.trait_id
               WHERE job_culture_traits.job_id = jobs.job_id
               ORDER BY traits.slug
           ) AS culture_keywords,
           jobs.experience_requirement
    FROM jobs
    WHERE %(job_id)s::bigint IS NULL OR jobs.job_id = %(job_id)s
    ORDER BY jobs.job_id
"""

CANDIDATE_PROFILES_SQL = """
    SELECT candidates.candidate_id,
           candidates.full_name,
           candidates.experience_years,
           ARRAY(
               SELECT skills.slug
               FROM candidate_skills
               JOIN skills ON skills.skill_id = candidate_skills.skill_id
               WHERE candidate_skills.candidate_id = candidates.candidate_id
               ORDER BY skills.slug
           ) AS skills,
           ARRAY(
               SELECT traits.slug
               FROM candidate_traits
               JOIN traits ON traits.trait_id = candidate_traits.trait_id
               WHERE candidate_traits.candidate_id = candidates.candidate_id
               ORDER BY traits.slug
           ) AS traits
    FROM candidates
    WHERE %(candidate_id)s::bigint IS NULL OR candidates.candidate_id = %(candidate_id)s
    ORDER BY candidates.candidate_id
"""


def load_job_profiles(conn: psycopg.Connection, job_id: int | None = None) -> list[JobProfile]:
    """All jobs, or only the one with job_id."""
    return [JobProfile(*row) for row in conn.execute(JOB_PROFILES_SQL, {"job_id": job_id}).fetchall()]


def load_candidate_profiles(conn: psycopg.Connection, candidate_id: int | None = None) -> list[CandidateProfile]:
    """All candidates, or only the one with candidate_id."""
    rows = conn.execute(CANDIDATE_PROFILES_SQL, {"candidate_id": candidate_id}).fetchall()
    return [CandidateProfile(*row) for row in rows]


# ---- Writing: replace the affected rows, never append

DELETE_MATCHES_SQL = """
    DELETE FROM matches
    WHERE (%(candidate_id)s::bigint IS NULL OR candidate_id = %(candidate_id)s)
      AND (%(job_id)s::bigint IS NULL OR job_id = %(job_id)s)
"""

INSERT_MATCH_SQL = """
    INSERT INTO matches (job_id, candidate_id, skill_score, experience_score, culture_score, score, reason,
                         matched_skills, missing_skills, matched_culture, missing_culture)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def refresh_matches(conn: psycopg.Connection, candidate_id: int | None = None, job_id: int | None = None) -> int:
    """Recomputes one candidate's matches, one job's, or (with neither) all of them. Returns how many qualify."""
    credit = load_taxonomy_credit(conn)
    results: list[MatchResult] = []
    for candidate in load_candidate_profiles(conn, candidate_id):
        for job in load_job_profiles(conn, job_id):
            result = score_match(candidate, job, credit)
            if result.qualifies:
                results.append(result)

    conn.execute(DELETE_MATCHES_SQL, {"candidate_id": candidate_id, "job_id": job_id})
    with conn.cursor() as cursor:
        cursor.executemany(INSERT_MATCH_SQL, [
            (r.job_id, r.candidate_id, r.skill_score, r.experience_score, r.culture_score, r.score, r.reason,
             r.matched_skills, r.missing_skills, r.matched_culture, r.missing_culture)
            for r in results
        ])
    return len(results)


# ---- Reading stored matches

@dataclass(frozen=True)
class StoredMatch:
    job_id: int
    job_title: str
    candidate_id: int
    candidate_name: str
    score: float
    skill_score: float
    experience_score: float
    culture_score: float | None
    matched_skills: list[str]
    missing_skills: list[str]
    matched_culture: list[str]
    missing_culture: list[str]
    reason: str
    candidate_experience_years: int
    job_min_experience_years: int
    # Shown, never scored: the recruiter reads the quirk, the candidate reads the tagline.
    candidate_quirk: str | None
    job_tagline: str | None
    candidate_is_open: bool  # open to opportunities; decides the recruiter's two sections

    @property
    def meets_minimum_experience(self) -> bool:
        return self.candidate_experience_years >= self.job_min_experience_years

    @property
    def tier(self) -> str:
        return tier_for(self.score, self.meets_minimum_experience)


STORED_MATCHES_SELECT = """
    SELECT matches.job_id, jobs.title, matches.candidate_id, candidates.full_name,
           matches.score, matches.skill_score, matches.experience_score, matches.culture_score,
           matches.matched_skills, matches.missing_skills, matches.matched_culture, matches.missing_culture,
           matches.reason, candidates.experience_years, jobs.min_experience_years,
           candidates.quirk, jobs.tagline, candidates.open_to_opportunities
    FROM matches
    JOIN jobs       ON jobs.job_id             = matches.job_id
    JOIN candidates ON candidates.candidate_id = matches.candidate_id
"""

# The candidate's final order (top applicant, newest posting) is applied in views.py.
MATCHES_FOR_CANDIDATE_SQL = STORED_MATCHES_SELECT + """
    WHERE matches.candidate_id = %s
    ORDER BY matches.score DESC
"""

# Score, open before not looking, earliest start (a past date counts as today), then a neutral hash.
MATCHES_FOR_JOB_SQL = STORED_MATCHES_SELECT + """
    WHERE matches.job_id = %s
    ORDER BY matches.score DESC,
             candidates.open_to_opportunities DESC,
             GREATEST(candidates.available_from, current_date),
             md5(matches.job_id::text || ':' || matches.candidate_id::text)
"""

CANDIDATE_EXISTS_SQL = "SELECT EXISTS (SELECT 1 FROM candidates WHERE candidate_id = %s)"

JOB_EXISTS_SQL = "SELECT EXISTS (SELECT 1 FROM jobs WHERE job_id = %s)"


def stored_matches_for_candidate(conn: psycopg.Connection, candidate_id: int) -> list[StoredMatch] | None:
    """Best jobs first. None if the candidate doesn't exist."""
    if not conn.execute(CANDIDATE_EXISTS_SQL, (candidate_id,)).fetchone()[0]:
        return None
    return _stored_matches(conn, MATCHES_FOR_CANDIDATE_SQL, candidate_id)


def stored_matches_for_job(conn: psycopg.Connection, job_id: int) -> list[StoredMatch] | None:
    """Best candidates first. None if the job doesn't exist."""
    if not conn.execute(JOB_EXISTS_SQL, (job_id,)).fetchone()[0]:
        return None
    return _stored_matches(conn, MATCHES_FOR_JOB_SQL, job_id)


def _stored_matches(conn: psycopg.Connection, sql: str, entity_id: int) -> list[StoredMatch]:
    matches = []
    for row in conn.execute(sql, (entity_id,)).fetchall():
        (job_id, job_title, candidate_id, candidate_name, score, skill_score, experience_score, culture_score,
         *rest) = row
        matches.append(StoredMatch(
            job_id, job_title, candidate_id, candidate_name,
            float(score), float(skill_score), float(experience_score),
            None if culture_score is None else float(culture_score),
            *rest,
        ))
    return matches
