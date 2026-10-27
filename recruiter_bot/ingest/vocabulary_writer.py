import psycopg

from recruiter_bot.ingest.text_normalizer import compact_key

INSERT_SKILLS_SQL = """
    INSERT INTO skills (slug)
    SELECT unnest(%s::text[])
    ON CONFLICT DO NOTHING
"""

FIND_SKILLS_BY_COMPACT_KEY_SQL = """
    SELECT compact_key, skill_id
    FROM skills
    WHERE compact_key = ANY(%s)
"""

INSERT_TRAITS_SQL = """
    INSERT INTO traits (slug)
    SELECT unnest(%s::text[])
    ON CONFLICT DO NOTHING
"""

FIND_TRAITS_BY_COMPACT_KEY_SQL = """
    SELECT compact_key, trait_id
    FROM traits
    WHERE compact_key = ANY(%s)
"""


def resolve_skill_ids(conn: psycopg.Connection, slugs: list[str]) -> dict[str, int]:
    return _resolve_ids(conn, slugs, INSERT_SKILLS_SQL, FIND_SKILLS_BY_COMPACT_KEY_SQL)


def resolve_trait_ids(conn: psycopg.Connection, slugs: list[str]) -> dict[str, int]:
    return _resolve_ids(conn, slugs, INSERT_TRAITS_SQL, FIND_TRAITS_BY_COMPACT_KEY_SQL)


def _resolve_ids(
    conn: psycopg.Connection,
    slugs: list[str],
    insert_vocabulary_sql: str,
    find_by_compact_key_sql: str,
) -> dict[str, int]:
    """Maps each slug to its id by compact key. Unknown values are added first."""
    unique_slugs = sorted(set(slugs))
    if not unique_slugs:
        return {}

    conn.execute(insert_vocabulary_sql, (unique_slugs,))

    keys = [compact_key(slug) for slug in unique_slugs]
    id_by_compact_key = {}
    for key, vocabulary_id in conn.execute(find_by_compact_key_sql, (keys,)).fetchall():
        id_by_compact_key[key] = vocabulary_id

    id_by_slug = {}
    for slug in unique_slugs:
        id_by_slug[slug] = id_by_compact_key[compact_key(slug)]
    return id_by_slug
