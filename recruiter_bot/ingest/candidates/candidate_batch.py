from dataclasses import dataclass
from datetime import date
from typing import Any

from recruiter_bot.ingest.candidates.candidate_extractor import CandidateRecord


@dataclass(frozen=True)
class CandidateBatch:
    source_keys: list[str]
    slugs: list[str]
    full_names: list[str]
    emails: list[str | None]
    experience_years: list[int]
    open_to_opportunities: list[bool]
    available_from: list[date | None]
    quirks: list[str | None]
    skill_links: list[tuple[str, str]]  # (candidate source key, skill slug)
    trait_links: list[tuple[str, str]]  # (candidate source key, trait slug)
    job_preference_links: list[tuple[str, str]]  # (candidate source key, preference slug)
    payloads: list[Any]                 # raw input, written to ingestion_events only


def build_candidate_batch(records: list[CandidateRecord]) -> CandidateBatch:
    source_keys = []
    slugs = []
    full_names = []
    emails = []
    experience_years = []
    open_to_opportunities = []
    available_from = []
    quirks = []
    skill_links = []
    trait_links = []
    job_preference_links = []
    payloads = []

    for record in records:
        source_keys.append(record.source_key)
        slugs.append(record.slug)
        full_names.append(record.full_name)
        emails.append(record.email)
        experience_years.append(record.experience_years)
        open_to_opportunities.append(record.open_to_opportunities)
        available_from.append(record.available_from)
        quirks.append(record.quirk)
        payloads.append(record.payload)

        for skill_slug in record.skill_slugs:
            skill_links.append((record.source_key, skill_slug))
        for trait_slug in record.trait_slugs:
            trait_links.append((record.source_key, trait_slug))
        for preference in record.job_preference_slugs:
            job_preference_links.append((record.source_key, preference))

    return CandidateBatch(
        source_keys=source_keys,
        slugs=slugs,
        full_names=full_names,
        emails=emails,
        experience_years=experience_years,
        open_to_opportunities=open_to_opportunities,
        available_from=available_from,
        quirks=quirks,
        skill_links=skill_links,
        trait_links=trait_links,
        job_preference_links=job_preference_links,
        payloads=payloads,
    )
