import itertools
import random
from datetime import datetime

import psycopg
import pytest
from pydantic import ValidationError

from recruiter_bot import seed
from recruiter_bot.api.candidates import matches_for
from recruiter_bot.api.schemas import JobMatches
from recruiter_bot.ingest import (
    CandidateInput,
    CandidatePatch,
    JobInput,
    JobPatch,
    insert_candidate,
    insert_job,
    update_candidate,
    update_job,
)
from recruiter_bot.matching.scorer import CandidateProfile, JobProfile, best_pairing, score_match, tier_for
from recruiter_bot.matching.store import (
    StoredMatch,
    load_candidate_profiles,
    load_job_profiles,
    refresh_matches,
    stored_matches_for_candidate,
    stored_matches_for_job,
)
from recruiter_bot.matching.views import Standing, order_for_candidate
from recruiter_bot.taxonomy import Credit, ExactCredit, load_taxonomy_credit


def a_job(**changes) -> JobProfile:
    """A job needing skills a and b, 2 years of experience and culture keywords x and y."""
    values = dict(
        job_id=1,
        title="Test Job",
        min_experience_years=2,
        required_skills=["a", "b"],
        culture_keywords=["x", "y"],
    )
    values.update(changes)

    return JobProfile(**values)


def a_candidate(**changes) -> CandidateProfile:
    """A candidate who has everything the job above asks for."""
    values = dict(
        candidate_id=1,
        full_name="Test Candidate",
        experience_years=4,
        skills=["a", "b"],
        traits=["x", "y"],
    )
    values.update(changes)

    return CandidateProfile(**values)


class PersuasionIsRelated:
    """A credit source where `persuasion` is half-related to `sales` and `negotiation`."""

    def credit(self, concept_type, candidate_term, job_term):
        """Full credit for the same word, half for persuasion on sales or negotiation, none otherwise."""
        if candidate_term == job_term:
            return Credit(1.0, "exact")

        if candidate_term == "persuasion" and job_term in ("sales", "negotiation"):
            return Credit(0.5, "related")

        return Credit(0.0, "none")


def test_a_full_match_scores_100_even_when_over_qualified():
    """A full match scores 100, and 20 years against a 2-year minimum earns no more than 4."""
    result = score_match(a_candidate(experience_years=20), a_job(), ExactCredit())

    assert result.score == 100.0
    assert result.experience_score == 1.0


def test_the_score_is_70_percent_skills_20_experience_10_culture():
    """Half the skills, enough experience, half the culture: 0.7 x 0.5 + 0.2 + 0.1 x 0.5 = 60."""
    result = score_match(a_candidate(skills=["a"], traits=["x"]), a_job(), ExactCredit())

    assert result.score == 60.0


def test_too_little_experience_earns_proportional_credit():
    """2 years against a 4-year minimum earns half the experience credit."""
    result = score_match(a_candidate(experience_years=2), a_job(min_experience_years=4), ExactCredit())

    assert result.experience_score == 0.5
    assert result.score == 90.0


def test_no_skill_overlap_is_never_a_match():
    """Without a single skill in common it is never a match, whatever the experience or culture."""
    result = score_match(a_candidate(skills=["z"], experience_years=20), a_job(), ExactCredit())

    assert result.score == 30.0
    assert result.qualifies is False


def test_a_related_skill_earns_half_credit_and_the_reason_says_so():
    """A related skill earns half credit, and the reason names it."""
    result = score_match(
        a_candidate(skills=["persuasion"]),
        a_job(required_skills=["negotiation"], culture_keywords=[]),
        PersuasionIsRelated(),
    )

    assert result.skill_score == 0.5
    assert "negotiation ≈ persuasion ½" in result.reason


def test_one_skill_cannot_be_counted_for_two_requirements():
    """One skill covers only one requirement, so the shared half credit is 0.25, not 0.5."""
    result = score_match(
        a_candidate(skills=["persuasion"]),
        a_job(required_skills=["sales", "negotiation"], culture_keywords=[]),
        PersuasionIsRelated(),
    )

    assert result.skill_score == 0.25
    assert len(result.skill_matches) == 1


def test_a_score_of_exactly_50_counts_as_a_match_and_70_as_a_strong_one():
    """50 is the lowest score that counts as a match, and 70 the lowest for a strong one."""
    assert tier_for(70.0) == "strong_match"
    assert tier_for(69.9) == "possible_match"
    assert tier_for(50.0) == "possible_match"
    assert tier_for(49.9) == "near_miss"


def a_stored_match(job_id: int, score: float) -> StoredMatch:
    """Candidate 1's stored match for this job; only the ids and the score matter for ordering."""
    return StoredMatch(
        job_id=job_id, job_title=f"job {job_id}", candidate_id=1, candidate_name="Pat",
        score=score, skill_score=1.0, experience_score=1.0, culture_score=None,
        matched_skills=[], missing_skills=[], matched_culture=[], missing_culture=[], reason="",
        candidate_experience_years=5, job_min_experience_years=2,
        candidate_quirk=None, job_tagline=None, candidate_is_open=True,
    )


def test_a_candidates_tied_jobs_put_the_one_they_lead_first_then_the_newest():
    """Score first; on a tie, the job where they're top applicant; then the newer posting."""
    older, newer = datetime(2026, 1, 1), datetime(2026, 2, 1)
    standings = {
        1: Standing(above=1, posted_at=newer),  # same score, but a rival scores higher
        2: Standing(above=0, posted_at=older),  # same score, top applicant
        3: Standing(above=0, posted_at=newer),  # same score, top applicant, newer
        4: Standing(above=0, posted_at=newer),  # better score, so first whatever else
    }
    matches = [a_stored_match(1, 70.0), a_stored_match(2, 70.0), a_stored_match(3, 70.0), a_stored_match(4, 80.0)]

    ordered = order_for_candidate(matches, standings)

    assert [match.job_id for match in ordered] == [4, 3, 2, 1]


def job_id_of(conn, title: str) -> int:
    """The id of the seed job with this title."""
    return conn.execute("SELECT job_id FROM jobs WHERE title = %s", (title,)).fetchone()[0]


def candidate_id_of(conn, name: str) -> int:
    """The id of the seed candidate with this name."""
    return conn.execute("SELECT candidate_id FROM candidates WHERE full_name = %s", (name,)).fetchone()[0]


def names_in(tiers) -> list[str]:
    """Every candidate name listed in a recruiter's view, in any tier."""
    names = []
    for tier in (tiers.strong_match, tiers.possible_match, tiers.near_miss):
        for match in tier:
            names.append(match.candidate_name)

    return names


def test_a_jobs_candidates_are_ranked_best_fit_first(conn):
    """A job's candidates come best fit first."""
    matches = stored_matches_for_job(conn, job_id_of(conn, "Incident Commander"))

    assert [(m.candidate_name, m.score) for m in matches[:2]] == [("Olivia P.", 95.0), ("Katniss E.", 74.2)]

    scores = [m.score for m in matches]
    assert scores == sorted(scores, reverse=True)


def test_a_candidates_jobs_are_ranked_best_fit_first(conn):
    """A candidate's jobs come best fit first."""
    response = matches_for(conn, candidate_id_of(conn, "Elle W."))

    best = response.matches.strong_match[0]
    assert (best.job_title, best.score, best.rank) == ("Developer Relations Lead", 90.0, 1)

    second = response.matches.possible_match[0]
    assert (second.job_title, second.score, second.rank) == ("Sales Engineer", 55.0, 2)


def test_both_directions_give_every_pair_the_same_score(conn):
    """Every candidate and job pair gets the same score in both views."""
    job_ids = [row[0] for row in conn.execute("SELECT job_id FROM jobs").fetchall()]
    candidate_ids = [row[0] for row in conn.execute("SELECT candidate_id FROM candidates").fetchall()]

    seen_from_jobs = {}
    for job_id in job_ids:
        for match in stored_matches_for_job(conn, job_id):
            seen_from_jobs[(match.job_id, match.candidate_id)] = match.score

    seen_from_candidates = {}
    for candidate_id in candidate_ids:
        for match in stored_matches_for_candidate(conn, candidate_id):
            seen_from_candidates[(match.job_id, match.candidate_id)] = match.score

    assert len(seen_from_jobs) > 0
    assert seen_from_jobs == seen_from_candidates


def test_stored_matches_equal_a_fresh_calculation(conn):
    """Stored matches equal a fresh calculation."""
    credit = load_taxonomy_credit(conn)
    candidates = load_candidate_profiles(conn)
    for job in load_job_profiles(conn):
        stored = {(m.candidate_id, m.score) for m in stored_matches_for_job(conn, job.job_id)}
        fresh = {(c.candidate_id, r.score) for c in candidates if (r := score_match(c, job, credit)).qualifies}

        assert stored == fresh


def test_equal_scores_go_to_whoever_can_start_first(conn):
    """Elle (available now) and Hermione (in 2 weeks) both score 90.0, so Elle comes first."""
    matches = stored_matches_for_job(conn, job_id_of(conn, "Developer Relations Lead"))

    assert [(m.candidate_name, m.score) for m in matches[:2]] == [("Elle W.", 90.0), ("Hermione G.", 90.0)]


def test_a_better_fit_who_is_not_looking_becomes_a_proactive_offer(conn):
    """Michael, who is not looking, fits Sales Engineer better than anyone who is."""
    job_id = job_id_of(conn, "Sales Engineer")
    response = JobMatches.from_results(job_id, stored_matches_for_job(conn, job_id))

    assert response.proactive_offers_included is True
    assert [offer.candidate_name for offer in response.proactive_offers] == ["Michael S."]
    assert "Michael S." not in names_in(response.matches)


def test_no_proactive_offer_when_someone_available_is_just_as_good(conn):
    """Backend Detective has an available candidate who beats everyone else, so no offer is needed."""
    job_id = job_id_of(conn, "Backend Detective")
    response = JobMatches.from_results(job_id, stored_matches_for_job(conn, job_id))

    assert response.proactive_offers_included is False
    assert response.proactive_offers == []


def test_near_misses_are_shown_only_when_nothing_better_exists(conn):
    """Ron's best job scores 43.3, so his near misses are shown; Elle has real matches, so hers are hidden."""
    ron = matches_for(conn, candidate_id_of(conn, "Ron S."))
    elle = matches_for(conn, candidate_id_of(conn, "Elle W."))

    assert ron.matches.near_misses_included is True
    assert len(ron.matches.near_miss) == 2

    assert elle.matches.near_misses_included is False
    assert elle.matches.near_miss == []


def test_the_taxonomy_gives_a_synonym_full_credit_and_a_related_word_half(conn):
    """Leslie's `tenacious` is a synonym of `persistent`; Katniss's `resilient` is related to `calm-under-pressure`."""
    sales_engineer = stored_matches_for_job(conn, job_id_of(conn, "Sales Engineer"))
    leslie = next(m for m in sales_engineer if m.candidate_name == "Leslie K.")

    assert "persistent" in leslie.matched_culture

    incident_commander = stored_matches_for_job(conn, job_id_of(conn, "Incident Commander"))
    katniss = next(m for m in incident_commander if m.candidate_name == "Katniss E.")

    assert "calm-under-pressure" in katniss.matched_culture
    assert katniss.culture_score == 0.75


def test_patch_changes_only_the_fields_sent_and_refreshes_matches(conn):
    """Ron gains every Sales Engineer skill: his skill score rises to 1, and his name and years stay the same."""

    def rons_skill_score(ron: int, job_id: int) -> float:
        return next(m.skill_score for m in stored_matches_for_job(conn, job_id) if m.candidate_id == ron)

    with conn.transaction(force_rollback=True):
        ron = candidate_id_of(conn, "Ron S.")
        sales_engineer = job_id_of(conn, "Sales Engineer")
        assert rons_skill_score(ron, sales_engineer) < 1.0  # he has only negotiation

        assert update_candidate(conn, ron, CandidatePatch(skills=["Sales", "Negotiation", "Public Speaking"])) is True
        refresh_matches(conn, candidate_id=ron)

        assert rons_skill_score(ron, sales_engineer) == 1.0
        profile = load_candidate_profiles(conn, ron)[0]
        assert (profile.full_name, profile.experience_years) == ("Ron S.", 15)
        assert profile.skills == ["negotiation", "public-speaking", "sales"]


def test_patch_of_a_missing_record_changes_nothing(conn):
    """An unknown id is reported, so the API can answer 404."""
    assert update_job(conn, 999_999, JobPatch(tagline="nobody")) is False


def test_patch_refuses_unknown_fields_and_clearing_required_ones():
    """A typo fails loudly, and a required field can be changed but not removed."""
    with pytest.raises(ValidationError):
        CandidatePatch.model_validate({"skils": ["sales"]})
    with pytest.raises(ValidationError):
        JobPatch.model_validate({"title": None})
    assert JobPatch.model_validate({"tagline": None}).model_fields_set == {"tagline"}


def culture_of_new_pair(conn, candidate_traits: list[str], job_culture: list[str]) -> tuple[float, list[str]]:
    """Stores a fresh job and candidate who share a skill, and returns their culture score and matched keywords."""
    job_id = insert_job(conn, JobInput(
        title="Culture Test", required_skills=["negotiation"], min_experience_years=0, culture_keywords=job_culture,
    ))
    candidate_id = insert_candidate(conn, CandidateInput(
        name="Culture Tester", skills=["negotiation"], experience_years=1, availability="Immediate",
        traits=candidate_traits,
    ))
    refresh_matches(conn, job_id=job_id)
    match = next(m for m in stored_matches_for_job(conn, job_id) if m.candidate_id == candidate_id)
    return match.culture_score, match.matched_culture


def test_a_concepts_own_name_matches_its_other_words_in_both_directions(conn):
    """`resilience` (the concept's name) and `cope-with-pressures` (one of its labels) match whichever side has which."""
    with conn.transaction(force_rollback=True):
        assert culture_of_new_pair(conn, ["Resilience"], ["cope-with-pressures"]) == (1.0, ["cope-with-pressures"])
        assert culture_of_new_pair(conn, ["Cope with pressures"], ["resilience"]) == (1.0, ["resilience"])


def test_a_word_the_taxonomy_does_not_know_matches_only_its_own_spelling(conn):
    """No concept means no synonyms: `grit` earns nothing toward `resilient`, but full credit toward `grit`."""
    with conn.transaction(force_rollback=True):
        assert culture_of_new_pair(conn, ["grit"], ["resilient"]) == (0.0, [])
        assert culture_of_new_pair(conn, ["Grit"], ["grit"]) == (1.0, ["grit"])


def test_every_word_the_taxonomy_knows_is_linked_to_its_concept(conn):
    """After seeding, a seed word with a label has its concept stored, e.g. `tenacious` -> persistence."""
    row = conn.execute("""
        SELECT concepts.slug FROM traits JOIN concepts ON concepts.concept_id = traits.concept_id
        WHERE traits.slug = 'tenacious'
    """).fetchone()
    assert row == ("persistence",)


def test_the_database_refuses_a_spelling_that_would_mean_two_concepts(conn):
    """`team-building` is already a label; `teambuilding` for another concept is refused by the database itself."""
    with conn.transaction(force_rollback=True):
        other_concept = conn.execute(
            "SELECT concept_id FROM concepts WHERE concept_type = 'skill' AND slug = 'leadership'"
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.UniqueViolation):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO concept_labels (concept_id, concept_type, label) VALUES (%s, 'skill', 'teambuilding')",
                    (other_concept,),
                )


def test_the_hungarian_pairing_always_earns_the_brute_force_maximum():
    """On 500 random cases, the pairing uses each skill once and earns exactly the best possible total."""
    rng = random.Random(42)
    for _ in range(500):
        rows, columns = rng.randint(1, 4), rng.randint(0, 6)
        credits = [[rng.choice([0.0, 0.0, 0.5, 1.0]) for _ in range(columns)] for _ in range(rows)]

        pairing = best_pairing(credits)
        used = [column for column in pairing if column is not None]
        assert len(used) == len(set(used))
        earned = sum(credits[row][column] for row, column in enumerate(pairing) if column is not None)

        # Brute force: every way to give each requirement a different skill, or none.
        options = list(range(columns)) + [None] * rows
        best = max(
            sum(credits[row][column] for row, column in enumerate(choice) if column is not None)
            for choice in itertools.permutations(options, rows)
        )
        assert earned == best


def test_running_the_seed_again_adds_nothing(conn):
    """Each seed file is loaded once (recorded in seed_runs), so a restart never duplicates a record."""
    count_sql = "SELECT (SELECT count(*) FROM candidates), (SELECT count(*) FROM jobs), (SELECT count(*) FROM matches)"
    before = conn.execute(count_sql).fetchone()
    conn.commit()

    seed.run()

    assert conn.execute(count_sql).fetchone() == before
