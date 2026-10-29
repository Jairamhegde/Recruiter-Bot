from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from recruiter_bot.ingest.record_keys import source_key_for
from recruiter_bot.ingest.record_errors import RecordError, describe_validation_error
from recruiter_bot.ingest.text_normalizer import normalize_list, normalize_required, parse_availability


EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"  # a light check; a real system confirms by sending a message


class CandidateInput(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str = Field(min_length=1)  # not unique: people share names
    email: str | None = Field(default=None, pattern=EMAIL_PATTERN)  # optional; unique when present
    skills: list[str] = Field(min_length=1)
    experience_years: int = Field(ge=0, le=70, strict=True)
    availability: str = Field(min_length=1)
    traits: list[str] = []
    quirk: str | None = None
    # Roles the candidate wants, e.g. "Backend Engineer". Stored, not yet used in matching.
    job_preferences: list[str] = []


@dataclass(frozen=True)
class CandidateRecord:
    source_key: str
    slug: str
    full_name: str
    email: str | None
    experience_years: int
    open_to_opportunities: bool
    available_from: date | None
    quirk: str | None
    skill_slugs: list[str]
    trait_slugs: list[str]
    job_preference_slugs: list[str]
    payload: Any


@dataclass(frozen=True)
class CandidateExtraction:
    records: list[CandidateRecord]
    rejected: list[RecordError]


def extract_candidates(raw_candidates: list[Any], today: date, source: str = "seed") -> CandidateExtraction:
    """Required fields: name, skills (at least one), experience_years, availability."""
    records = []
    rejected = []
    index_by_key = {}
    index_by_email = {}

    for index, raw_candidate in enumerate(raw_candidates):
        try:
            record = _build_candidate_record(raw_candidate, today, source)
        except ValidationError as error:
            rejected.append(RecordError(index, raw_candidate, describe_validation_error(error)))
            continue
        except ValueError as error:
            rejected.append(RecordError(index, raw_candidate, str(error)))
            continue

        if record.source_key in index_by_key:
            message = f"duplicate of record #{index_by_key[record.source_key]} (key {record.source_key!r})"
            rejected.append(RecordError(index, raw_candidate, message))
            continue
        if record.email is not None and record.email in index_by_email:
            message = f"duplicate of record #{index_by_email[record.email]} (email {record.email!r})"
            rejected.append(RecordError(index, raw_candidate, message))
            continue

        index_by_key[record.source_key] = index
        if record.email is not None:
            index_by_email[record.email] = index
        records.append(record)

    return CandidateExtraction(records, rejected)


def _build_candidate_record(raw_candidate: Any, today: date, source: str) -> CandidateRecord:
    candidate = CandidateInput.model_validate(raw_candidate)
    open_to_opportunities, available_from = parse_availability(candidate.availability, today)

    slug = normalize_required(candidate.name, "name")

    return CandidateRecord(
        source_key=source_key_for(source, slug),
        slug=slug,
        full_name=candidate.name,
        email=candidate.email.lower() if candidate.email else None,
        experience_years=candidate.experience_years,
        open_to_opportunities=open_to_opportunities,
        available_from=available_from,
        quirk=candidate.quirk,
        skill_slugs=normalize_list(candidate.skills, "skill"),
        trait_slugs=normalize_list(candidate.traits, "trait"),
        job_preference_slugs=normalize_list(candidate.job_preferences, "job preference"),
        payload=raw_candidate,
    )
