from datetime import date

import pytest

from recruiter_bot.ingest.text_normalizer import normalize, normalize_list, parse_availability

TODAY = date(2026, 10, 28)


@pytest.mark.parametrize("raw, expected", [
    ("  Stakeholder   Management ", "stakeholder-management"),
    ("stakeholder-management", "stakeholder-management"),
    ("Sherlock H.", "sherlock-h"),
    ("team-building ,", "team-building"),
    ("Engineering Manager, Chaos Team", "engineering-manager-chaos-team"),
    ("C++", "cplusplus"),
    ("C#", "csharp"),
])
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_candidate_and_job_spellings_normalize_to_the_same_skill():
    candidate_skill = "stakeholder management"
    job_skill = "stakeholder-management"
    assert normalize(candidate_skill) == normalize(job_skill)


def test_normalize_list_drops_duplicates_and_keeps_order():
    assert normalize_list(["Research", "public speaking", "research"], "skill") == ["research", "public-speaking"]


def test_normalize_list_rejects_blank_value():
    with pytest.raises(ValueError, match="no letters or digits"):
        normalize_list(["research", "   "], "skill")


@pytest.mark.parametrize("raw, expected", [
    ("Immediate", (True, date(2026, 10, 28))),
    ("2 weeks", (True, date(2026, 11, 11))),
    ("Not looking", (False, None)),
])
def test_parse_availability(raw, expected):
    assert parse_availability(raw, TODAY) == expected


def test_parse_availability_rejects_unknown_text():
    with pytest.raises(ValueError, match="unrecognized availability"):
        parse_availability("someday", TODAY)
