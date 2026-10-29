from dataclasses import dataclass

from recruiter_bot.matching.assignment import best_assignment
from recruiter_bot.matching.term_credit import Credit, TermCredit

# Credit becomes a whole number so that equal totals are exactly equal: 0.5 -> 500, 1.0 -> 1000.
CREDIT_UNITS = 1000


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
    """Credit earned / required terms; each candidate term covers one requirement at most."""
    if not required_terms:
        return TermComparison([], [], 0.0)

    terms = sorted(set(candidate_terms))  # a fixed order, so equal pairings are always settled the same way
    credits = [[credit.credit(concept_type, term, required) for term in terms] for required in required_terms]

    # Only candidate terms that earn credit for something can be part of the answer.
    useful_columns = [column for column in range(len(terms)) if any(row[column].value > 0 for row in credits)]
    weights = _weights(credits, useful_columns)
    paired = best_assignment(weights)

    matches = []
    missing_terms = []
    total_credit = 0.0
    for row, required_term in enumerate(required_terms):
        if paired[row] is None:
            missing_terms.append(required_term)
            continue
        column = useful_columns[paired[row]]
        term_credit = credits[row][column]
        matches.append(TermMatch(required_term, terms[column], term_credit))
        total_credit += term_credit.value
    return TermComparison(matches, missing_terms, total_credit / len(required_terms))


def _weights(credits: list[list[Credit]], useful_columns: list[int]) -> list[list[int]]:
    """Whole-number weights: credit first, then a tiny penalty that settles exact ties the same way."""
    rows = len(credits)
    base = len(useful_columns) + 1   # a rank never reaches this
    big = base ** rows               # more than all penalties added together

    weights = []
    for row in range(rows):
        # Terms that earn credit for this requirement, best first: most credit, then alphabetical.
        earning = [position for position, column in enumerate(useful_columns) if credits[row][column].value > 0]
        earning.sort(key=lambda position: (-credits[row][useful_columns[position]].value, position))
        rank_of = {position: rank for rank, position in enumerate(earning, start=1)}

        penalty_unit = base ** (rows - 1 - row)
        weights_of_row = []
        for position, column in enumerate(useful_columns):
            if position not in rank_of:
                weights_of_row.append(0)
                continue
            units = round(credits[row][column].value * CREDIT_UNITS)
            weights_of_row.append(units * big - rank_of[position] * penalty_unit)
        weights.append(weights_of_row)
    return weights
