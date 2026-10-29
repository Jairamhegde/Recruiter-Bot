"""Loads and checks the labelled cases the linking stages are measured against (D-42)."""
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from recruiter_bot.ingest.taxonomy.taxonomy_reader import Taxonomy, read_taxonomy
from recruiter_bot.ingest.text_normalizer import compact_key, normalize

CASES_FILE = Path(__file__).resolve().parent / "evaluation_cases.json"
TAXONOMY_FILE = Path(__file__).resolve().parent.parent.parent / "seed" / "taxonomy.json"

EXPECTATIONS = ("same", "related", "none", "negated")
# About 60% of the cases tune the thresholds; the other 40% judge them.
TEST_SHARE_PERCENT = 40


@dataclass(frozen=True)
class EvaluationCase:
    concept_type: str
    term: str
    expect: str
    concept: str | None
    note: str | None

    @property
    def split(self) -> str:
        """'calibration' or 'test', from a hash of the word, so nobody picks which case lands where."""
        bucket = int(hashlib.sha256(f"{self.concept_type}:{self.term}".encode()).hexdigest(), 16) % 100
        return "test" if bucket < TEST_SHARE_PERCENT else "calibration"


def load_cases(cases_file: Path = CASES_FILE, taxonomy: Taxonomy | None = None) -> list[EvaluationCase]:
    """Every case, checked against the taxonomy. A mistake in the file fails here, not in a result."""
    taxonomy = taxonomy or read_taxonomy(TAXONOMY_FILE)
    concepts = {(concept.concept_type, concept.slug) for concept in taxonomy.concepts}
    labels = {(label.concept_type, compact_key(label.label)) for label in taxonomy.labels}

    cases = []
    seen = set()
    for index, raw_case in enumerate(json.loads(cases_file.read_text(encoding="utf-8"))["cases"]):
        where = f"case #{index} ({raw_case.get('term')!r})"
        case = EvaluationCase(
            concept_type=raw_case["type"],
            term=normalize(raw_case["term"]),
            expect=raw_case["expect"],
            concept=raw_case.get("concept"),
            note=raw_case.get("note"),
        )
        if case.term != raw_case["term"]:
            raise ValueError(f"{where}: write the term normalized, as {case.term!r}")
        if case.expect not in EXPECTATIONS:
            raise ValueError(f"{where}: expect must be one of {list(EXPECTATIONS)}")
        needs_concept = case.expect in ("same", "related")
        if needs_concept and (case.concept_type, case.concept) not in concepts:
            raise ValueError(f"{where}: no {case.concept_type} concept {case.concept!r} in the taxonomy")
        if not needs_concept and case.concept is not None:
            raise ValueError(f"{where}: a '{case.expect}' case has no concept")
        # A word the taxonomy already knows never reaches the model stages, so it would test nothing.
        if (case.concept_type, compact_key(case.term)) in labels:
            raise ValueError(f"{where}: {case.term!r} is already a taxonomy label")
        if (case.concept_type, case.term) in seen:
            raise ValueError(f"{where}: listed twice")
        seen.add((case.concept_type, case.term))
        cases.append(case)
    return cases


def describe(cases: list[EvaluationCase]) -> str:
    counts = Counter((case.split, case.concept_type, case.expect) for case in cases)
    lines = [f"{len(cases)} cases"]
    for split in ("calibration", "test"):
        for concept_type in ("skill", "trait"):
            parts = [f"{expect} {counts[(split, concept_type, expect)]}" for expect in EXPECTATIONS]
            lines.append(f"  {split:<11} {concept_type:<5}  " + ", ".join(parts))
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe(load_cases()))
