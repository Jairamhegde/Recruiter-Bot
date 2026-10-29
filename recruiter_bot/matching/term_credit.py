from dataclasses import dataclass
from typing import Protocol

import psycopg

from recruiter_bot.ingest.text_normalizer import compact_key


@dataclass(frozen=True)
class Credit:
    value: float
    kind: str  # "exact", "synonym", "related", "suggested" or "none"


NO_CREDIT = Credit(0.0, "none")
EXACT = Credit(1.0, "exact")

# A model-linked word earns half of 'related', never as much as a curated link.
SUGGESTED_CREDIT = 0.25


class TermCredit(Protocol):
    """How much a candidate term earns toward a job term. The scorer only sees this."""

    def credit(self, concept_type: str, candidate_term: str, job_term: str) -> Credit: ...


class ExactCredit:
    """Identical terms only, compared by compact key."""

    def credit(self, concept_type: str, candidate_term: str, job_term: str) -> Credit:
        if compact_key(candidate_term) == compact_key(job_term):
            return EXACT
        return NO_CREDIT


class TaxonomyCredit:
    """Same concept 1.0, related per its relation, model-suggested 0.25, else 0."""

    def __init__(
        self,
        concept_by_label: dict[tuple[str, str], int],
        relation_credit: dict[tuple[int, int], float],
        suggested_concept: dict[tuple[str, str], int] | None = None,
    ) -> None:
        self._concept_by_label = concept_by_label
        self._relation_credit = relation_credit
        self._suggested_concept = suggested_concept or {}

    def credit(self, concept_type: str, candidate_term: str, job_term: str) -> Credit:
        if compact_key(candidate_term) == compact_key(job_term):
            return EXACT

        candidate_concept = self._concept_by_label.get((concept_type, compact_key(candidate_term)))
        job_concept = self._concept_by_label.get((concept_type, compact_key(job_term)))
        if candidate_concept is None or job_concept is None:
            return self._suggested_credit(concept_type, candidate_term, job_term, candidate_concept, job_concept)
        if candidate_concept == job_concept:
            return Credit(1.0, "synonym")

        # "unrelated" relations are stored with credit 0, so they fall through to no credit.
        value = self._relation_credit.get((candidate_concept, job_concept), 0.0)
        if value > 0:
            return Credit(value, "related")
        return NO_CREDIT

    def _suggested_credit(
        self, concept_type: str, candidate_term: str, job_term: str,
        candidate_concept: int | None, job_concept: int | None,
    ) -> Credit:
        """Credit when the model linked one side to the other's concept; one guess per pair."""
        if candidate_concept is None and job_concept is not None:
            suggested = self._suggested_concept.get((concept_type, compact_key(candidate_term)))
            if suggested == job_concept:
                return Credit(SUGGESTED_CREDIT, "suggested")
        if job_concept is None and candidate_concept is not None:
            suggested = self._suggested_concept.get((concept_type, compact_key(job_term)))
            if suggested == candidate_concept:
                return Credit(SUGGESTED_CREDIT, "suggested")
        return NO_CREDIT


CONCEPT_LABELS_SQL = "SELECT concept_type, compact_key, concept_id FROM concept_labels"

CONCEPT_RELATIONS_SQL = "SELECT from_concept_id, to_concept_id, credit FROM concept_relations"

# Model-linked words earn suggested credit; approved words are synonyms.
SUGGESTED_LINKS_SQL = """
    SELECT term_suggestions.concept_type, term_suggestions.term, term_suggestions.outcome, concepts.concept_id
    FROM term_suggestions
    JOIN concepts ON concepts.concept_type = term_suggestions.concept_type
                 AND concepts.slug = term_suggestions.concept_slug
    WHERE term_suggestions.outcome IN ('linked', 'approved')
"""


def load_taxonomy_credit(conn: psycopg.Connection) -> TaxonomyCredit:
    concept_by_label = {}
    for concept_type, key, concept_id in conn.execute(CONCEPT_LABELS_SQL).fetchall():
        concept_by_label[(concept_type, key)] = concept_id

    relation_credit = {}
    for from_concept_id, to_concept_id, credit in conn.execute(CONCEPT_RELATIONS_SQL).fetchall():
        relation_credit[(from_concept_id, to_concept_id)] = float(credit)

    suggested_concept = {}
    for concept_type, term, outcome, concept_id in conn.execute(SUGGESTED_LINKS_SQL).fetchall():
        if outcome == "approved":
            # A person said so: from now on the word is a synonym, exactly like a taxonomy label.
            concept_by_label.setdefault((concept_type, compact_key(term)), concept_id)
        else:
            suggested_concept[(concept_type, compact_key(term))] = concept_id
    return TaxonomyCredit(concept_by_label, relation_credit, suggested_concept)
