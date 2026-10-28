from dataclasses import dataclass
from typing import Protocol

import psycopg

from recruiter_bot.ingest.text_normalizer import compact_key


@dataclass(frozen=True)
class Credit:
    value: float
    kind: str  # "exact", "synonym", "related" or "none"


NO_CREDIT = Credit(0.0, "none")
EXACT = Credit(1.0, "exact")


class TermCredit(Protocol):
    """How much a candidate term earns toward a job term (D-32). The scorer only sees this."""

    def credit(self, concept_type: str, candidate_term: str, job_term: str) -> Credit: ...


class ExactCredit:
    """Identical terms only, compared by compact key (D-26)."""

    def credit(self, concept_type: str, candidate_term: str, job_term: str) -> Credit:
        if compact_key(candidate_term) == compact_key(job_term):
            return EXACT
        return NO_CREDIT


class TaxonomyCredit:
    """Same term or same concept 1.0, related concept per its relation, anything else 0 (D-29)."""

    def __init__(
        self,
        concept_by_label: dict[tuple[str, str], int],
        relation_credit: dict[tuple[int, int], float],
    ) -> None:
        self._concept_by_label = concept_by_label
        self._relation_credit = relation_credit

    def credit(self, concept_type: str, candidate_term: str, job_term: str) -> Credit:
        if compact_key(candidate_term) == compact_key(job_term):
            return EXACT

        candidate_concept = self._concept_by_label.get((concept_type, compact_key(candidate_term)))
        job_concept = self._concept_by_label.get((concept_type, compact_key(job_term)))
        if candidate_concept is None or job_concept is None:
            return NO_CREDIT
        if candidate_concept == job_concept:
            return Credit(1.0, "synonym")

        # "unrelated" relations are stored with credit 0, so they fall through to no credit.
        value = self._relation_credit.get((candidate_concept, job_concept), 0.0)
        if value > 0:
            return Credit(value, "related")
        return NO_CREDIT


CONCEPT_LABELS_SQL = "SELECT concept_type, compact_key, concept_id FROM concept_labels"

CONCEPT_RELATIONS_SQL = "SELECT from_concept_id, to_concept_id, credit FROM concept_relations"


def load_taxonomy_credit(conn: psycopg.Connection) -> TaxonomyCredit:
    concept_by_label = {}
    for concept_type, key, concept_id in conn.execute(CONCEPT_LABELS_SQL).fetchall():
        concept_by_label[(concept_type, key)] = concept_id

    relation_credit = {}
    for from_concept_id, to_concept_id, credit in conn.execute(CONCEPT_RELATIONS_SQL).fetchall():
        relation_credit[(from_concept_id, to_concept_id)] = float(credit)
    return TaxonomyCredit(concept_by_label, relation_credit)
