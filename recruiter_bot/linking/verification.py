"""Stage 5: check each candidate concept with the NLI model, in both directions."""
from dataclasses import dataclass

from recruiter_bot.ingest.taxonomy.taxonomy_reader import Taxonomy
from recruiter_bot.linking.concept_search import Candidate, phrase_of
from recruiter_bot.linking.models import NliModel


@dataclass(frozen=True)
class Verification:
    concept: str
    similarity: float     # from stage 4
    implies: float        # probability the unknown word implies the concept's label
    implied_by: float     # probability the concept's label implies the unknown word
    contradiction: float  # the higher contradiction probability of the two directions
    closest_label: str    # the label that agreed best with the unknown word

    @property
    def mutual_entailment(self) -> float:
        """How strongly both directions hold; high only for synonyms."""
        return min(self.implies, self.implied_by)


def as_sentence(concept_type: str, slug: str) -> str:
    """NLI models were trained on sentences, so words are judged inside one."""
    if concept_type == "trait":
        return f"This person is {phrase_of(slug)}."
    return f"This person is skilled in {phrase_of(slug)}."


def labels_by_concept_from_taxonomy(taxonomy: Taxonomy) -> dict[tuple[str, str], list[str]]:
    """(type, concept) -> its preferred and alternative labels. Hidden labels are misspellings, so they're left out."""
    labels: dict[tuple[str, str], list[str]] = {}
    for label in taxonomy.labels:
        if label.label_type != "hidden":
            labels.setdefault((label.concept_type, label.concept_slug), []).append(label.label)
    return labels


class CandidateVerifier:
    def __init__(self, nli_model: NliModel, labels_by_concept: dict[tuple[str, str], list[str]]) -> None:
        self._nli_model = nli_model
        self._labels_by_concept = labels_by_concept

    def verify(self, concept_type: str, term: str, candidates: list[Candidate]) -> list[Verification]:
        """One verification per candidate, in the same order."""
        term_sentence = as_sentence(concept_type, term)
        verifications = []
        for candidate in candidates:
            best = None
            for label in self._labels_by_concept.get((concept_type, candidate.concept), []):
                label_sentence = as_sentence(concept_type, label)
                forward, backward = self._nli_model.judge([(term_sentence, label_sentence), (label_sentence, term_sentence)])
                verification = Verification(
                    concept=candidate.concept,
                    similarity=candidate.similarity,
                    implies=forward.entailment,
                    implied_by=backward.entailment,
                    contradiction=max(forward.contradiction, backward.contradiction),
                    closest_label=label,
                )
                # A concept with several labels keeps the label that agrees best in both directions.
                if best is None or verification.mutual_entailment > best.mutual_entailment:
                    best = verification
            if best is not None:
                verifications.append(best)
        return verifications
