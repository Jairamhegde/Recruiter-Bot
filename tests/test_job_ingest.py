from pathlib import Path

import pytest

from recruiter_bot.ingest import build_job_batch, extract_jobs, read_json_records

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"


def job(**overrides):
    record = {"title": "Backend Detective", "required_skills": ["deduction"], "min_experience_years": 3}
    record.update(overrides)
    return record


def test_reads_job_seed_file():
    assert len(read_json_records(SEED_DIR / "job_data.json")) == 6


def test_all_seed_jobs_are_valid():
    extraction = extract_jobs(read_json_records(SEED_DIR / "job_data.json"))
    assert len(extraction.records) == 6
    assert extraction.rejected == []


@pytest.mark.parametrize("missing_field", ["title", "required_skills", "min_experience_years"])
def test_rejects_job_missing_required_field(missing_field):
    record = job()
    del record[missing_field]
    extraction = extract_jobs([record])
    assert extraction.records == []
    assert missing_field in extraction.rejected[0].message


@pytest.mark.parametrize("bad_record, expected_message", [
    (job(required_skills=[]), "required_skills"),
    (job(required_skills=["  "]), "no letters or digits"),
    (job(min_experience_years="3"), "min_experience_years"),
    (job(min_experience_years=-1), "min_experience_years"),
    (job(title="  ,  "), "no letters or digits"),
    ("not an object", "record"),
])
def test_rejects_invalid_job_values(bad_record, expected_message):
    extraction = extract_jobs([bad_record])
    assert extraction.records == []
    assert expected_message in extraction.rejected[0].message


def test_keeps_valid_jobs_when_others_are_rejected():
    raw = [job(), job(title="Ghost Job", required_skills=[]), job(title="Sales Engineer")]
    extraction = extract_jobs(raw)
    assert [record.slug for record in extraction.records] == ["backend-detective", "sales-engineer"]
    assert [error.index for error in extraction.rejected] == [1]


def test_rejects_duplicate_job():
    extraction = extract_jobs([job(), job(title="backend   detective")])
    assert len(extraction.records) == 1
    assert "duplicate of record #0" in extraction.rejected[0].message


def test_optional_job_fields_can_be_missing():
    [extracted] = extract_jobs([job()]).records
    assert extracted.culture_trait_slugs == []
    assert extracted.tagline is None


def test_normalizes_job_skills_and_culture_keywords():
    record = job(
        title="Engineering Manager, Chaos Team",
        required_skills=["Team Building", "  Stakeholder   Management ", "leadership"],
        culture_keywords=["Calm Under Pressure"],
    )
    [extracted] = extract_jobs([record]).records
    assert extracted.slug == "engineering-manager-chaos-team"
    assert extracted.skill_slugs == ["team-building", "stakeholder-management", "leadership"]
    assert extracted.culture_trait_slugs == ["calm-under-pressure"]


def test_job_batch_columns_line_up():
    raw = [job(culture_keywords=["analytical"]), job(title="Sales Engineer", required_skills=["sales"])]
    batch = build_job_batch(extract_jobs(raw).records)

    assert batch.slugs == ["backend-detective", "sales-engineer"]
    assert batch.min_experience_years == [3, 3]
    assert batch.skill_links == [("backend-detective", "deduction"), ("sales-engineer", "sales")]
    assert batch.culture_trait_links == [("backend-detective", "analytical")]


def test_seed_job_batch_sizes():
    records = extract_jobs(read_json_records(SEED_DIR / "job_data.json")).records
    batch = build_job_batch(records)
    assert len(batch.slugs) == 6
    assert len(batch.skill_links) == 16
    assert len(batch.culture_trait_links) == 12
