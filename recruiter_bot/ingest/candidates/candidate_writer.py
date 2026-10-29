import psycopg

from recruiter_bot.ingest.candidates.candidate_batch import CandidateBatch

UPSERT_CANDIDATES_SQL = """
    INSERT INTO candidates (source_key, slug, full_name, email, experience_years, open_to_opportunities,
                            available_from, quirk)
    SELECT *
    FROM unnest(%s::text[], %s::text[], %s::text[], %s::text[], %s::smallint[], %s::boolean[], %s::date[], %s::text[])
    ON CONFLICT (source_key) DO UPDATE SET
        slug                  = EXCLUDED.slug,
        full_name             = EXCLUDED.full_name,
        email                 = EXCLUDED.email,
        experience_years      = EXCLUDED.experience_years,
        open_to_opportunities = EXCLUDED.open_to_opportunities,
        available_from        = EXCLUDED.available_from,
        quirk                 = EXCLUDED.quirk
    WHERE (candidates.slug, candidates.full_name, candidates.email, candidates.experience_years,
           candidates.open_to_opportunities, candidates.available_from, candidates.quirk)
          IS DISTINCT FROM
          (EXCLUDED.slug, EXCLUDED.full_name, EXCLUDED.email, EXCLUDED.experience_years,
           EXCLUDED.open_to_opportunities, EXCLUDED.available_from, EXCLUDED.quirk)
"""

FIND_CANDIDATE_IDS_SQL = """
    SELECT source_key, candidate_id
    FROM candidates
    WHERE source_key = ANY(%s)
"""

DELETE_CANDIDATE_SKILLS_SQL = """
    DELETE FROM candidate_skills
    WHERE candidate_id = ANY(%s)
"""

INSERT_CANDIDATE_SKILLS_SQL = """
    INSERT INTO candidate_skills (candidate_id, skill_id)
    SELECT * FROM unnest(%s::bigint[], %s::bigint[])
    ON CONFLICT DO NOTHING
"""

DELETE_CANDIDATE_TRAITS_SQL = """
    DELETE FROM candidate_traits
    WHERE candidate_id = ANY(%s)
"""

INSERT_CANDIDATE_TRAITS_SQL = """
    INSERT INTO candidate_traits (candidate_id, trait_id)
    SELECT * FROM unnest(%s::bigint[], %s::bigint[])
    ON CONFLICT DO NOTHING
"""

DELETE_CANDIDATE_JOB_PREFERENCES_SQL = """
    DELETE FROM candidate_job_preferences
    WHERE candidate_id = ANY(%s)
"""

INSERT_CANDIDATE_JOB_PREFERENCES_SQL = """
    INSERT INTO candidate_job_preferences (candidate_id, preference)
    SELECT * FROM unnest(%s::bigint[], %s::text[])
    ON CONFLICT DO NOTHING
"""


def save_candidates(
    conn: psycopg.Connection,
    batch: CandidateBatch,
    skill_ids: dict[str, int],
    trait_ids: dict[str, int],
) -> dict[str, int]:
    """Upserts the candidates and replaces their skill, trait and job preference links. Returns source key -> candidate_id."""
    if not batch.source_keys:
        return {}

    conn.execute(UPSERT_CANDIDATES_SQL, (
        batch.source_keys,
        batch.slugs,
        batch.full_names,
        batch.emails,
        batch.experience_years,
        batch.open_to_opportunities,
        batch.available_from,
        batch.quirks,
    ))

    candidate_ids = {}
    for source_key, candidate_id in conn.execute(FIND_CANDIDATE_IDS_SQL, (batch.source_keys,)).fetchall():
        candidate_ids[source_key] = candidate_id

    all_candidate_ids = list(candidate_ids.values())

    conn.execute(DELETE_CANDIDATE_SKILLS_SQL, (all_candidate_ids,))
    skill_owner_ids = []
    skill_value_ids = []
    for candidate_key, skill_slug in batch.skill_links:
        skill_owner_ids.append(candidate_ids[candidate_key])
        skill_value_ids.append(skill_ids[skill_slug])
    if skill_owner_ids:
        conn.execute(INSERT_CANDIDATE_SKILLS_SQL, (skill_owner_ids, skill_value_ids))

    conn.execute(DELETE_CANDIDATE_TRAITS_SQL, (all_candidate_ids,))
    trait_owner_ids = []
    trait_value_ids = []
    for candidate_key, trait_slug in batch.trait_links:
        trait_owner_ids.append(candidate_ids[candidate_key])
        trait_value_ids.append(trait_ids[trait_slug])
    if trait_owner_ids:
        conn.execute(INSERT_CANDIDATE_TRAITS_SQL, (trait_owner_ids, trait_value_ids))

    conn.execute(DELETE_CANDIDATE_JOB_PREFERENCES_SQL, (all_candidate_ids,))
    preference_owner_ids = []
    preferences = []
    for candidate_key, preference in batch.job_preference_links:
        preference_owner_ids.append(candidate_ids[candidate_key])
        preferences.append(preference)
    if preference_owner_ids:
        conn.execute(INSERT_CANDIDATE_JOB_PREFERENCES_SQL, (preference_owner_ids, preferences))

    return candidate_ids
