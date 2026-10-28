from typing import Any

import psycopg
from pydantic import BaseModel, ConfigDict, Field, model_validator

from recruiter_bot.ingest.batch_inserter import INGEST_LOCK_SQL
from recruiter_bot.ingest.event_log_writer import log_accepted, log_rejected
from recruiter_bot.ingest.jobs.job_creator import JobExists, JobRejected
from recruiter_bot.ingest.record_errors import RecordError
from recruiter_bot.ingest.text_normalizer import normalize_list, normalize_required
from recruiter_bot.ingest.vocabulary_writer import resolve_skill_ids, resolve_trait_ids
from recruiter_bot.ingest.taxonomy.term_linker import link_record_terms
from recruiter_bot.matching.match_store import refresh_job_matches

REQUIRED_FIELDS = ("title", "required_skills", "min_experience_years")


class JobNotFound(LookupError):
    pass


class JobPatch(BaseModel):
    """Every field optional; the constraints match JobInput (D-38)."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1)
    required_skills: list[str] | None = Field(default=None, min_length=1)
    min_experience_years: int | None = Field(default=None, ge=0, le=70, strict=True)
    culture_keywords: list[str] | None = None
    tagline: str | None = None  # null clears it

    @model_validator(mode="after")
    def required_fields_cannot_be_cleared(self) -> "JobPatch":
        for field in REQUIRED_FIELDS:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} can be changed but not removed")
        return self


CURRENT_JOB_SQL = """
    SELECT slug, title, min_experience_years, tagline
    FROM jobs
    WHERE job_id = %s
    FOR UPDATE
"""

OTHER_JOB_WITH_SLUG_SQL = "SELECT EXISTS (SELECT 1 FROM jobs WHERE slug = %s AND job_id <> %s)"

UPDATE_JOB_SQL = """
    UPDATE jobs
    SET slug = %s, title = %s, min_experience_years = %s, tagline = %s
    WHERE job_id = %s
"""

REPLACE_SKILLS_DELETE_SQL = "DELETE FROM job_skills WHERE job_id = %s"

REPLACE_SKILLS_INSERT_SQL = """
    INSERT INTO job_skills (job_id, skill_id)
    SELECT %s, unnest(%s::bigint[])
    ON CONFLICT DO NOTHING
"""

REPLACE_CULTURE_DELETE_SQL = "DELETE FROM job_culture_traits WHERE job_id = %s"

REPLACE_CULTURE_INSERT_SQL = """
    INSERT INTO job_culture_traits (job_id, trait_id)
    SELECT %s, unnest(%s::bigint[])
    ON CONFLICT DO NOTHING
"""


def update_job(conn: psycopg.Connection, job_id: int, patch: JobPatch, source: str = "api") -> None:
    """Applies the sent fields and refreshes the job's matches, all in one transaction (D-38)."""
    sent = patch.model_dump(include=patch.model_fields_set)

    # Normalize before writing anything, with the same rules as ingestion (D-02).
    try:
        slug = normalize_required(patch.title, "title") if "title" in sent else None
        skill_slugs = normalize_list(patch.required_skills, "skill") if "required_skills" in sent else None
        culture_slugs = normalize_list(patch.culture_keywords or [], "trait") if "culture_keywords" in sent else None
    except ValueError as error:
        log_rejected(conn, "job", source, [RecordError(0, _payload(job_id, sent), str(error))])
        raise JobRejected(str(error))

    with conn.transaction():
        conn.execute(INGEST_LOCK_SQL)
        current = conn.execute(CURRENT_JOB_SQL, (job_id,)).fetchone()
        if current is None:
            raise JobNotFound(f"No job with id {job_id}")
        current_slug, title, min_experience_years, tagline = current

        if slug is not None and conn.execute(OTHER_JOB_WITH_SLUG_SQL, (slug, job_id)).fetchone()[0]:
            raise JobExists(f"a job titled {patch.title!r} already exists")

        conn.execute(UPDATE_JOB_SQL, (
            slug or current_slug,
            patch.title if "title" in sent else title,
            patch.min_experience_years if "min_experience_years" in sent else min_experience_years,
            patch.tagline if "tagline" in sent else tagline,
            job_id,
        ))
        if skill_slugs is not None:
            skill_ids = resolve_skill_ids(conn, skill_slugs)
            conn.execute(REPLACE_SKILLS_DELETE_SQL, (job_id,))
            conn.execute(REPLACE_SKILLS_INSERT_SQL, (job_id, [skill_ids[s] for s in skill_slugs]))
        if culture_slugs is not None:
            trait_ids = resolve_trait_ids(conn, culture_slugs)
            conn.execute(REPLACE_CULTURE_DELETE_SQL, (job_id,))
            conn.execute(REPLACE_CULTURE_INSERT_SQL, (job_id, [trait_ids[t] for t in culture_slugs]))

        log_accepted(conn, "job", source, [slug or current_slug], [_payload(job_id, sent)])
        # Same transaction, so nobody sees the new job with old matches (D-37).
        # Unknown words are linked first, so this record's matches already use the links (D-41).
        link_record_terms(conn, skill_slugs, culture_slugs)
        refresh_job_matches(conn, job_id)


def _payload(job_id: int, sent: dict[str, Any]) -> dict[str, Any]:
    return {"patch_job_id": job_id, **sent}
