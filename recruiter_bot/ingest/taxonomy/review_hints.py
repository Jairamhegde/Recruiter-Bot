from collections import defaultdict
from dataclasses import dataclass

from recruiter_bot.ingest.taxonomy.taxonomy_reader import ConceptLabel

# Review hints only: they never give credit (D-31).
NEGATION_WORDS = {"not", "non", "no", "un", "anti", "never", "without"}


@dataclass(frozen=True)
class ConceptHint:
    term: str
    concept_type: str
    concept: str
    like: list[str]


def suggest_concepts(unknown_terms: list[str], concept_type: str, labels: list[ConceptLabel]) -> list[ConceptHint]:
    """Unknown terms that share a first word with a concept's visible labels, one hint per concept."""
    labels_by_first_word = defaultdict(list)
    for label in labels:
        # Hidden labels are misspellings; a hint should point at real words.
        if label.concept_type == concept_type and label.label_type != "hidden":
            labels_by_first_word[_first_word(label.label)].append(label)

    hints = []
    for term in sorted(set(unknown_terms)):
        if _first_word(term) in NEGATION_WORDS:
            continue
        like_by_concept = defaultdict(list)
        for label in labels_by_first_word.get(_first_word(term), []):
            if _is_negated(term) == _is_negated(label.label):
                like_by_concept[label.concept_slug].append(label.label)
        for concept, like in sorted(like_by_concept.items()):
            hints.append(ConceptHint(term, concept_type, concept, sorted(like)))
    return hints


def _first_word(slug: str) -> str:
    return slug.split("-")[0]


def _is_negated(slug: str) -> bool:
    return not NEGATION_WORDS.isdisjoint(slug.split("-"))
