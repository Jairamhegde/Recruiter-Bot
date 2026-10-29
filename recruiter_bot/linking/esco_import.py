"""Adds real ESCO labels to seed/taxonomy.json, from the ESCO records kept in seed/esco_snapshot.json (D-55).

Usage: python -m recruiter_bot.linking.esco_import

The snapshot holds only the ESCO concepts this prototype maps to, with each label that was left
out and why. This script is deterministic and safe to run again: it adds what is missing and
changes nothing else. A label is added as a synonym of our concept unless:
- it was excluded when the mapping was reviewed (for example "show positive attitude" is optimism, not enthusiasm);
- it is already one of the concept's labels;
- it would also belong to another concept of the same type: one label can mean only one thing,
  so a label two concepts claim is left out of both and reported.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

from recruiter_bot.ingest.text_normalizer import compact_key, normalize

SEED_DIR = Path(__file__).resolve().parent.parent.parent / "seed"
TAXONOMY_PATH = SEED_DIR / "taxonomy.json"
SNAPSHOT_PATH = SEED_DIR / "esco_snapshot.json"


def import_esco_labels(taxonomy: dict, snapshot: dict) -> tuple[dict, list[str]]:
    """The taxonomy with ESCO labels added, and a report of every label left out."""
    report = []
    concept_by_id = {concept["id"]: concept for concept in taxonomy["concepts"]}

    # Every label the taxonomy has now, by type and compact key, so clashes can be found.
    owners = defaultdict(set)
    for concept in taxonomy["concepts"]:
        for label in _labels_of(concept):
            owners[(concept["type"], compact_key(label))].add(concept["id"])

    # The labels ESCO proposes for each concept, normalized like every other term (D-02).
    proposed = {}
    for concept_id, record in snapshot["concepts"].items():
        concept = concept_by_id[concept_id]
        excluded = {normalize(label) for label in record["excluded"]}
        hidden = [normalize(label) for label in record["esco_hidden_labels"] + record["as_hidden"]]
        alternative = []
        for label in [record["esco_label"]] + record["esco_alternative_labels"]:
            slug = normalize(label)
            if slug in excluded:
                report.append(f"{concept_id}: left out {slug!r}: {record['excluded'][_original(label, record['excluded'])]}")
            elif slug in hidden:
                continue  # stored as a misspelling instead
            elif slug not in alternative:
                alternative.append(slug)
        proposed[concept_id] = (alternative, hidden)
        for slug in alternative + hidden:
            owners[(concept["type"], compact_key(slug))].add(concept_id)

    for concept_id, (alternative, hidden) in proposed.items():
        concept = concept_by_id[concept_id]
        own = {compact_key(label) for label in _labels_of(concept)}
        for field, new_labels in (("alt_labels", alternative), ("hidden_labels", hidden)):
            kept = list(concept.get(field, []))
            for slug in new_labels:
                key = compact_key(slug)
                if key in own:
                    continue
                claimed_by = owners[(concept["type"], key)] - {concept_id}
                if claimed_by:
                    report.append(f"{concept_id}: left out {slug!r}: also a label of {', '.join(sorted(claimed_by))}")
                    continue
                kept.append(slug)
                own.add(key)
            if kept:
                concept[field] = kept
        concept.setdefault("references", {})["esco_uri"] = snapshot["concepts"][concept_id]["esco_uri"]
    return taxonomy, report


def _labels_of(concept: dict) -> list[str]:
    return [concept["preferred_label"]] + concept.get("alt_labels", []) + concept.get("hidden_labels", [])


def _original(label: str, excluded: dict[str, str]) -> str:
    """The excluded entry as written in the snapshot, for its reason."""
    return next(written for written in excluded if normalize(written) == normalize(label))


def write_taxonomy(taxonomy: dict, path: Path) -> None:
    """One concept or relation per line, as the file is written by hand."""
    lines = ["{", '  "concepts": [']
    concepts = [f"    {json.dumps(concept, ensure_ascii=False)}" for concept in taxonomy["concepts"]]
    lines.append(",\n".join(concepts))
    lines.append("  ],")
    lines.append('  "relations": [')
    relations = [f"    {json.dumps(relation, ensure_ascii=False)}" for relation in taxonomy["relations"]]
    lines.append(",\n".join(relations))
    lines.append("  ]")
    lines.append("}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    taxonomy = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    before = sum(len(c.get("alt_labels", [])) + len(c.get("hidden_labels", [])) for c in taxonomy["concepts"])
    taxonomy, report = import_esco_labels(taxonomy, snapshot)
    after = sum(len(c.get("alt_labels", [])) + len(c.get("hidden_labels", [])) for c in taxonomy["concepts"])
    write_taxonomy(taxonomy, TAXONOMY_PATH)

    for line in report:
        print(line)
    with_uri = sum(1 for c in taxonomy["concepts"] if c.get("references", {}).get("esco_uri"))
    print(f"Synonyms and misspellings: {before} before, {after} now; {with_uri} concepts reference ESCO.")


if __name__ == "__main__":
    sys.exit(main())
