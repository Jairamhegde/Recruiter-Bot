from dataclasses import dataclass, field

import psycopg


@dataclass(frozen=True)
class JobProfile:
    job_id: int
    title: str
    min_experience_years: int
    required_skills: list[str]
    culture_keywords: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CandidateProfile:
    candidate_id: int
    full_name: str
    experience_years: int
    skills: list[str]
    traits: list[str] = field(default_factory=list)


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
           ) AS culture_keywords
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
    profiles = []
    for row in conn.execute(JOB_PROFILES_SQL, {"job_id": job_id}).fetchall():
        job_id_value, title, min_experience_years, required_skills, culture_keywords = row
        profiles.append(JobProfile(job_id_value, title, min_experience_years, required_skills, culture_keywords))
    return profiles


def load_candidate_profiles(conn: psycopg.Connection, candidate_id: int | None = None) -> list[CandidateProfile]:
    """All candidates, or only the one with candidate_id."""
    profiles = []
    for row in conn.execute(CANDIDATE_PROFILES_SQL, {"candidate_id": candidate_id}).fetchall():
        candidate_id_value, full_name, experience_years, skills, traits = row
        profiles.append(CandidateProfile(candidate_id_value, full_name, experience_years, skills, traits))
    return profiles
