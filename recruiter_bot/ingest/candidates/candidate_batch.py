from dataclasses import dataclass
from datetime import date
from typing import Any

from recruiter_bot.ingest.candidates.candidate_extractor import CandidateRecord


@dataclass(frozen=True)
class CandidateBatch:
    slugs: list[str]
    full_names: list[str]
    experience_years: list[int]
    open_to_opportunities: list[bool]
    available_from: list[date | None]
    quirks: list[str | None]
    skill_links: list[tuple[str, str]]  # (candidate slug, skill slug)
    trait_links: list[tuple[str, str]]  # (candidate slug, trait slug)
    job_preference_links: list[tuple[str, str]]  # (candidate slug, preference slug)
    payloads: list[Any]                 # raw input, written to ingestion_events only


def build_candidate_batch(records: list[CandidateRecord]) -> CandidateBatch:
    slugs = []
    full_names = []
    experience_years = []
    open_to_opportunities = []
    available_from = []
    quirks = []
    skill_links = []
    trait_links = []
    job_preference_links = []
    payloads = []

    for record in records:
        slugs.append(record.slug)
        full_names.append(record.full_name)
        experience_years.append(record.experience_years)
        open_to_opportunities.append(record.open_to_opportunities)
        available_from.append(record.available_from)
        quirks.append(record.quirk)
        payloads.append(record.payload)

        for skill_slug in record.skill_slugs:
            skill_links.append((record.slug, skill_slug))
        for trait_slug in record.trait_slugs:
            trait_links.append((record.slug, trait_slug))
        for preference in record.job_preference_slugs:
            job_preference_links.append((record.slug, preference))

    return CandidateBatch(
        slugs=slugs,
        full_names=full_names,
        experience_years=experience_years,
        open_to_opportunities=open_to_opportunities,
        available_from=available_from,
        quirks=quirks,
        skill_links=skill_links,
        trait_links=trait_links,
        job_preference_links=job_preference_links,
        payloads=payloads,
    )
