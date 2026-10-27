import psycopg

from recruiter_bot.ingest.candidates.candidate_batch import CandidateBatch

UPSERT_CANDIDATES_SQL = """
    INSERT INTO candidates (slug, full_name, experience_years, open_to_opportunities, available_from, quirk)
    SELECT *
    FROM unnest(%s::text[], %s::text[], %s::smallint[], %s::boolean[], %s::date[], %s::text[])
    ON CONFLICT (slug) DO UPDATE SET
        full_name             = EXCLUDED.full_name,
        experience_years      = EXCLUDED.experience_years,
        open_to_opportunities = EXCLUDED.open_to_opportunities,
        available_from        = EXCLUDED.available_from,
        quirk                 = EXCLUDED.quirk
    WHERE (candidates.full_name, candidates.experience_years, candidates.open_to_opportunities,
           candidates.available_from, candidates.quirk)
          IS DISTINCT FROM
          (EXCLUDED.full_name, EXCLUDED.experience_years, EXCLUDED.open_to_opportunities,
           EXCLUDED.available_from, EXCLUDED.quirk)
"""

FIND_CANDIDATE_IDS_SQL = """
    SELECT slug, candidate_id
    FROM candidates
    WHERE slug = ANY(%s)
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


def save_candidates(
    conn: psycopg.Connection,
    batch: CandidateBatch,
    skill_ids: dict[str, int],
    trait_ids: dict[str, int],
) -> dict[str, int]:
    """Upserts the candidates and replaces their skill and trait links. Returns slug -> candidate_id."""
    if not batch.slugs:
        return {}

    conn.execute(UPSERT_CANDIDATES_SQL, (
        batch.slugs,
        batch.full_names,
        batch.experience_years,
        batch.open_to_opportunities,
        batch.available_from,
        batch.quirks,
    ))

    candidate_ids = {}
    for slug, candidate_id in conn.execute(FIND_CANDIDATE_IDS_SQL, (batch.slugs,)).fetchall():
        candidate_ids[slug] = candidate_id

    all_candidate_ids = list(candidate_ids.values())

    conn.execute(DELETE_CANDIDATE_SKILLS_SQL, (all_candidate_ids,))
    skill_owner_ids = []
    skill_value_ids = []
    for candidate_slug, skill_slug in batch.skill_links:
        skill_owner_ids.append(candidate_ids[candidate_slug])
        skill_value_ids.append(skill_ids[skill_slug])
    if skill_owner_ids:
        conn.execute(INSERT_CANDIDATE_SKILLS_SQL, (skill_owner_ids, skill_value_ids))

    conn.execute(DELETE_CANDIDATE_TRAITS_SQL, (all_candidate_ids,))
    trait_owner_ids = []
    trait_value_ids = []
    for candidate_slug, trait_slug in batch.trait_links:
        trait_owner_ids.append(candidate_ids[candidate_slug])
        trait_value_ids.append(trait_ids[trait_slug])
    if trait_owner_ids:
        conn.execute(INSERT_CANDIDATE_TRAITS_SQL, (trait_owner_ids, trait_value_ids))

    return candidate_ids
