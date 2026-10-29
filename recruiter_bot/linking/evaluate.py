"""Measures the linking stages on the labelled cases. Usage: python -m recruiter_bot.linking.evaluate search|verify|calibrate|test"""
import sys
import time
from dataclasses import dataclass

from recruiter_bot.ingest.taxonomy.taxonomy_reader import read_taxonomy
from recruiter_bot.linking.decision import THRESHOLDS, Thresholds, decide
from recruiter_bot.linking.concept_search import ConceptIndex, build_concept_index, texts_from_taxonomy
from recruiter_bot.linking.evaluation_cases import TAXONOMY_FILE, EvaluationCase, load_cases
from recruiter_bot.linking.models import load_models
from recruiter_bot.linking.verification import (
    CandidateVerifier,
    Verification,
    labels_by_concept_from_taxonomy,
)


@dataclass(frozen=True)
class SearchScore:
    cases: int
    found_at: dict[int, int]  # how many cases had the expected concept within the first N candidates

    def describe(self) -> str:
        shares = ", ".join(f"top {limit} {count / self.cases:.0%}" for limit, count in self.found_at.items())
        return f"{self.cases} cases with a known concept: {shares}"


def score_search(index: ConceptIndex, cases: list[EvaluationCase]) -> tuple[SearchScore, list[str]]:
    """How often the expected concept is among the first 1, 3, 5 and 10 candidates, plus the top-5 misses."""
    with_concept = [case for case in cases if case.concept is not None]
    found = {1: 0, 3: 0, 5: 0, 10: 0}
    misses = []
    for case in with_concept:
        ranked = [candidate.concept for candidate in index.closest(case.concept_type, case.term, limit=10)]
        for limit in found:
            if case.concept in ranked[:limit]:
                found[limit] += 1
        if case.concept not in ranked[:5]:
            misses.append(f"{case.term} -> expected {case.concept}, got {', '.join(ranked[:5])}")
    return SearchScore(len(with_concept), found), misses


def evaluate_search() -> None:
    """Compares the ways of representing a concept, on the calibration cases only."""
    models = load_models()
    if models is None:
        raise SystemExit("Model files are missing: run python -m recruiter_bot.linking.model_files")
    taxonomy = read_taxonomy(TAXONOMY_FILE)
    calibration = [case for case in load_cases(taxonomy=taxonomy) if case.split == "calibration"]

    variants = {
        "A: labels": (False, False, False),
        "B: labels + names": (True, False, False),
        "C: labels + names + descriptions": (True, True, False),
        "D: C, words in short sentences": (True, True, True),
    }
    for name, (include_names, include_descriptions, with_context) in variants.items():
        started = time.perf_counter()
        texts = texts_from_taxonomy(taxonomy, include_names, include_descriptions, with_context)
        index = ConceptIndex(models.embedding, texts, with_context)
        built_ms = (time.perf_counter() - started) * 1000
        score, misses = score_search(index, calibration)
        print(f"{name:<34} {score.describe()}   (index built in {built_ms:.0f} ms)")
        for miss in misses:
            print(f"    missed: {miss}")


@dataclass(frozen=True)
class LabelledVerification:
    case: EvaluationCase
    verification: Verification
    kind: str  # "synonym", "related" or "other"


def area_under_curve(positive_scores: list[float], negative_scores: list[float]) -> float:
    """The chance a random positive outscores a random negative: 1.0 is perfect, 0.5 a coin flip."""
    wins = 0.0
    for positive in positive_scores:
        for negative in negative_scores:
            if positive > negative:
                wins += 1.0
            elif positive == negative:
                wins += 0.5
    return wins / (len(positive_scores) * len(negative_scores))


def median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def verify_calibration_cases() -> list[LabelledVerification]:
    """Every candidate of every calibration case, verified and labelled with what it should be."""
    models = load_models()
    if models is None:
        raise SystemExit("Model files are missing: run python -m recruiter_bot.linking.model_files")
    taxonomy = read_taxonomy(TAXONOMY_FILE)
    index = build_concept_index(models.embedding, taxonomy)
    verifier = CandidateVerifier(models.nli, labels_by_concept_from_taxonomy(taxonomy))

    labelled = []
    for case in load_cases(taxonomy=taxonomy):
        # Negated words are decided by the rules and never reach this stage.
        if case.split != "calibration" or case.expect == "negated":
            continue
        candidates = index.closest(case.concept_type, case.term)
        for verification in verifier.verify(case.concept_type, case.term, candidates):
            if verification.concept == case.concept and case.expect == "same":
                kind = "synonym"
            elif verification.concept == case.concept and case.expect == "related":
                kind = "related"
            else:
                kind = "other"
            labelled.append(LabelledVerification(case, verification, kind))
    return labelled


def evaluate_verification() -> None:
    """How well each signal separates synonyms from everything else, on the calibration cases."""
    started = time.perf_counter()
    labelled = verify_calibration_cases()
    print(f"{len(labelled)} candidate pairs verified in {time.perf_counter() - started:.1f} s\n")

    signals = {
        "similarity (stage 4 alone)": lambda v: v.similarity,
        "entailment, one direction": lambda v: v.implies,
        "mutual entailment": lambda v: v.mutual_entailment,
        "mutual entailment x (1 - contradiction)": lambda v: v.mutual_entailment * (1 - v.contradiction),
    }
    synonyms = [item.verification for item in labelled if item.kind == "synonym"]
    not_synonyms = [item.verification for item in labelled if item.kind != "synonym"]
    print(f"Separating {len(synonyms)} synonyms from {len(not_synonyms)} other pairs (AUC):")
    for name, signal in signals.items():
        auc = area_under_curve([signal(v) for v in synonyms], [signal(v) for v in not_synonyms])
        print(f"  {name:<42} {auc:.3f}")

    print("\nMedians by kind of pair:")
    for kind in ("synonym", "related", "other"):
        group = [item.verification for item in labelled if item.kind == kind]
        print(f"  {kind:<8} ({len(group):>3})  similarity {median([v.similarity for v in group]):.2f}   "
              f"mutual entailment {median([v.mutual_entailment for v in group]):.2f}   "
              f"contradiction {median([v.contradiction for v in group]):.2f}")

    print("\nOpposites: the candidate most similar to each word, and what NLI says about it:")
    for item in labelled:
        note = item.case.note or ""
        if note.startswith("opposite") and item.verification.concept == _most_similar(labelled, item.case):
            v = item.verification
            print(f"  {item.case.term:<12} vs {v.concept:<20} similarity {v.similarity:.2f}   "
                  f"mutual entailment {v.mutual_entailment:.2f}   contradiction {v.contradiction:.2f}")


def _most_similar(labelled: list[LabelledVerification], case: EvaluationCase) -> str:
    same_case = [item.verification for item in labelled if item.case == case]
    return max(same_case, key=lambda v: v.similarity).concept


@dataclass(frozen=True)
class DecisionScore:
    words: int
    auto_correct: list[str]    # "same" words linked to their concept
    auto_wrong: list[str]      # any other automatic link
    review: int
    review_with_right_concept: int  # reviews of same/related words whose concept is among the suggestions
    review_needing_concept: int     # reviews of same/related words
    no_match: int

    @property
    def precision(self) -> float:
        """Of the automatic links, the share that were right. 1.0 when there were none."""
        made = len(self.auto_correct) + len(self.auto_wrong)
        return 1.0 if made == 0 else len(self.auto_correct) / made

    def describe(self, same_words: int) -> str:
        return "\n".join([
            f"  automatic links: {len(self.auto_correct)} right, {len(self.auto_wrong)} wrong "
            f"(precision {self.precision:.0%}); {len(self.auto_correct)} of {same_words} synonyms found automatically",
            f"  sent to review:  {self.review} words; the right concept was among the suggestions "
            f"for {self.review_with_right_concept} of {self.review_needing_concept} that have one",
            f"  no match:        {self.no_match} words",
        ])


def verify_cases(split: str) -> list[tuple[EvaluationCase, list[Verification]]]:
    """The verified candidates of every case in one split. Negated words never reach the models."""
    models = load_models()
    if models is None:
        raise SystemExit("Model files are missing: run python -m recruiter_bot.linking.model_files")
    taxonomy = read_taxonomy(TAXONOMY_FILE)
    index = build_concept_index(models.embedding, taxonomy)
    verifier = CandidateVerifier(models.nli, labels_by_concept_from_taxonomy(taxonomy))

    results = []
    for case in load_cases(taxonomy=taxonomy):
        if case.split == split and case.expect != "negated":
            candidates = index.closest(case.concept_type, case.term)
            results.append((case, verifier.verify(case.concept_type, case.term, candidates)))
    return results


def score_decisions(results: list[tuple[EvaluationCase, list[Verification]]], thresholds: Thresholds) -> DecisionScore:
    auto_correct, auto_wrong = [], []
    review = review_with_right_concept = review_needing_concept = no_match = 0
    for case, verifications in results:
        # The automatic rule is measured even while it is switched off in production.
        decision = decide(verifications, thresholds, automatic_linking=True)
        if decision.outcome == "auto_link":
            if case.expect == "same" and decision.concept == case.concept:
                auto_correct.append(f"{case.term} -> {decision.concept}")
            else:
                auto_wrong.append(f"{case.term} -> {decision.concept} (expected {case.expect} "
                                  f"{case.concept or ''}; {decision.explain()})".replace(" )", ")"))
        elif decision.outcome == "review":
            review += 1
            if case.concept is not None:
                review_needing_concept += 1
                if case.concept in decision.suggestions:
                    review_with_right_concept += 1
        else:
            no_match += 1
    return DecisionScore(len(results), auto_correct, auto_wrong, review,
                         review_with_right_concept, review_needing_concept, no_match)


MINIMUM_PRECISION = 0.98
GRID_MUTUAL_ENTAILMENT = [0.50, 0.60, 0.70, 0.80, 0.85, 0.90, 0.95, 0.97, 0.98, 0.99, 0.995]
GRID_SIMILARITY = [0.80, 0.82, 0.84, 0.86, 0.88, 0.90, 0.92, 0.94]
GRID_MARGIN = [0.0, 0.02, 0.05, 0.10, 0.20, 0.30, 0.50]


def calibrate() -> None:
    """Chooses thresholds with no wrong automatic links, then the most right ones."""
    results = verify_cases("calibration")
    same_words = sum(1 for case, _ in results if case.expect == "same")

    best_thresholds = None
    best_score = None
    for mutual in GRID_MUTUAL_ENTAILMENT:
        for similarity in GRID_SIMILARITY:
            for margin in GRID_MARGIN:
                thresholds = Thresholds(mutual, similarity, margin)
                score = score_decisions(results, thresholds)
                if score.precision < MINIMUM_PRECISION:
                    continue
                if best_score is None or _better(score, thresholds, best_score, best_thresholds):
                    best_thresholds, best_score = thresholds, score

    print(f"{len(results)} calibration words; {len(GRID_MUTUAL_ENTAILMENT) * len(GRID_SIMILARITY) * len(GRID_MARGIN)} "
          f"settings tried")
    print(f"chosen: {best_thresholds}")
    print(best_score.describe(same_words))
    for link in best_score.auto_correct:
        print(f"    linked: {link}")
    for link in best_score.auto_wrong:
        print(f"    WRONG:  {link}")


def _better(score: DecisionScore, thresholds: Thresholds, best_score: DecisionScore, best_thresholds: Thresholds) -> bool:
    if len(score.auto_correct) != len(best_score.auto_correct):
        return len(score.auto_correct) > len(best_score.auto_correct)
    stricter = (thresholds.mutual_entailment, thresholds.similarity, thresholds.margin)
    current = (best_thresholds.mutual_entailment, best_thresholds.similarity, best_thresholds.margin)
    return stricter > current


def test() -> None:
    """Judges the chosen THRESHOLDS once on the test cases, which no choice was based on."""
    results = verify_cases("test")
    same_words = sum(1 for case, _ in results if case.expect == "same")
    score = score_decisions(results, THRESHOLDS)
    print(f"{len(results)} test words, thresholds {THRESHOLDS}")
    print(score.describe(same_words))
    for link in score.auto_correct:
        print(f"    linked: {link}")
    for link in score.auto_wrong:
        print(f"    WRONG:  {link}")


if __name__ == "__main__":
    commands = {"search": evaluate_search, "verify": evaluate_verification, "calibrate": calibrate, "test": test}
    if len(sys.argv) == 2 and sys.argv[1] in commands:
        commands[sys.argv[1]]()
    else:
        print(__doc__)
        raise SystemExit(2)
