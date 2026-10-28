"""How much do the rankings depend on the choice of weights? (D-48)

Usage: python -m recruiter_bot.sensitivity.report

It reads every job's stored matches, then re-ranks them with different weights:
1. Sanity check: the production weights must reproduce every stored score exactly.
2. One weight at a time: each weight moved by +-0.05 and +-0.10 around production.
3. A grid of every plausible weighting, keeping skills >= experience >= culture.
For each, it reports whether each job's top candidate stays the same, which candidates
change tier, and how similar the whole order stays (Kendall's tau).
"""
import sys

import psycopg

from recruiter_bot.db import connect
from recruiter_bot.matching.match_store import StoredMatch, stored_matches_for_job
from recruiter_bot.sensitivity.comparison import (
    rank_agreement,
    rank_candidates,
    tier_changes,
    top_candidate,
    top_change,
)
from recruiter_bot.sensitivity.weights import PRODUCTION_WEIGHTS, Weights, recompute_score

JOBS_SQL = "SELECT job_id, title FROM jobs ORDER BY job_id"

STEPS = [-0.10, -0.05, 0.05, 0.10]
GRID_SKILLS = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]
GRID_EXPERIENCE = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]


def load_matches_by_job(conn: psycopg.Connection) -> dict[str, list[StoredMatch]]:
    """Job title -> its stored matches. Jobs with fewer than two matches can't change order, so they're left out."""
    matches_by_job = {}
    for job_id, title in conn.execute(JOBS_SQL).fetchall():
        matches = stored_matches_for_job(conn, job_id)
        if len(matches) >= 2:
            matches_by_job[title] = matches
    return matches_by_job


def check_formula(matches_by_job: dict[str, list[StoredMatch]]) -> None:
    """Stops the report if recompute_score doesn't match what production stored."""
    for title, matches in matches_by_job.items():
        for match in matches:
            recomputed = recompute_score(match.skill_score, match.experience_score, match.culture_score,
                                         PRODUCTION_WEIGHTS)
            if recomputed != match.score:
                raise SystemExit(f"Formula mismatch for {match.candidate_name} / {title}: "
                                 f"stored {match.score}, recomputed {recomputed}")
    count = sum(len(matches) for matches in matches_by_job.values())
    print(f"Sanity check passed: the production weights reproduce all {count} stored scores exactly.\n")


def one_weight_at_a_time(matches_by_job: dict[str, list[StoredMatch]]) -> None:
    print("1. One weight at a time (the others keep their proportions; all three rescaled to add up to 1)")
    print(f"   {'change':<18} {'weights used':<46} {'real flips':<11} {'ties':<6} {'tier changes':<13} lowest tau")

    for factor in ("skills", "experience", "culture"):
        for step in STEPS:
            weights = _moved(PRODUCTION_WEIGHTS, factor, step)
            if weights is None:
                continue  # a weight would drop below zero

            flips = []
            ties = []
            all_tier_changes = []
            lowest_tau = 1.0
            for title, matches in matches_by_job.items():
                baseline = rank_candidates(matches, PRODUCTION_WEIGHTS)
                variant = rank_candidates(matches, weights)
                change = top_change(baseline, variant)
                if change == "flip":
                    flips.append(f"{title}: {top_candidate(baseline)} -> {top_candidate(variant)} (a better score)")
                elif change == "tie":
                    ties.append(f"{title}: {top_candidate(baseline)} now tied with {top_candidate(variant)}")
                for change in tier_changes(baseline, variant):
                    all_tier_changes.append(f"{title} / {change}")
                lowest_tau = min(lowest_tau, rank_agreement(baseline, variant))

            label = f"{factor} {step:+.2f}"
            print(f"   {label:<18} {weights.describe():<46} {len(flips):<11} {len(ties):<6} "
                  f"{len(all_tier_changes):<13} {lowest_tau:.2f}")
            for line in flips + ties:
                print(f"       {line}")
    print()


def _moved(weights: Weights, factor: str, step: float) -> Weights | None:
    skills, experience, culture = weights.skills, weights.experience, weights.culture
    if factor == "skills":
        skills += step
    elif factor == "experience":
        experience += step
    else:
        culture += step
    if min(skills, experience, culture) < -1e-9:
        return None
    return Weights(max(skills, 0.0), max(experience, 0.0), max(culture, 0.0)).scaled_to_one()


def plausible_weightings() -> list[Weights]:
    """Every grid point where the weights add up to 1 and skills >= experience >= culture."""
    weightings = []
    for skills in GRID_SKILLS:
        for experience in GRID_EXPERIENCE:
            culture = round(1.0 - skills - experience, 2)
            if culture < 0:
                continue
            if skills >= experience >= culture:
                weightings.append(Weights(skills, experience, culture))
    return weightings


def grid_of_weightings(matches_by_job: dict[str, list[StoredMatch]]) -> None:
    weightings = plausible_weightings()
    print(f"2. Every plausible weighting ({len(weightings)} of them: skills >= experience >= culture)")
    for title, matches in matches_by_job.items():
        baseline = rank_candidates(matches, PRODUCTION_WEIGHTS)
        baseline_top = top_candidate(baseline)

        same = 0
        tied = 0
        beaten_by = {}  # candidate -> one weighting under which they score strictly higher
        lowest_tau = 1.0
        for weights in weightings:
            variant = rank_candidates(matches, weights)
            change = top_change(baseline, variant)
            if change == "same":
                same += 1
            elif change == "tie":
                tied += 1
            elif top_candidate(variant) not in beaten_by:
                beaten_by[top_candidate(variant)] = weights
            lowest_tau = min(lowest_tau, rank_agreement(baseline, variant))

        not_beaten = (same + tied) / len(weightings)
        print(f"   {title:<34} {baseline_top} is never beaten in {not_beaten:.0%} of weightings "
              f"(alone first {same}, tied first {tied}); lowest tau {lowest_tau:.2f}")
        for winner, weights in beaten_by.items():
            print(f"       {winner} scores higher with e.g. {weights.describe()}")
    print()


def main() -> None:
    if sys.argv[1:]:
        print(__doc__)
        raise SystemExit(2)
    with connect() as conn:
        matches_by_job = load_matches_by_job(conn)

    print(f"Production weights: {PRODUCTION_WEIGHTS.describe()}\n")
    check_formula(matches_by_job)
    one_weight_at_a_time(matches_by_job)
    grid_of_weightings(matches_by_job)


if __name__ == "__main__":
    main()
