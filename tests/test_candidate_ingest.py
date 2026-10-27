import json
from datetime import date
from pathlib import Path

import pytest

from recruiter_bot.ingest import build_candidate_batch, extract_candidates, read_json_records

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"
TODAY = date(2026, 10, 28)


def candidate(**overrides):
    record = {"name": "Sherlock H.", "skills": ["deduction"], "experience_years": 8, "availability": "Immediate"}
    record.update(overrides)
    return record


def test_reads_candidate_seed_file():
    assert len(read_json_records(SEED_DIR / "candidate_data.json")) == 15


def test_rejects_file_that_is_not_an_array(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"name": "Sherlock H."}))
    with pytest.raises(ValueError, match="expected a JSON array"):
        read_json_records(path)


def test_all_seed_candidates_are_valid():
    extraction = extract_candidates(read_json_records(SEED_DIR / "candidate_data.json"), TODAY)
    assert len(extraction.records) == 15
    assert extraction.rejected == []


@pytest.mark.parametrize("missing_field", ["name", "skills", "experience_years", "availability"])
def test_rejects_candidate_missing_required_field(missing_field):
    record = candidate()
    del record[missing_field]
    extraction = extract_candidates([record], TODAY)
    assert extraction.records == []
    assert missing_field in extraction.rejected[0].message


@pytest.mark.parametrize("bad_record, expected_message", [
    (candidate(skills=[]), "skills"),
    (candidate(skills=["  "]), "no letters or digits"),
    (candidate(experience_years="8"), "experience_years"),
    (candidate(experience_years=-1), "experience_years"),
    (candidate(availability="someday"), "unrecognized availability"),
    ("not an object", "record"),
])
def test_rejects_invalid_candidate_values(bad_record, expected_message):
    extraction = extract_candidates([bad_record], TODAY)
    assert extraction.records == []
    assert expected_message in extraction.rejected[0].message


def test_keeps_valid_candidates_when_others_are_rejected():
    raw = [candidate(), candidate(name="Ghost", skills=[]), candidate(name="Rick S.")]
    extraction = extract_candidates(raw, TODAY)
    assert [record.slug for record in extraction.records] == ["sherlock-h", "rick-s"]
    assert [error.index for error in extraction.rejected] == [1]


def test_rejects_duplicate_candidate():
    extraction = extract_candidates([candidate(), candidate(name="sherlock  h")], TODAY)
    assert len(extraction.records) == 1
    assert "duplicate of record #0" in extraction.rejected[0].message


def test_ignores_unknown_fields():
    extraction = extract_candidates([candidate(salary=100)], TODAY)
    assert len(extraction.records) == 1
    assert extraction.rejected == []


def test_normalizes_candidate_skills_and_availability():
    record = candidate(skills=["Stakeholder Management", "stakeholder-management"], availability="2 weeks")
    [extracted] = extract_candidates([record], TODAY).records
    assert extracted.skill_slugs == ["stakeholder-management"]
    assert extracted.open_to_opportunities is True
    assert extracted.available_from == date(2026, 11, 11)


def test_candidate_batch_columns_line_up():
    raw = [
        candidate(),
        candidate(name="Ron S.", skills=["negotiation"], experience_years=15,
                  availability="Not looking", traits=["stubborn"]),
    ]
    batch = build_candidate_batch(extract_candidates(raw, TODAY).records)

    assert batch.slugs == ["sherlock-h", "ron-s"]
    assert batch.experience_years == [8, 15]
    assert batch.open_to_opportunities == [True, False]
    assert batch.available_from == [TODAY, None]
    assert batch.skill_links == [("sherlock-h", "deduction"), ("ron-s", "negotiation")]
    assert batch.trait_links == [("ron-s", "stubborn")]


def test_seed_candidate_batch_sizes():
    records = extract_candidates(read_json_records(SEED_DIR / "candidate_data.json"), TODAY).records
    batch = build_candidate_batch(records)
    assert len(batch.slugs) == 15
    assert len(batch.skill_links) == 50
    assert len(batch.trait_links) == 30
