from dataclasses import dataclass

import psycopg

from recruiter_bot.ingest.batch_inserter import INGEST_LOCK_SQL
from recruiter_bot.ingest.taxonomy.taxonomy_reader import Taxonomy

# Deleting the concepts cascades to their labels and relations.
DELETE_CONCEPTS_SQL = "DELETE FROM concepts"

INSERT_CONCEPTS_SQL = """
    INSERT INTO concepts (concept_type, slug, description, esco_uri, onet_element_id)
    SELECT * FROM unnest(%s::text[], %s::text[], %s::text[], %s::text[], %s::text[])
    RETURNING concept_type, slug, concept_id
"""

INSERT_LABELS_SQL = """
    INSERT INTO concept_labels (concept_id, concept_type, label, label_type)
    SELECT * FROM unnest(%s::bigint[], %s::text[], %s::text[], %s::text[])
"""

INSERT_RELATIONS_SQL = """
    INSERT INTO concept_relations (from_concept_id, to_concept_id, concept_type, relation, credit)
    SELECT * FROM unnest(%s::bigint[], %s::bigint[], %s::text[], %s::text[], %s::numeric[])
"""


@dataclass(frozen=True)
class TaxonomyResult:
    concepts: int
    labels: int
    relations: int


def save_taxonomy(conn: psycopg.Connection, taxonomy: Taxonomy) -> TaxonomyResult:
    """Replaces the whole taxonomy in one transaction. Candidate and job rows are never touched."""
    with conn.transaction():
        conn.execute(INGEST_LOCK_SQL)
        conn.execute(DELETE_CONCEPTS_SQL)
        if taxonomy.concepts:
            concept_ids = {}
            rows = conn.execute(INSERT_CONCEPTS_SQL, (
                [concept.concept_type for concept in taxonomy.concepts],
                [concept.slug for concept in taxonomy.concepts],
                [concept.description for concept in taxonomy.concepts],
                [concept.esco_uri for concept in taxonomy.concepts],
                [concept.onet_element_id for concept in taxonomy.concepts],
            )).fetchall()
            for concept_type, slug, concept_id in rows:
                concept_ids[(concept_type, slug)] = concept_id

            conn.execute(INSERT_LABELS_SQL, (
                [concept_ids[(label.concept_type, label.concept_slug)] for label in taxonomy.labels],
                [label.concept_type for label in taxonomy.labels],
                [label.label for label in taxonomy.labels],
                [label.label_type for label in taxonomy.labels],
            ))
            conn.execute(INSERT_RELATIONS_SQL, (
                [concept_ids[(relation.concept_type, relation.from_slug)] for relation in taxonomy.relations],
                [concept_ids[(relation.concept_type, relation.to_slug)] for relation in taxonomy.relations],
                [relation.concept_type for relation in taxonomy.relations],
                [relation.relation for relation in taxonomy.relations],
                [relation.credit for relation in taxonomy.relations],
            ))
    return TaxonomyResult(
        concepts=len(taxonomy.concepts),
        labels=len(taxonomy.labels),
        relations=len(taxonomy.relations),
    )
