from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from recruiter_bot.ingest.record_errors import RecordError, describe_validation_error
from recruiter_bot.ingest.text_normalizer import normalize_list, normalize_required, parse_availability


class CandidateInput(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str = Field(min_length=1)
    skills: list[str] = Field(min_length=1)
    experience_years: int = Field(ge=0, le=70, strict=True)
    availability: str = Field(min_length=1)
    traits: list[str] = []
    quirk: str | None = None


@dataclass(frozen=True)
class CandidateRecord:
    slug: str
    full_name: str
    experience_years: int
    open_to_opportunities: bool
    available_from: date | None
    quirk: str | None
    skill_slugs: list[str]
    trait_slugs: list[str]
    payload: Any


@dataclass(frozen=True)
class CandidateExtraction:
    records: list[CandidateRecord]
    rejected: list[RecordError]


def extract_candidates(raw_candidates: list[Any], today: date) -> CandidateExtraction:
    """Required fields: name, skills (at least one), experience_years, availability."""
    records = []
    rejected = []
    index_by_slug = {}

    for index, raw_candidate in enumerate(raw_candidates):
        try:
            record = _build_candidate_record(raw_candidate, today)
        except ValidationError as error:
            rejected.append(RecordError(index, raw_candidate, describe_validation_error(error)))
            continue
        except ValueError as error:
            rejected.append(RecordError(index, raw_candidate, str(error)))
            continue

        if record.slug in index_by_slug:
            first_index = index_by_slug[record.slug]
            message = f"duplicate of record #{first_index} (slug {record.slug!r})"
            rejected.append(RecordError(index, raw_candidate, message))
            continue

        index_by_slug[record.slug] = index
        records.append(record)

    return CandidateExtraction(records, rejected)


def _build_candidate_record(raw_candidate: Any, today: date) -> CandidateRecord:
    candidate = CandidateInput.model_validate(raw_candidate)
    open_to_opportunities, available_from = parse_availability(candidate.availability, today)

    return CandidateRecord(
        slug=normalize_required(candidate.name, "name"),
        full_name=candidate.name,
        experience_years=candidate.experience_years,
        open_to_opportunities=open_to_opportunities,
        available_from=available_from,
        quirk=candidate.quirk,
        skill_slugs=normalize_list(candidate.skills, "skill"),
        trait_slugs=normalize_list(candidate.traits, "trait"),
        payload=raw_candidate,
    )
