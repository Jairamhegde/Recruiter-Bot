"""A small ESCO-shaped taxonomy: words that mean the same concept, and concepts that are related.

seed/taxonomy.json -> concepts, concept_labels and concept_relations.
Every skill and trait word is then resolved to the concept it means (skills.concept_id, traits.concept_id),
and matching compares those concepts, so synonyms match whichever side uses which word.
"""
import json
from dataclasses import dataclass
from pathlib import Path

import psycopg

from recruiter_bot.ingest import compact_key, normalize

CONCEPT_TYPES = ("skill", "trait")
RELATED_CREDIT = 0.5  # a related concept earns half; the same concept earns full credit


# ---- Loading seed/taxonomy.json into the database

INSERT_CONCEPT_SQL = """
    INSERT INTO concepts (concept_type, slug, description, esco_uri)
    VALUES (%s, %s, %s, %s)
    RETURNING concept_id
"""

INSERT_LABEL_SQL = "INSERT INTO concept_labels (concept_id, concept_type, label) VALUES (%s, %s, %s)"

INSERT_RELATION_SQL = """
    INSERT INTO concept_relations (from_concept_id, to_concept_id, concept_type, credit)
    VALUES (%s, %s, %s, %s), (%s, %s, %s, %s)
"""

# After a reload, every stored word is looked up again, so its concept always follows the current taxonomy.
RESOLVE_WORDS_SQL = [
    """
    UPDATE skills
    SET concept_id = (SELECT concept_id FROM concept_labels
                      WHERE concept_type = 'skill' AND compact_label = replace(skills.slug, '-', ''))
    """,
    """
    UPDATE traits
    SET concept_id = (SELECT concept_id FROM concept_labels
                      WHERE concept_type = 'trait' AND compact_label = replace(traits.slug, '-', ''))
    """,
]


def load_taxonomy_file(conn: psycopg.Connection, path: Path) -> tuple[int, int]:
    """Replaces the stored taxonomy with the file's. Returns (concepts, relations). A bad entry fails it all."""
    data = json.loads(path.read_text(encoding="utf-8"))
    concept_ids = {}
    label_owner = {}

    # Deleting the concepts cascades to their labels and relations.
    conn.execute("DELETE FROM concepts")
    for concept in data["concepts"]:
        concept_type, slug = concept["type"], normalize(concept["id"])
        if concept_type not in CONCEPT_TYPES:
            raise ValueError(f"concept {slug!r}: unknown type {concept_type!r}")
        concept_id = conn.execute(INSERT_CONCEPT_SQL, (
            concept_type, slug, concept.get("description"), concept.get("esco_uri"),
        )).fetchone()[0]
        concept_ids[(concept_type, slug)] = concept_id

        # The concept's own name is a label too: a candidate who writes "resilience" means the resilience concept.
        for raw_label in [slug, concept["preferred_label"], *concept.get("alt_labels", [])]:
            label = normalize(raw_label)
            key = (concept_type, compact_key(label))
            if label_owner.get(key) == slug:
                continue  # the same word twice for one concept, e.g. the id and the preferred label
            # One word can't mean two concepts, or a score would depend on which one was picked.
            if key in label_owner:
                raise ValueError(f"{concept_type} label {label!r} belongs to both {label_owner[key]!r} and {slug!r}")
            label_owner[key] = slug
            conn.execute(INSERT_LABEL_SQL, (concept_id, concept_type, label))

    for relation in data["related"]:
        concept_type = relation["type"]
        first, second = (concept_ids[(concept_type, normalize(slug))] for slug in relation["between"])
        conn.execute(INSERT_RELATION_SQL, (
            first, second, concept_type, RELATED_CREDIT,
            second, first, concept_type, RELATED_CREDIT,
        ))

    for sql in RESOLVE_WORDS_SQL:
        conn.execute(sql)
    return len(concept_ids), len(data["related"])


# ---- Credit: what one term earns toward another

@dataclass(frozen=True)
class Credit:
    value: float
    kind: str  # "exact", "synonym", "related" or "none"


NO_CREDIT = Credit(0.0, "none")
EXACT = Credit(1.0, "exact")


class ExactCredit:
    """Identical terms only. Used by the tests, to score without a taxonomy."""

    def credit(self, concept_type: str, candidate_term: str, job_term: str) -> Credit:
        return EXACT if compact_key(candidate_term) == compact_key(job_term) else NO_CREDIT


class TaxonomyCredit:
    """Same word or same concept 1.0, related concept 0.5, anything else 0. Works the same in both directions."""

    def __init__(self, concept_of_word: dict[tuple[str, str], int], relation_credit: dict[tuple[int, int], float]):
        self._concept_of_word = concept_of_word
        self._relation_credit = relation_credit

    def credit(self, concept_type: str, candidate_term: str, job_term: str) -> Credit:
        if compact_key(candidate_term) == compact_key(job_term):
            return EXACT

        # A word the taxonomy doesn't know has no concept, so it only matches its own spelling.
        candidate_concept = self._concept_of_word.get((concept_type, candidate_term))
        job_concept = self._concept_of_word.get((concept_type, job_term))
        if candidate_concept is None or job_concept is None:
            return NO_CREDIT
        if candidate_concept == job_concept:
            return Credit(1.0, "synonym")

        value = self._relation_credit.get((candidate_concept, job_concept), 0.0)
        return Credit(value, "related") if value > 0 else NO_CREDIT


# The concept each stored word was resolved to: the one place matching learns what a word means.
WORD_CONCEPTS_SQL = """
    SELECT 'skill', slug, concept_id FROM skills WHERE concept_id IS NOT NULL
    UNION ALL
    SELECT 'trait', slug, concept_id FROM traits WHERE concept_id IS NOT NULL
"""

CONCEPT_RELATIONS_SQL = "SELECT from_concept_id, to_concept_id, credit FROM concept_relations"


def load_taxonomy_credit(conn: psycopg.Connection) -> TaxonomyCredit:
    concept_of_word = {}
    for concept_type, slug, concept_id in conn.execute(WORD_CONCEPTS_SQL).fetchall():
        concept_of_word[(concept_type, slug)] = concept_id

    relation_credit = {}
    for from_concept_id, to_concept_id, credit in conn.execute(CONCEPT_RELATIONS_SQL).fetchall():
        relation_credit[(from_concept_id, to_concept_id)] = float(credit)
    return TaxonomyCredit(concept_of_word, relation_credit)
