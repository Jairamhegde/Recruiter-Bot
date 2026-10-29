"""Stage 4: find the concepts closest in meaning to an unknown word (D-43).

Each concept is represented by a few short texts (its labels, its name, its description).
Every text is embedded once, when the index is built. A search embeds the unknown word,
compares it with every text of the same type, and gives each concept the similarity of
its closest text. Search only proposes candidates; stage 5 decides whether they are right.
"""
from dataclasses import dataclass

import numpy

from recruiter_bot.ingest.taxonomy.taxonomy_reader import Taxonomy
from recruiter_bot.linking.models import EmbeddingModel

# D-43: chosen on the calibration cases. Ten candidates keep the right concept in reach for 95% of them;
# wrong candidates cost only a check in stage 5, while a missing one can never be linked.
CANDIDATE_COUNT = 10


@dataclass(frozen=True)
class ConceptText:
    concept_type: str
    concept: str  # concept slug
    text: str     # plain words, as the model reads them
    kind: str     # "label", "name" or "description"


@dataclass(frozen=True)
class Candidate:
    concept: str
    similarity: float   # cosine similarity, -1 to 1
    closest_text: str   # the text of the concept that came closest, for explaining the result


def phrase_of(slug: str) -> str:
    """'calm-under-pressure' -> 'calm under pressure': the models read words, not slugs."""
    return slug.replace("-", " ")


def in_context(concept_type: str, slug: str) -> str:
    """A word inside a short sentence: a lone adjective like 'meticulous' gives a small model little to go on."""
    if concept_type == "trait":
        return f"a person who is {phrase_of(slug)}"
    return f"the skill of {phrase_of(slug)}"


def texts_from_taxonomy(
    taxonomy: Taxonomy, include_names: bool, include_descriptions: bool, with_context: bool,
) -> list[ConceptText]:
    """The texts that represent each concept. Hidden labels are misspellings, so they're left out."""

    def as_text(concept_type: str, slug: str) -> str:
        return in_context(concept_type, slug) if with_context else phrase_of(slug)

    texts = []
    for label in taxonomy.labels:
        if label.label_type != "hidden":
            texts.append(ConceptText(label.concept_type, label.concept_slug, as_text(label.concept_type, label.label), "label"))
    for concept in taxonomy.concepts:
        if include_names:
            texts.append(ConceptText(concept.concept_type, concept.slug, as_text(concept.concept_type, concept.slug), "name"))
        if include_descriptions and concept.description:
            texts.append(ConceptText(concept.concept_type, concept.slug, concept.description, "description"))
    return texts


class ConceptIndex:
    def __init__(self, embedding_model: EmbeddingModel, texts: list[ConceptText], with_context: bool) -> None:
        self._embedding_model = embedding_model
        self._texts = texts
        self._with_context = with_context  # queries must be phrased the same way as the texts
        self._vectors = embedding_model.embed([text.text for text in texts])

    def closest(self, concept_type: str, term: str, limit: int = CANDIDATE_COUNT) -> list[Candidate]:
        """The `limit` concepts of this type closest in meaning to the term, best first."""
        query = in_context(concept_type, term) if self._with_context else phrase_of(term)
        query_vector = self._embedding_model.embed([query])[0]
        similarities = self._vectors @ query_vector  # every vector has length 1, so this is cosine similarity

        best_by_concept: dict[str, Candidate] = {}
        for text, similarity in zip(self._texts, similarities):
            if text.concept_type != concept_type:
                continue
            current = best_by_concept.get(text.concept)
            if current is None or similarity > current.similarity:
                best_by_concept[text.concept] = Candidate(text.concept, float(similarity), text.text)

        ranked = sorted(best_by_concept.values(), key=lambda candidate: (-candidate.similarity, candidate.concept))
        return ranked[:limit]


def build_concept_index(embedding_model: EmbeddingModel, taxonomy: Taxonomy) -> ConceptIndex:
    """The production setting (D-43): labels, names and descriptions, with words in short sentences."""
    texts = texts_from_taxonomy(taxonomy, include_names=True, include_descriptions=True, with_context=True)
    return ConceptIndex(embedding_model, texts, with_context=True)
