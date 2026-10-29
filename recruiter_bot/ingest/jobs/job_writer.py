import psycopg

from recruiter_bot.ingest.jobs.job_batch import JobBatch

UPSERT_JOBS_SQL = """
    INSERT INTO jobs (source_key, slug, title, company, min_experience_years, experience_requirement, tagline)
    SELECT *
    FROM unnest(%s::text[], %s::text[], %s::text[], %s::text[], %s::smallint[], %s::text[], %s::text[])
    ON CONFLICT (source_key) DO UPDATE SET
        slug                 = EXCLUDED.slug,
        title                = EXCLUDED.title,
        company              = EXCLUDED.company,
        min_experience_years = EXCLUDED.min_experience_years,
        experience_requirement = EXCLUDED.experience_requirement,
        tagline              = EXCLUDED.tagline
    WHERE (jobs.slug, jobs.title, jobs.company, jobs.min_experience_years, jobs.experience_requirement, jobs.tagline)
          IS DISTINCT FROM
          (EXCLUDED.slug, EXCLUDED.title, EXCLUDED.company, EXCLUDED.min_experience_years,
           EXCLUDED.experience_requirement, EXCLUDED.tagline)
"""

FIND_JOB_IDS_SQL = """
    SELECT source_key, job_id
    FROM jobs
    WHERE source_key = ANY(%s)
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
    """Upserts the jobs and replaces their skill and culture-trait links. Returns source key -> job_id."""
    if not batch.source_keys:
        return {}

    conn.execute(UPSERT_JOBS_SQL, (
        batch.source_keys,
        batch.slugs,
        batch.titles,
        batch.companies,
        batch.min_experience_years,
        batch.experience_requirements,
        batch.taglines,
    ))

    job_ids = {}
    for source_key, job_id in conn.execute(FIND_JOB_IDS_SQL, (batch.source_keys,)).fetchall():
        job_ids[source_key] = job_id

    all_job_ids = list(job_ids.values())

    conn.execute(DELETE_JOB_SKILLS_SQL, (all_job_ids,))
    skill_owner_ids = []
    skill_value_ids = []
    for job_key, skill_slug in batch.skill_links:
        skill_owner_ids.append(job_ids[job_key])
        skill_value_ids.append(skill_ids[skill_slug])
    if skill_owner_ids:
        conn.execute(INSERT_JOB_SKILLS_SQL, (skill_owner_ids, skill_value_ids))

    conn.execute(DELETE_JOB_CULTURE_TRAITS_SQL, (all_job_ids,))
    trait_owner_ids = []
    trait_value_ids = []
    for job_key, trait_slug in batch.culture_trait_links:
        trait_owner_ids.append(job_ids[job_key])
        trait_value_ids.append(trait_ids[trait_slug])
    if trait_owner_ids:
        conn.execute(INSERT_JOB_CULTURE_TRAITS_SQL, (trait_owner_ids, trait_value_ids))

    return job_ids
