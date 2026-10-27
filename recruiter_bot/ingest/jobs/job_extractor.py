from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from recruiter_bot.ingest.record_errors import RecordError, describe_validation_error
from recruiter_bot.ingest.text_normalizer import normalize_list, normalize_required


class JobInput(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    title: str = Field(min_length=1)
    required_skills: list[str] = Field(min_length=1)
    min_experience_years: int = Field(ge=0, le=70, strict=True)
    culture_keywords: list[str] = []
    tagline: str | None = None


@dataclass(frozen=True)
class JobRecord:
    slug: str
    title: str
    min_experience_years: int
    tagline: str | None
    skill_slugs: list[str]
    culture_trait_slugs: list[str]
    payload: Any


@dataclass(frozen=True)
class JobExtraction:
    records: list[JobRecord]
    rejected: list[RecordError]


def extract_jobs(raw_jobs: list[Any]) -> JobExtraction:
    """Required fields: title, required_skills (at least one), min_experience_years."""
    records = []
    rejected = []
    index_by_slug = {}

    for index, raw_job in enumerate(raw_jobs):
        try:
            record = _build_job_record(raw_job)
        except ValidationError as error:
            rejected.append(RecordError(index, raw_job, describe_validation_error(error)))
            continue
        except ValueError as error:
            rejected.append(RecordError(index, raw_job, str(error)))
            continue

        if record.slug in index_by_slug:
            first_index = index_by_slug[record.slug]
            message = f"duplicate of record #{first_index} (slug {record.slug!r})"
            rejected.append(RecordError(index, raw_job, message))
            continue

        index_by_slug[record.slug] = index
        records.append(record)

    return JobExtraction(records, rejected)


def _build_job_record(raw_job: Any) -> JobRecord:
    job = JobInput.model_validate(raw_job)

    return JobRecord(
        slug=normalize_required(job.title, "title"),
        title=job.title,
        min_experience_years=job.min_experience_years,
        tagline=job.tagline,
        skill_slugs=normalize_list(job.required_skills, "skill"),
        culture_trait_slugs=normalize_list(job.culture_keywords, "culture keyword"),
        payload=raw_job,
    )
