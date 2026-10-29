from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from recruiter_bot.ingest.record_keys import source_key_for
from recruiter_bot.ingest.record_errors import RecordError, describe_validation_error
from recruiter_bot.ingest.text_normalizer import normalize_list, normalize_required


class JobInput(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    title: str = Field(min_length=1)
    company: str | None = Field(default=None, min_length=1)  # optional; a title is unique within a company
    required_skills: list[str] = Field(min_length=1)
    min_experience_years: int = Field(ge=0, le=70, strict=True)
    # "required" (the default) makes the minimum a must; "preferred" makes it count, never exclude.
    experience_requirement: Literal["required", "preferred"] = "required"
    culture_keywords: list[str] = []
    tagline: str | None = None


@dataclass(frozen=True)
class JobRecord:
    source_key: str
    slug: str
    title: str
    company: str | None
    min_experience_years: int
    experience_requirement: str
    tagline: str | None
    skill_slugs: list[str]
    culture_trait_slugs: list[str]
    payload: Any


@dataclass(frozen=True)
class JobExtraction:
    records: list[JobRecord]
    rejected: list[RecordError]


def extract_jobs(raw_jobs: list[Any], source: str = "seed") -> JobExtraction:
    """Required fields: title, required_skills (at least one), min_experience_years."""
    records = []
    rejected = []
    index_by_key = {}
    index_by_company_title = {}

    for index, raw_job in enumerate(raw_jobs):
        try:
            record = _build_job_record(raw_job, source)
        except ValidationError as error:
            rejected.append(RecordError(index, raw_job, describe_validation_error(error)))
            continue
        except ValueError as error:
            rejected.append(RecordError(index, raw_job, str(error)))
            continue

        company_title = (record.company.lower(), record.slug) if record.company else None
        if record.source_key in index_by_key:
            message = f"duplicate of record #{index_by_key[record.source_key]} (key {record.source_key!r})"
            rejected.append(RecordError(index, raw_job, message))
            continue
        if company_title is not None and company_title in index_by_company_title:
            message = f"duplicate of record #{index_by_company_title[company_title]} (same company and title)"
            rejected.append(RecordError(index, raw_job, message))
            continue

        index_by_key[record.source_key] = index
        if company_title is not None:
            index_by_company_title[company_title] = index
        records.append(record)

    return JobExtraction(records, rejected)


def _build_job_record(raw_job: Any, source: str) -> JobRecord:
    job = JobInput.model_validate(raw_job)

    slug = normalize_required(job.title, "title")

    return JobRecord(
        source_key=source_key_for(source, slug),
        slug=slug,
        title=job.title,
        company=job.company,
        min_experience_years=job.min_experience_years,
        experience_requirement=job.experience_requirement,
        tagline=job.tagline,
        skill_slugs=normalize_list(job.required_skills, "skill"),
        culture_trait_slugs=normalize_list(job.culture_keywords, "culture keyword"),
        payload=raw_job,
    )
