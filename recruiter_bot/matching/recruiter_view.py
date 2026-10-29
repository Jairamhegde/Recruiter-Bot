"""What a recruiter sees for one job: who can be hired now, and who is worth a proactive offer (D-49).

The score never changes here. This only decides which section a match goes into and whether
near misses are worth showing.
"""
from recruiter_bot.matching.match_store import StoredMatch

# D-17: near misses are shown only when nothing reaches a match, and then at most this many.
NEAR_MISS_LIMIT = 3


def is_a_match(match: StoredMatch) -> bool:
    """A strong or possible match, i.e. a score of 50 or more (D-17, D-34)."""
    return match.tier in ("strong_match", "possible_match")


def shown_matches(matches: list[StoredMatch]) -> tuple[list[StoredMatch], bool]:
    """The matches worth showing, best first, and whether near misses are among them.

    Near misses only appear when there is no strong or possible match at all: then they explain
    what is missing. Otherwise they're noise next to real matches.
    """
    real_matches = [match for match in matches if is_a_match(match)]
    if real_matches:
        # Strong before possible, keeping each tier's own order. A match below the job's minimum years
        # is at most possible even with a high score (D-56), so ranks must follow the tiers, not the score alone.
        real_matches.sort(key=lambda match: match.tier != "strong_match")
        return real_matches, False
    near_misses = [match for match in matches if match.tier == "near_miss"]
    return near_misses[:NEAR_MISS_LIMIT], bool(near_misses)


def open_candidates(matches: list[StoredMatch]) -> list[StoredMatch]:
    """Candidates who are open to opportunities, whatever their start date."""
    return [match for match in matches if match.candidate_is_open]


def proactive_offers(matches: list[StoredMatch]) -> list[StoredMatch]:
    """Candidates who aren't looking but are worth approaching anyway: a strong or possible match
    who scores higher than the best candidate who is open. That is exactly when nobody available
    is as good, so the effort of an offer pays off."""
    available = open_candidates(matches)
    best_open_score = max((match.score for match in available), default=None)

    offers = []
    for match in matches:
        if match.candidate_is_open or not is_a_match(match):
            continue
        if best_open_score is None or match.score > best_open_score:
            offers.append(match)
    return offers
