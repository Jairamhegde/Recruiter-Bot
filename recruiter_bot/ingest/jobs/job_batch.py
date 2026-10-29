from dataclasses import dataclass
from typing import Any

from recruiter_bot.ingest.jobs.job_extractor import JobRecord


@dataclass(frozen=True)
class JobBatch:
    source_keys: list[str]
    slugs: list[str]
    titles: list[str]
    companies: list[str | None]
    min_experience_years: list[int]
    experience_requirements: list[str]
    taglines: list[str | None]
    skill_links: list[tuple[str, str]]          # (job source key, skill slug)
    culture_trait_links: list[tuple[str, str]]  # (job source key, trait slug)
    payloads: list[Any]                         # raw input, written to ingestion_events only


def build_job_batch(records: list[JobRecord]) -> JobBatch:
    source_keys = []
    slugs = []
    titles = []
    companies = []
    min_experience_years = []
    experience_requirements = []
    taglines = []
    skill_links = []
    culture_trait_links = []
    payloads = []

    for record in records:
        source_keys.append(record.source_key)
        slugs.append(record.slug)
        titles.append(record.title)
        companies.append(record.company)
        min_experience_years.append(record.min_experience_years)
        experience_requirements.append(record.experience_requirement)
        taglines.append(record.tagline)
        payloads.append(record.payload)

        for skill_slug in record.skill_slugs:
            skill_links.append((record.source_key, skill_slug))
        for trait_slug in record.culture_trait_slugs:
            culture_trait_links.append((record.source_key, trait_slug))

    return JobBatch(
        source_keys=source_keys,
        slugs=slugs,
        titles=titles,
        companies=companies,
        min_experience_years=min_experience_years,
        experience_requirements=experience_requirements,
        taglines=taglines,
        skill_links=skill_links,
        culture_trait_links=culture_trait_links,
        payloads=payloads,
    )
