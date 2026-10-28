from dataclasses import dataclass

from recruiter_bot.matching.term_credit import Credit, TermCredit


@dataclass(frozen=True)
class TermMatch:
    required_term: str
    candidate_term: str
    credit: Credit


@dataclass(frozen=True)
class TermComparison:
    matches: list[TermMatch]
    missing_terms: list[str]
    score: float

    @property
    def matched_terms(self) -> list[str]:
        return [match.required_term for match in self.matches]


def compare_terms(
    candidate_terms: list[str],
    required_terms: list[str],
    concept_type: str,
    credit: TermCredit,
) -> TermComparison:
    """score = credit earned / required terms (0 to 1). Each candidate term covers at most one requirement (D-32)."""
    if not required_terms:
        return TermComparison([], [], 0.0)

    # Only candidate terms that earn something are worth searching; strongest first.
    options = []
    for required_term in required_terms:
        earning = []
        for candidate_term in candidate_terms:
            term_credit = credit.credit(concept_type, candidate_term, required_term)
            if term_credit.value > 0:
                earning.append((candidate_term, term_credit))
        earning.sort(key=lambda option: (-option[1].value, option[0]))
        options.append(earning)

    _, picks = _best_assignment(options, 0, frozenset(), {})

    matches = []
    missing_terms = []
    total_credit = 0.0
    for required_term, pick in zip(required_terms, picks):
        if pick is None:
            missing_terms.append(required_term)
        else:
            candidate_term, term_credit = pick
            matches.append(TermMatch(required_term, candidate_term, term_credit))
            total_credit += term_credit.value
    return TermComparison(matches, missing_terms, total_credit / len(required_terms))


def _best_assignment(options, index, used, memo):
    """Highest total credit over requirements[index:], never reusing a candidate term.
    Exact rather than greedy: taking the best credit first can block a better total."""
    if index == len(options):
        return 0.0, ()
    key = (index, used)
    if key in memo:
        return memo[key]

    best_total, best_rest = _best_assignment(options, index + 1, used, memo)
    best_picks = (None,) + best_rest
    for candidate_term, term_credit in options[index]:
        if candidate_term in used:
            continue
        rest_total, rest = _best_assignment(options, index + 1, used | {candidate_term}, memo)
        total = term_credit.value + rest_total
        if total > best_total + 1e-9:
            best_total = total
            best_picks = ((candidate_term, term_credit),) + rest

    memo[key] = (best_total, best_picks)
    return memo[key]
