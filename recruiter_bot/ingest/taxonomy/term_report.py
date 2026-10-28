from dataclasses import dataclass

import psycopg

from recruiter_bot.ingest.taxonomy.review_hints import ConceptHint, suggest_concepts
from recruiter_bot.ingest.taxonomy.taxonomy_reader import Taxonomy

# Unknown: no label of that type in the taxonomy (D-31).
UNKNOWN_SKILLS_SQL = """
    SELECT skills.slug
    FROM skills
    WHERE NOT EXISTS (
        SELECT 1 FROM concept_labels
        WHERE concept_labels.concept_type = 'skill' AND concept_labels.compact_key = skills.compact_key
    )
    ORDER BY skills.slug
"""

UNKNOWN_TRAITS_SQL = """
    SELECT traits.slug
    FROM traits
    WHERE NOT EXISTS (
        SELECT 1 FROM concept_labels
        WHERE concept_labels.concept_type = 'trait' AND concept_labels.compact_key = traits.compact_key
    )
    ORDER BY traits.slug
"""

# Unmatched: no term on the other side earns credit for it, whether by being the
# same term, a label of the same concept, or a label of a related concept (D-29).
UNMATCHED_SKILLS_SQL = """
    WITH skill_concept_ids AS (
        SELECT skills.skill_id, concept_labels.concept_id
        FROM skills
        JOIN concept_labels ON concept_labels.concept_type = 'skill'
                           AND concept_labels.compact_key  = skills.compact_key
    ),
    credited AS (
        SELECT skills.skill_id AS from_id, skills.skill_id AS to_id FROM skills
        UNION
        SELECT own.skill_id, other.skill_id
        FROM skill_concept_ids AS own
        JOIN skill_concept_ids AS other ON other.concept_id = own.concept_id
        UNION
        SELECT own.skill_id, other.skill_id
        FROM skill_concept_ids AS own
        JOIN concept_relations ON concept_relations.from_concept_id = own.concept_id
                              AND concept_relations.credit > 0
        JOIN skill_concept_ids AS other ON other.concept_id = concept_relations.to_concept_id
    )
    SELECT skills.slug, 'candidate' AS side
    FROM skills
    WHERE EXISTS (SELECT 1 FROM candidate_skills WHERE candidate_skills.skill_id = skills.skill_id)
      AND NOT EXISTS (
          SELECT 1 FROM credited
          JOIN job_skills ON job_skills.skill_id = credited.to_id
          WHERE credited.from_id = skills.skill_id
      )
    UNION ALL
    SELECT skills.slug, 'job' AS side
    FROM skills
    WHERE EXISTS (SELECT 1 FROM job_skills WHERE job_skills.skill_id = skills.skill_id)
      AND NOT EXISTS (
          SELECT 1 FROM credited
          JOIN candidate_skills ON candidate_skills.skill_id = credited.from_id
          WHERE credited.to_id = skills.skill_id
      )
    ORDER BY side, slug
"""

UNMATCHED_TRAITS_SQL = """
    WITH trait_concept_ids AS (
        SELECT traits.trait_id, concept_labels.concept_id
        FROM traits
        JOIN concept_labels ON concept_labels.concept_type = 'trait'
                           AND concept_labels.compact_key  = traits.compact_key
    ),
    credited AS (
        SELECT traits.trait_id AS from_id, traits.trait_id AS to_id FROM traits
        UNION
        SELECT own.trait_id, other.trait_id
        FROM trait_concept_ids AS own
        JOIN trait_concept_ids AS other ON other.concept_id = own.concept_id
        UNION
        SELECT own.trait_id, other.trait_id
        FROM trait_concept_ids AS own
        JOIN concept_relations ON concept_relations.from_concept_id = own.concept_id
                              AND concept_relations.credit > 0
        JOIN trait_concept_ids AS other ON other.concept_id = concept_relations.to_concept_id
    )
    SELECT traits.slug, 'candidate' AS side
    FROM traits
    WHERE EXISTS (SELECT 1 FROM candidate_traits WHERE candidate_traits.trait_id = traits.trait_id)
      AND NOT EXISTS (
          SELECT 1 FROM credited
          JOIN job_culture_traits ON job_culture_traits.trait_id = credited.to_id
          WHERE credited.from_id = traits.trait_id
      )
    UNION ALL
    SELECT traits.slug, 'job' AS side
    FROM traits
    WHERE EXISTS (SELECT 1 FROM job_culture_traits WHERE job_culture_traits.trait_id = traits.trait_id)
      AND NOT EXISTS (
          SELECT 1 FROM credited
          JOIN candidate_traits ON candidate_traits.trait_id = credited.from_id
          WHERE credited.to_id = traits.trait_id
      )
    ORDER BY side, slug
"""


@dataclass(frozen=True)
class TermReport:
    unknown_skills: list[str]
    unknown_traits: list[str]
    unmatched_skills: list[tuple[str, str]]
    unmatched_traits: list[tuple[str, str]]
    hints: list[ConceptHint]


def build_term_report(conn: psycopg.Connection, taxonomy: Taxonomy) -> TermReport:
    """Unknown terms with review hints, plus (slug, side) for terms the other side can't cover."""
    unknown_skills = [slug for (slug,) in conn.execute(UNKNOWN_SKILLS_SQL).fetchall()]
    unknown_traits = [slug for (slug,) in conn.execute(UNKNOWN_TRAITS_SQL).fetchall()]
    return TermReport(
        unknown_skills=unknown_skills,
        unknown_traits=unknown_traits,
        unmatched_skills=[tuple(row) for row in conn.execute(UNMATCHED_SKILLS_SQL).fetchall()],
        unmatched_traits=[tuple(row) for row in conn.execute(UNMATCHED_TRAITS_SQL).fetchall()],
        hints=suggest_concepts(unknown_skills, "skill", taxonomy.labels)
        + suggest_concepts(unknown_traits, "trait", taxonomy.labels),
    )
