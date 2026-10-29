"""What a recruiter sees for one job: who to hire now, and who is worth an offer."""
from recruiter_bot.matching.match_store import StoredMatch

# Near misses are shown only when nothing reaches a match, and then at most this many.
NEAR_MISS_LIMIT = 3


def is_a_match(match: StoredMatch) -> bool:
    """A strong or possible match, i.e. a score of 50 or more."""
    return match.tier in ("strong_match", "possible_match")


def shown_matches(matches: list[StoredMatch]) -> tuple[list[StoredMatch], bool]:
    """The matches worth showing, best first; near misses only when nothing better exists."""
    real_matches = [match for match in matches if is_a_match(match)]
    if real_matches:
        # Strong before possible, so ranks follow the tiers, not the score alone.
        real_matches.sort(key=lambda match: match.tier != "strong_match")
        return real_matches, False
    near_misses = [match for match in matches if match.tier == "near_miss"]
    return near_misses[:NEAR_MISS_LIMIT], bool(near_misses)


def open_candidates(matches: list[StoredMatch]) -> list[StoredMatch]:
    """Candidates who are open to opportunities, whatever their start date."""
    return [match for match in matches if match.candidate_is_open]


def proactive_offers(matches: list[StoredMatch]) -> list[StoredMatch]:
    """Candidates not looking who score higher than the best open candidate."""
    available = open_candidates(matches)
    best_open_score = max((match.score for match in available), default=None)

    offers = []
    for match in matches:
        if match.candidate_is_open or not is_a_match(match):
            continue
        if best_open_score is None or match.score > best_open_score:
            offers.append(match)
    return offers
