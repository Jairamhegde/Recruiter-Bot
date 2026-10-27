import psycopg

from recruiter_bot.ingest.jobs.job_batch import JobBatch

UPSERT_JOBS_SQL = """
    INSERT INTO jobs (slug, title, min_experience_years, tagline)
    SELECT *
    FROM unnest(%s::text[], %s::text[], %s::smallint[], %s::text[])
    ON CONFLICT (slug) DO UPDATE SET
        title                = EXCLUDED.title,
        min_experience_years = EXCLUDED.min_experience_years,
        tagline              = EXCLUDED.tagline
    WHERE (jobs.title, jobs.min_experience_years, jobs.tagline)
          IS DISTINCT FROM
          (EXCLUDED.title, EXCLUDED.min_experience_years, EXCLUDED.tagline)
"""

FIND_JOB_IDS_SQL = """
    SELECT slug, job_id
    FROM jobs
    WHERE slug = ANY(%s)
"""

DELETE_JOB_SKILLS_SQL = """
    DELETE FROM job_skills
    WHERE job_id = ANY(%s)
"""

INSERT_JOB_SKILLS_SQL = """
    INSERT INTO job_skills (job_id, skill_id)
    SELECT * FROM unnest(%s::bigint[], %s::bigint[])
    ON CONFLICT DO NOTHING
"""

DELETE_JOB_CULTURE_TRAITS_SQL = """
    DELETE FROM job_culture_traits
    WHERE job_id = ANY(%s)
"""

INSERT_JOB_CULTURE_TRAITS_SQL = """
    INSERT INTO job_culture_traits (job_id, trait_id)
    SELECT * FROM unnest(%s::bigint[], %s::bigint[])
    ON CONFLICT DO NOTHING
"""


def save_jobs(
    conn: psycopg.Connection,
    batch: JobBatch,
    skill_ids: dict[str, int],
    trait_ids: dict[str, int],
) -> dict[str, int]:
    """Upserts the jobs and replaces their skill and culture-trait links. Returns slug -> job_id."""
    if not batch.slugs:
        return {}

    conn.execute(UPSERT_JOBS_SQL, (
        batch.slugs,
        batch.titles,
        batch.min_experience_years,
        batch.taglines,
    ))

    job_ids = {}
    for slug, job_id in conn.execute(FIND_JOB_IDS_SQL, (batch.slugs,)).fetchall():
        job_ids[slug] = job_id

    all_job_ids = list(job_ids.values())

    conn.execute(DELETE_JOB_SKILLS_SQL, (all_job_ids,))
    skill_owner_ids = []
    skill_value_ids = []
    for job_slug, skill_slug in batch.skill_links:
        skill_owner_ids.append(job_ids[job_slug])
        skill_value_ids.append(skill_ids[skill_slug])
    if skill_owner_ids:
        conn.execute(INSERT_JOB_SKILLS_SQL, (skill_owner_ids, skill_value_ids))

    conn.execute(DELETE_JOB_CULTURE_TRAITS_SQL, (all_job_ids,))
    trait_owner_ids = []
    trait_value_ids = []
    for job_slug, trait_slug in batch.culture_trait_links:
        trait_owner_ids.append(job_ids[job_slug])
        trait_value_ids.append(trait_ids[trait_slug])
    if trait_owner_ids:
        conn.execute(INSERT_JOB_CULTURE_TRAITS_SQL, (trait_owner_ids, trait_value_ids))

    return job_ids
