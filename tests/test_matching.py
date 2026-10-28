import psycopg
import pytest

from recruiter_bot.db import connect
from recruiter_bot.matching import (
    CandidateProfile,
    Credit,
    ExactCredit,
    JobProfile,
    TaxonomyCredit,
    compare_terms,
    experience_fit,
    rank_candidates_for_job,
    rank_jobs_for_candidate,
    score_match,
)

EXACT = ExactCredit()


class FakeCredit:
    """A credit source built from a dict, to test the scorer without a taxonomy (D-32)."""

    def __init__(self, related):
        self._related = related

    def credit(self, concept_type, candidate_term, job_term):
        if candidate_term == job_term:
            return Credit(1.0, "exact")
        value = self._related.get((candidate_term, job_term))
        if value:
            return Credit(value, "related")
        return Credit(0.0, "none")


# ---- Credit sources

def test_exact_credit_compares_compact_keys():
    assert EXACT.credit("skill", "public-speaking", "publicspeaking").value == 1.0
    assert EXACT.credit("skill", "persuasion", "sales").value == 0.0


def test_taxonomy_credit_by_concept_and_relation():
    credit = TaxonomyCredit(
        concept_by_label={("trait", "persistent"): 1, ("trait", "tenacious"): 1, ("trait", "calm"): 2,
                          ("trait", "calmunderpressure"): 3, ("trait", "chaotic"): 4, ("trait", "organized"): 5},
        relation_credit={(2, 3): 0.5, (3, 2): 0.5, (4, 5): 0.0, (5, 4): 0.0},
    )
    assert credit.credit("trait", "tenacious", "persistent") == Credit(1.0, "synonym")
    assert credit.credit("trait", "calm", "calm-under-pressure") == Credit(0.5, "related")
    assert credit.credit("trait", "chaotic", "organized") == Credit(0.0, "none")
    assert credit.credit("trait", "witty", "calm") == Credit(0.0, "none")
    # A label belongs to one type: the same word as a skill gets nothing.
    assert credit.credit("skill", "tenacious", "persistent") == Credit(0.0, "none")


# ---- Term coverage

def test_compare_terms_counts_matched_and_missing():
    comparison = compare_terms(
        candidate_terms=["sales", "public-speaking", "team-building"],
        required_terms=["sales", "public-speaking", "negotiation"],
        concept_type="skill",
        credit=EXACT,
    )
    assert comparison.matched_terms == ["sales", "public-speaking"]
    assert comparison.missing_terms == ["negotiation"]
    assert comparison.score == pytest.approx(2 / 3)


def test_compare_terms_with_no_overlap():
    comparison = compare_terms(["woodworking"], ["deduction", "forensics"], "skill", EXACT)
    assert comparison.matched_terms == []
    assert comparison.score == 0.0


def test_one_candidate_term_covers_one_requirement():
    credit = FakeCredit({("persuasion", "sales"): 0.5, ("persuasion", "negotiation"): 0.5})
    comparison = compare_terms(["persuasion"], ["negotiation", "sales"], "skill", credit)
    assert comparison.score == 0.25
    assert len(comparison.matches) == 1


def test_assignment_is_exact_not_greedy():
    # Greedy would give "mentor" to leadership (its best credit) and leave team-building empty: 1.0.
    # The best assignment uses "coach" for leadership and "mentor" for team-building: 1.5.
    credit = FakeCredit({("mentor", "leadership"): 1.0, ("mentor", "team-building"): 1.0,
                         ("coach", "leadership"): 0.5})
    comparison = compare_terms(["mentor", "coach"], ["leadership", "team-building"], "skill", credit)
    assert comparison.score == 0.75
    assert {(m.required_term, m.candidate_term) for m in comparison.matches} == {
        ("leadership", "coach"), ("team-building", "mentor"),
    }


# ---- Experience fit

@pytest.mark.parametrize("years, minimum, expected", [
    (8, 3, 1.0),
    (3, 3, 1.0),
    (20, 2, 1.0),
    (2, 4, 0.5),
    (0, 0, 1.0),
])
def test_experience_fit(years, minimum, expected):
    assert experience_fit(years, minimum) == expected


# ---- Scoring

def test_score_without_culture_keywords_rescales_weights():
    candidate = CandidateProfile(1, "Sherlock H.", 8, ["deduction", "forensics", "pattern-recognition"])
    job = JobProfile(1, "Backend Detective", 3, ["deduction", "forensics", "pattern-recognition"])
    result = score_match(candidate, job, EXACT)
    assert result.score == 100.0
    assert result.culture_score is None
    assert result.reason == "3/3 skills (deduction, forensics, pattern-recognition) · 8y vs 3y min"


def test_score_combines_skills_experience_and_culture():
    candidate = CandidateProfile(1, "Junior", 2, ["sales"], ["persistent"])
    job = JobProfile(6, "Sales Engineer", 4, ["negotiation", "sales"], ["enthusiastic", "persistent"])
    result = score_match(candidate, job, EXACT)
    assert (result.skill_score, result.experience_score, result.culture_score) == (0.5, 0.5, 0.5)
    assert result.score == 50.0  # 0.7 * 0.5 + 0.2 * 0.5 + 0.1 * 0.5
    assert result.reason == "1/2 skills (sales) · missing negotiation · 2y vs 4y min · culture 1/2 (persistent)"


def test_reason_names_where_partial_credit_came_from():
    credit = FakeCredit({("persuasion", "negotiation"): 0.5})
    candidate = CandidateProfile(1, "Elle W.", 3, ["persuasion", "sales"])
    job = JobProfile(6, "Sales Engineer", 3, ["negotiation", "sales"])
    assert score_match(candidate, job, credit).reason == (
        "1.5/2 skills (negotiation ≈ persuasion ½, sales) · 3y vs 3y min"
    )


def test_culture_and_experience_cannot_create_a_match():
    candidate = CandidateProfile(1, "Ron S.", 15, ["woodworking"], ["decisive"])
    job = JobProfile(5, "Incident Commander", 4, ["crisis-management"], ["decisive"])
    result = score_match(candidate, job, EXACT)
    assert result.score == 30.0
    assert not result.qualifies


# ---- Ranking against the seeded database, with the taxonomy

@pytest.fixture
def conn():
    try:
        connection = connect()
    except psycopg.OperationalError:
        pytest.skip("Postgres is not running")
    with connection:
        yield connection


def names(results):
    return [(result.candidate_name, result.score) for result in results]


def test_backend_detective_ranking(conn):
    assert names(rank_candidates_for_job(conn, 1)) == [("Sherlock H.", 95.0), ("Sheldon C.", 43.3)]


def test_culture_breaks_the_rapid_prototyping_tie(conn):
    # All three have both skills; innovative (Tony) beats the related improviser (MacGyver).
    assert names(rank_candidates_for_job(conn, 2)) == [
        ("Tony S.", 95.0), ("MacGyver", 92.5), ("Rick S.", 90.0),
    ]


def test_equal_scores_are_broken_by_name(conn):
    assert names(rank_candidates_for_job(conn, 3))[:2] == [("Elle W.", 90.0), ("Hermione G.", 90.0)]


def test_related_skill_gives_partial_credit(conn):
    results = rank_candidates_for_job(conn, 4)
    assert names(results)[:2] == [("Miranda P.", 66.7), ("Ted L.", 60.0)]
    assert results[1].reason.startswith("1.5/3 skills (leadership ≈ mentorship ½, team-building)")


def test_related_trait_gives_partial_culture_credit(conn):
    results = rank_candidates_for_job(conn, 5)
    assert names(results)[:2] == [("Olivia P.", 95.0), ("Katniss E.", 74.2)]
    assert "culture 1.5/2 (calm-under-pressure ≈ resilient ½, decisive)" in results[1].reason


def test_synonym_and_culture_reorder_sales_engineer(conn):
    results = rank_candidates_for_job(conn, 6)
    assert names(results)[:3] == [("Michael S.", 71.7), ("Dwight S.", 66.7), ("Elle W.", 55.0)]
    leslie = next(result for result in results if result.candidate_name == "Leslie K.")
    assert "culture 1/2 (persistent = tenacious)" in leslie.reason


def test_candidates_without_skill_credit_are_excluded(conn):
    candidate_names = [result.candidate_name for result in rank_candidates_for_job(conn, 1)]
    assert "Ron S." not in candidate_names


def test_reverse_direction_for_ron(conn):
    results = rank_jobs_for_candidate(conn, 5)
    assert [(result.job_title, result.score) for result in results] == [
        ("Incident Commander", 43.3), ("Sales Engineer", 43.3),
    ]


def test_both_directions_agree_on_every_pair(conn):
    # D-15: one score per pair; the direction only changes what is ranked.
    # Real ids, not 1-6 and 1-15: records added through the API take ids too.
    job_ids = [row[0] for row in conn.execute("SELECT job_id FROM jobs")]
    candidate_ids = [row[0] for row in conn.execute("SELECT candidate_id FROM candidates")]
    by_job = {(r.job_id, r.candidate_id): r.score for job_id in job_ids for r in rank_candidates_for_job(conn, job_id)}
    by_candidate = {
        (r.job_id, r.candidate_id): r.score
        for candidate_id in candidate_ids
        for r in rank_jobs_for_candidate(conn, candidate_id)
    }
    assert by_job == by_candidate


def test_exact_credit_can_be_swapped_in(conn):
    # Loosely coupled: the same ranker without the taxonomy gives no related credit to Ted.
    ted = next(r for r in rank_candidates_for_job(conn, 4, credit=EXACT) if r.candidate_name == "Ted L.")
    assert ted.skill_score == pytest.approx(1 / 3, abs=0.001)


def test_unknown_ids_return_none(conn):
    assert rank_candidates_for_job(conn, 999) is None
    assert rank_jobs_for_candidate(conn, 999) is None
