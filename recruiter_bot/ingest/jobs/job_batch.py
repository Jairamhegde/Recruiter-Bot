from dataclasses import dataclass
from typing import Any

from recruiter_bot.ingest.jobs.job_extractor import JobRecord


@dataclass(frozen=True)
class JobBatch:
    slugs: list[str]
    titles: list[str]
    min_experience_years: list[int]
    taglines: list[str | None]
    skill_links: list[tuple[str, str]]          # (job slug, skill slug)
    culture_trait_links: list[tuple[str, str]]  # (job slug, trait slug)
    payloads: list[Any]                         # raw input, written to ingestion_events only


def build_job_batch(records: list[JobRecord]) -> JobBatch:
    slugs = []
    titles = []
    min_experience_years = []
    taglines = []
    skill_links = []
    culture_trait_links = []
    payloads = []

    for record in records:
        slugs.append(record.slug)
        titles.append(record.title)
        min_experience_years.append(record.min_experience_years)
        taglines.append(record.tagline)
        payloads.append(record.payload)

        for skill_slug in record.skill_slugs:
            skill_links.append((record.slug, skill_slug))
        for trait_slug in record.culture_trait_slugs:
            culture_trait_links.append((record.slug, trait_slug))

    return JobBatch(
        slugs=slugs,
        titles=titles,
        min_experience_years=min_experience_years,
        taglines=taglines,
        skill_links=skill_links,
        culture_trait_links=culture_trait_links,
        payloads=payloads,
    )
