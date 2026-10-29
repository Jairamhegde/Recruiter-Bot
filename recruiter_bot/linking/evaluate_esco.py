"""Judges word placement on ESCO's own labels. Usage: python -m recruiter_bot.linking.evaluate_esco"""
import hashlib
import json
import math
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from recruiter_bot.ingest import read_taxonomy
from recruiter_bot.ingest.text_normalizer import normalize, root_key
from recruiter_bot.linking.concept_search import build_concept_index
from recruiter_bot.linking.decision import decide
from recruiter_bot.linking.esco_import import SNAPSHOT_PATH, TAXONOMY_PATH
from recruiter_bot.linking.models import load_models
from recruiter_bot.linking.verification import CandidateVerifier, labels_by_concept_from_taxonomy

HELD_OUT_PERCENT = 20


@dataclass(frozen=True)
class Case:
    concept_type: str
    term: str
    expected: str | None   # the concept for a held-out synonym; None for a look-alike


@dataclass(frozen=True)
class Outcome:
    case: Case
    layer: str             # "rules", "model" or "none"
    decision: str          # "credit", "review" or "nothing"
    concept: str | None    # the concept credited, or the first review suggestion


def held_out(concept_type: str, term: str) -> bool:
    bucket = int(hashlib.sha256(f"esco:{concept_type}:{term}".encode()).hexdigest(), 16) % 100
    return bucket < HELD_OUT_PERCENT


def build_cases(taxonomy, snapshot) -> tuple[list[Case], set[tuple[str, str]]]:
    type_of = {concept.slug: concept.concept_type for concept in taxonomy.concepts}
    imported = {}
    for concept_id, record in snapshot["concepts"].items():
        for label in [record["esco_label"]] + record["esco_alternative_labels"]:
            imported[(type_of[concept_id], normalize(label))] = concept_id

    labels_now = {(label.concept_type, label.label): label.concept_slug for label in taxonomy.labels}
    positives = [Case(concept_type, term, concept) for (concept_type, term), concept in labels_now.items()
                 if imported.get((concept_type, term)) == concept and held_out(concept_type, term)]
    hidden = {(case.concept_type, case.term) for case in positives}

    chosen_uris = {record["esco_uri"] for record in snapshot["concepts"].values()}
    lookalikes = {}
    for concept_id, record in snapshot["concepts"].items():
        for hit in record["lookalikes"]:
            term = normalize(hit["title"])
            if hit["uri"] in chosen_uris or (type_of[concept_id], term) in labels_now:
                continue
            lookalikes[(type_of[concept_id], term)] = Case(type_of[concept_id], term, None)
    return positives + sorted(lookalikes.values(), key=lambda case: case.term), hidden


def evaluate(cases: list[Case], taxonomy, models) -> list[Outcome]:
    index = build_concept_index(models.embedding, taxonomy)
    verifier = CandidateVerifier(models.nli, labels_by_concept_from_taxonomy(taxonomy))
    concepts_by_root = {}
    for label in taxonomy.labels:
        if label.label_type != "hidden":
            concepts_by_root.setdefault((label.concept_type, root_key(label.label)), set()).add(label.concept_slug)

    outcomes = []
    for case in cases:
        # The word-root rule (the typo rule needs the database and is left out here).
        by_root = concepts_by_root.get((case.concept_type, root_key(case.term)), set())
        if len(by_root) == 1:
            outcomes.append(Outcome(case, "rules", "credit", next(iter(by_root))))
            continue
        decision = decide(verifier.verify(case.concept_type, case.term, index.closest(case.concept_type, case.term)),
                          automatic_linking=True)
        if decision.outcome == "auto_link":
            outcomes.append(Outcome(case, "model", "credit", decision.concept))
        elif decision.outcome == "review":
            outcomes.append(Outcome(case, "model", "review", decision.suggestions[0]))
        else:
            outcomes.append(Outcome(case, "none", "nothing", None))
    return outcomes


def wilson(successes: int, total: int) -> str:
    """The 95% confidence interval of a proportion; honest about how little a small sample proves."""
    if total == 0:
        return "n/a"
    z = 1.96
    p = successes / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return f"{successes}/{total} = {p:.0%} (95% interval {max(0.0, centre - spread):.0%} to {min(1.0, centre + spread):.0%})"


def report(outcomes: list[Outcome]) -> None:
    positives = [o for o in outcomes if o.case.expected is not None]
    lookalikes = [o for o in outcomes if o.case.expected is None]
    credited = [o for o in outcomes if o.decision == "credit"]
    right_credit = [o for o in credited if o.concept == o.case.expected]

    print(f"Held-out ESCO synonyms: {len(positives)}; ESCO look-alike concepts: {len(lookalikes)}\n")
    print("Words that earned credit automatically (the number that protects scores):")
    print(f"  precision: {wilson(len(right_credit), len(credited))}")
    for layer in ("rules", "model"):
        in_layer = [o for o in credited if o.layer == layer]
        print(f"    {layer:<6} {wilson(sum(o.concept == o.case.expected for o in in_layer), len(in_layer))}")
    print("\nHeld-out synonyms found again:")
    print(f"  with credit:              {wilson(sum(o.decision == 'credit' and o.concept == o.case.expected for o in positives), len(positives))}")
    reviewed = [o for o in positives if o.decision == "review"]
    print(f"  sent to review:           {len(reviewed)}, right concept suggested first in {sum(o.concept == o.case.expected for o in reviewed)}")
    print(f"  missed entirely:          {sum(o.decision == 'nothing' for o in positives)}")
    print("\nLook-alikes (should earn nothing):")
    print(f"  wrongly credited:         {wilson(sum(o.decision == 'credit' for o in lookalikes), len(lookalikes))}")
    print(f"  sent to review (a person decides): {sum(o.decision == 'review' for o in lookalikes)}")
    wrong = [o for o in credited if o.concept != o.case.expected]
    if wrong:
        print("\nEvery wrong automatic credit:")
        for o in wrong:
            print(f"  {o.case.concept_type} {o.case.term!r} -> {o.concept} by {o.layer} (expected {o.case.expected or 'nothing'})")


def main() -> None:
    models = load_models()
    if models is None:
        print("The model files are missing: python -m recruiter_bot.linking.model_files")
        raise SystemExit(1)
    taxonomy = read_taxonomy(TAXONOMY_PATH)
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    cases, hidden = build_cases(taxonomy, snapshot)
    # The system must not see the held-out synonyms: they are taken out of its taxonomy.
    reduced = replace(taxonomy, labels=[label for label in taxonomy.labels
                                        if (label.concept_type, label.label) not in hidden])
    report(evaluate(cases, reduced, models))


if __name__ == "__main__":
    sys.exit(main())
