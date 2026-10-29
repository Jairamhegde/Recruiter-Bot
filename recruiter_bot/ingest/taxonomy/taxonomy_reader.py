import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from recruiter_bot.ingest.text_normalizer import compact_key, normalize_required

CONCEPT_TYPES = ("skill", "trait")
# Credit comes from the relation type, never from the entry.
RELATION_CREDIT = {"related": 0.5, "unrelated": 0.0}
CONCEPT_KEYS = {"id", "type", "preferred_label", "alt_labels", "hidden_labels", "description", "references"}
REFERENCE_KEYS = {"esco_uri", "onet_element_id"}
LABEL_FIELDS = {"preferred_label": "preferred", "alt_labels": "alternative", "hidden_labels": "hidden"}


@dataclass(frozen=True)
class Concept:
    slug: str
    concept_type: str
    description: str | None
    esco_uri: str | None
    onet_element_id: str | None


@dataclass(frozen=True)
class ConceptLabel:
    concept_slug: str
    concept_type: str
    label: str
    label_type: str


@dataclass(frozen=True)
class ConceptRelation:
    from_slug: str
    to_slug: str
    concept_type: str
    relation: str
    credit: float


@dataclass(frozen=True)
class Taxonomy:
    concepts: list[Concept]
    labels: list[ConceptLabel]
    relations: list[ConceptRelation]


def read_taxonomy(path: Path) -> Taxonomy:
    return extract_taxonomy(json.loads(path.read_text(encoding="utf-8")))


def extract_taxonomy(data: Any) -> Taxonomy:
    """Validates the taxonomy file. Any bad entry fails the whole load."""
    if not isinstance(data, dict) or set(data) != {"concepts", "relations"}:
        raise ValueError("taxonomy: expected an object with keys ['concepts', 'relations']")
    concepts, labels = _extract_concepts(data["concepts"])
    relations = _extract_relations(data["relations"], {(concept.concept_type, concept.slug) for concept in concepts})
    return Taxonomy(concepts, labels, relations)


def _extract_concepts(entries: Any) -> tuple[list[Concept], list[ConceptLabel]]:
    if not isinstance(entries, list):
        raise ValueError("concepts: expected a list of concepts")

    concepts = []
    labels = []
    concept_index_by_key = {}
    label_owner_by_key = {}
    for index, entry in enumerate(entries):
        where = f"concepts[{index}]"
        if not isinstance(entry, dict) or not {"id", "type", "preferred_label"} <= set(entry) <= CONCEPT_KEYS:
            raise ValueError(f"{where}: expected 'id', 'type', 'preferred_label' and optionally {sorted(CONCEPT_KEYS)}")

        concept_type = entry["type"]
        if concept_type not in CONCEPT_TYPES:
            raise ValueError(f"{where}: unknown type {concept_type!r}, expected one of {list(CONCEPT_TYPES)}")
        slug = normalize_required(_string(entry["id"], f"{where}.id"), f"{where}.id")
        if (concept_type, slug) in concept_index_by_key:
            raise ValueError(f"{where}: {concept_type} concept {slug!r} is already defined in "
                             f"concepts[{concept_index_by_key[(concept_type, slug)]}]")
        concept_index_by_key[(concept_type, slug)] = index

        references = entry.get("references", {})
        if not isinstance(references, dict) or not set(references) <= REFERENCE_KEYS:
            raise ValueError(f"{where}.references: expected an object with only {sorted(REFERENCE_KEYS)}")
        concepts.append(Concept(
            slug=slug,
            concept_type=concept_type,
            description=_optional_string(entry.get("description"), f"{where}.description"),
            esco_uri=_optional_string(references.get("esco_uri"), f"{where}.references.esco_uri"),
            onet_element_id=_optional_string(references.get("onet_element_id"), f"{where}.references.onet_element_id"),
        ))

        for field, label_type in LABEL_FIELDS.items():
            raw_labels = [entry[field]] if field == "preferred_label" else entry.get(field, [])
            if not isinstance(raw_labels, list):
                raise ValueError(f"{where}.{field}: expected a list of strings")
            for raw_label in raw_labels:
                label = normalize_required(_string(raw_label, f"{where}.{field}"), f"{where}.{field}")
                # Compact keys, because that's how labels are matched.
                owner_key = (concept_type, compact_key(label))
                if owner_key in label_owner_by_key:
                    raise ValueError(f"{where}: {concept_type} label {label!r} already belongs to "
                                     f"{label_owner_by_key[owner_key]}")
                label_owner_by_key[owner_key] = slug
                labels.append(ConceptLabel(slug, concept_type, label, label_type))
    return concepts, labels


def _extract_relations(entries: Any, concept_keys: set[tuple[str, str]]) -> list[ConceptRelation]:
    """Each entry becomes two directed relations, one per direction."""
    if not isinstance(entries, list):
        raise ValueError("relations: expected a list of relations")

    relations = []
    index_by_pair = {}
    for index, entry in enumerate(entries):
        where = f"relations[{index}]"
        if not isinstance(entry, dict) or set(entry) != {"type", "between", "relation"}:
            raise ValueError(f"{where}: expected an object with 'type', 'between' and 'relation'")

        concept_type = entry["type"]
        if concept_type not in CONCEPT_TYPES:
            raise ValueError(f"{where}: unknown type {concept_type!r}, expected one of {list(CONCEPT_TYPES)}")
        relation = entry["relation"]
        if relation not in RELATION_CREDIT:
            raise ValueError(f"{where}: unknown relation {relation!r}, expected one of {list(RELATION_CREDIT)}")

        between = entry["between"]
        if not isinstance(between, list) or len(between) != 2 or not all(isinstance(slug, str) for slug in between):
            raise ValueError(f"{where}: 'between' must be a list of two concept ids")
        first = normalize_required(between[0], f"{where} concept")
        second = normalize_required(between[1], f"{where} concept")
        if first == second:
            raise ValueError(f"{where}: {first!r} is related to itself")
        for slug in (first, second):
            if (concept_type, slug) not in concept_keys:
                raise ValueError(f"{where}: no {concept_type} concept {slug!r}")

        pair = (concept_type, frozenset((first, second)))
        if pair in index_by_pair:
            raise ValueError(f"{where}: {first!r} and {second!r} are already related in relations[{index_by_pair[pair]}]")
        index_by_pair[pair] = index

        credit = RELATION_CREDIT[relation]
        relations.append(ConceptRelation(first, second, concept_type, relation, credit))
        relations.append(ConceptRelation(second, first, concept_type, relation, credit))
    return relations


def _string(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{where}: expected a string")
    return value


def _optional_string(value: Any, where: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError(f"{where}: expected a non-empty string or null")
    return value.strip()
