"""Ranks one job's candidates with a set of weights, and compares two such rankings (D-48)."""
from dataclasses import dataclass

from recruiter_bot.matching.match_scorer import tier_for
from recruiter_bot.matching.match_store import StoredMatch
from recruiter_bot.sensitivity.weights import Weights, recompute_score


@dataclass(frozen=True)
class RankedCandidate:
    candidate_name: str
    score: float
    tier: str


def rank_candidates(matches: list[StoredMatch], weights: Weights) -> list[RankedCandidate]:
    """One job's candidates, best first, scored with these weights.

    The order is score, then skill score, then name. The API also uses availability
    between equal scores (D-16); it's left out here because no weight changes it.
    """
    rescored = []
    for match in matches:
        score = recompute_score(match.skill_score, match.experience_score, match.culture_score, weights)
        rescored.append((score, match.skill_score, match.candidate_name))

    rescored.sort(key=lambda item: (-item[0], -item[1], item[2]))

    ranked = []
    for score, _skill_score, candidate_name in rescored:
        ranked.append(RankedCandidate(candidate_name, score, tier_for(score)))
    return ranked


def top_candidate(ranking: list[RankedCandidate]) -> str | None:
    if not ranking:
        return None
    return ranking[0].candidate_name


def top_change(baseline: list[RankedCandidate], variant: list[RankedCandidate]) -> str:
    """'same', 'tie' or 'flip' for the first place.

    - same: the baseline winner is still first.
    - tie:  someone else is listed first, but the baseline winner has exactly the same score.
            Only the tie-break order moved; nobody became a better fit.
    - flip: someone else now has a strictly higher score than the baseline winner.
    """
    baseline_winner = top_candidate(baseline)
    if top_candidate(variant) == baseline_winner:
        return "same"
    best_score = variant[0].score
    for candidate in variant:
        if candidate.candidate_name == baseline_winner and candidate.score == best_score:
            return "tie"
    return "flip"


def tier_changes(baseline: list[RankedCandidate], variant: list[RankedCandidate]) -> list[str]:
    """Candidates whose tier differs between the two rankings, e.g. 'Ted L.: possible_match -> near_miss'."""
    baseline_tier = {}
    for candidate in baseline:
        baseline_tier[candidate.candidate_name] = candidate.tier

    changes = []
    for candidate in variant:
        before = baseline_tier[candidate.candidate_name]
        if candidate.tier != before:
            changes.append(f"{candidate.candidate_name}: {before} -> {candidate.tier}")
    return changes


def rank_agreement(baseline: list[RankedCandidate], variant: list[RankedCandidate]) -> float:
    """Kendall's tau: 1.0 when the two orders are identical, 0 when unrelated, -1.0 when reversed.

    It looks at every pair of candidates and asks: do both rankings put this pair in the same order?
    A pair with exactly the same score in the variant is skipped: a tie is not a disagreement.
    """
    position_in_variant = {}
    score_in_variant = {}
    for position, candidate in enumerate(variant):
        position_in_variant[candidate.candidate_name] = position
        score_in_variant[candidate.candidate_name] = candidate.score

    names = [candidate.candidate_name for candidate in baseline]  # already in baseline order
    same_order = 0
    opposite_order = 0
    for first in range(len(names)):
        for second in range(first + 1, len(names)):
            if score_in_variant[names[first]] == score_in_variant[names[second]]:
                continue
            # In the baseline, names[first] comes before names[second]. Is that still true in the variant?
            if position_in_variant[names[first]] < position_in_variant[names[second]]:
                same_order += 1
            else:
                opposite_order += 1

    pairs = same_order + opposite_order
    if pairs == 0:
        return 1.0  # zero or one candidate: nothing can change order
    return (same_order - opposite_order) / pairs
