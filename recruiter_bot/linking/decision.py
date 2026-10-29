"""Stage 6: one decision per unknown word: auto_link, review or no_match."""
from dataclasses import dataclass

from recruiter_bot.linking.verification import Verification

SUGGESTION_COUNT = 3
# A word goes to review when it more likely than not implies the concept, in either direction.
REVIEW_ENTAILMENT = 0.5

# Off: 67% precision on held-out words, against a 98% target.
AUTOMATIC_LINKING = False


@dataclass(frozen=True)
class Thresholds:
    mutual_entailment: float  # both directions must imply each other at least this strongly
    similarity: float         # and the meanings must be at least this close
    margin: float             # and the best candidate must beat the second by at least this much


# Calibrated thresholds: link only when one concept clearly beats the rest.
THRESHOLDS = Thresholds(mutual_entailment=0.50, similarity=0.86, margin=0.30)


@dataclass(frozen=True)
class LinkDecision:
    outcome: str                   # "auto_link", "review" or "no_match"
    concept: str | None            # the concept for auto_link
    suggestions: list[str]         # for review, best first
    best: Verification | None      # the evidence behind the decision

    def explain(self) -> str:
        if self.best is None:
            return "no candidates"
        return (f"best {self.best.concept} via '{self.best.closest_label}': mutual entailment "
                f"{self.best.mutual_entailment:.2f}, similarity {self.best.similarity:.2f}")


def rank(verifications: list[Verification]) -> list[Verification]:
    """Best agreement in both directions first; similarity breaks ties."""
    return sorted(verifications, key=lambda v: (-v.mutual_entailment, -v.similarity, v.concept))


def decide(
    verifications: list[Verification],
    thresholds: Thresholds = THRESHOLDS,
    automatic_linking: bool = AUTOMATIC_LINKING,
) -> LinkDecision:
    ranked = rank(verifications)
    if not ranked:
        return LinkDecision("no_match", None, [], None)

    best = ranked[0]
    runner_up_score = ranked[1].mutual_entailment if len(ranked) > 1 else 0.0
    margin = best.mutual_entailment - runner_up_score

    confident = (
        best.mutual_entailment >= thresholds.mutual_entailment
        and best.similarity >= thresholds.similarity
        and margin >= thresholds.margin
    )
    if confident and automatic_linking:
        return LinkDecision("auto_link", best.concept, [], best)

    plausible = [v for v in ranked if max(v.implies, v.implied_by) >= REVIEW_ENTAILMENT]
    if confident and best not in plausible:
        plausible.insert(0, best)  # a confident match always leads the suggestions
    if plausible:
        return LinkDecision("review", None, [v.concept for v in plausible[:SUGGESTION_COUNT]], best)
    return LinkDecision("no_match", None, [], best)
