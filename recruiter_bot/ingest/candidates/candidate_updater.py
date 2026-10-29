from typing import Any

import psycopg
from pydantic import BaseModel, ConfigDict, Field, model_validator

from recruiter_bot.ingest.batch_inserter import INGEST_LOCK_SQL
from recruiter_bot.ingest.candidates.candidate_creator import CandidateExists, CandidateRejected
from recruiter_bot.ingest.candidates.candidate_extractor import EMAIL_PATTERN
from recruiter_bot.ingest.event_log_writer import log_accepted, log_rejected
from recruiter_bot.ingest.record_errors import RecordError
from recruiter_bot.ingest.text_normalizer import normalize_list, normalize_required, parse_availability
from recruiter_bot.ingest.vocabulary_writer import resolve_skill_ids, resolve_trait_ids
from recruiter_bot.ingest.taxonomy.term_linker import link_record_terms
from recruiter_bot.matching.match_store import refresh_candidate_matches

REQUIRED_FIELDS = ("name", "skills", "experience_years", "availability")


class CandidateNotFound(LookupError):
    pass


class CandidatePatch(BaseModel):
    """Every field optional; the constraints match CandidateInput."""
    # Unknown fields are refused, so a typo like "skils" fails instead of silently doing nothing.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1)
    email: str | None = Field(default=None, pattern=EMAIL_PATTERN)  # null clears it
    skills: list[str] | None = Field(default=None, min_length=1)
    experience_years: int | None = Field(default=None, ge=0, le=70, strict=True)
    availability: str | None = Field(default=None, min_length=1)
    traits: list[str] | None = None
    quirk: str | None = None  # null clears it
    job_preferences: list[str] | None = None  # null clears them; stored, not yet used in matching

    @model_validator(mode="after")
    def required_fields_cannot_be_cleared(self) -> "CandidatePatch":
        for field in REQUIRED_FIELDS:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} can be changed but not removed")
        return self


CURRENT_CANDIDATE_SQL = """
    SELECT slug, full_name, email, experience_years, open_to_opportunities, available_from, quirk
    FROM candidates
    WHERE candidate_id = %s
    FOR UPDATE
"""

OTHER_CANDIDATE_WITH_EMAIL_SQL = "SELECT EXISTS (SELECT 1 FROM candidates WHERE email = %s AND candidate_id <> %s)"

UPDATE_CANDIDATE_SQL = """
    UPDATE candidates
    SET slug = %s, full_name = %s, email = %s, experience_years = %s,
        open_to_opportunities = %s, available_from = %s, quirk = %s
    WHERE candidate_id = %s
"""

REPLACE_SKILLS_DELETE_SQL = "DELETE FROM candidate_skills WHERE candidate_id = %s"

REPLACE_SKILLS_INSERT_SQL = """
    INSERT INTO candidate_skills (candidate_id, skill_id)
    SELECT %s, unnest(%s::bigint[])
    ON CONFLICT DO NOTHING
"""

REPLACE_JOB_PREFERENCES_DELETE_SQL = "DELETE FROM candidate_job_preferences WHERE candidate_id = %s"

REPLACE_JOB_PREFERENCES_INSERT_SQL = """
    INSERT INTO candidate_job_preferences (candidate_id, preference)
    SELECT %s, unnest(%s::text[])
    ON CONFLICT DO NOTHING
"""

REPLACE_TRAITS_DELETE_SQL = "DELETE FROM candidate_traits WHERE candidate_id = %s"

REPLACE_TRAITS_INSERT_SQL = """
    INSERT INTO candidate_traits (candidate_id, trait_id)
    SELECT %s, unnest(%s::bigint[])
    ON CONFLICT DO NOTHING
"""


def update_candidate(conn: psycopg.Connection, candidate_id: int, patch: CandidatePatch, source: str = "api") -> None:
    """Applies the sent fields and refreshes the candidate's matches, all in one transaction."""
    sent = patch.model_dump(include=patch.model_fields_set)
    today = conn.execute("SELECT current_date").fetchone()[0]
    conn.commit()

    # Normalize before writing anything, with the same rules as ingestion.
    try:
        slug = normalize_required(patch.name, "name") if "name" in sent else None
        skill_slugs = normalize_list(patch.skills, "skill") if "skills" in sent else None
        trait_slugs = normalize_list(patch.traits or [], "trait") if "traits" in sent else None
        preference_slugs = (
            normalize_list(patch.job_preferences or [], "job preference") if "job_preferences" in sent else None
        )
        # A changed availability counts from today, the day the person said it.
        availability = parse_availability(patch.availability, today) if "availability" in sent else None
    except ValueError as error:
        log_rejected(conn, "candidate", source, [RecordError(0, _payload(candidate_id, sent), str(error))])
        raise CandidateRejected(str(error))

    with conn.transaction():
        conn.execute(INGEST_LOCK_SQL)
        current = conn.execute(CURRENT_CANDIDATE_SQL, (candidate_id,)).fetchone()
        if current is None:
            raise CandidateNotFound(f"No candidate with id {candidate_id}")
        current_slug, full_name, email, experience_years, open_to_opportunities, available_from, quirk = current

        # Names may repeat; only an email can clash.
        if "email" in sent:
            email = patch.email.lower() if patch.email else None
            if email is not None and conn.execute(OTHER_CANDIDATE_WITH_EMAIL_SQL, (email, candidate_id)).fetchone()[0]:
                raise CandidateExists(f"a candidate with email {email!r} already exists")
        if availability is not None:
            open_to_opportunities, available_from = availability

        conn.execute(UPDATE_CANDIDATE_SQL, (
            slug or current_slug,
            patch.name if "name" in sent else full_name,
            email,
            patch.experience_years if "experience_years" in sent else experience_years,
            open_to_opportunities,
            available_from,
            patch.quirk if "quirk" in sent else quirk,
            candidate_id,
        ))
        if skill_slugs is not None:
            skill_ids = resolve_skill_ids(conn, skill_slugs)
            conn.execute(REPLACE_SKILLS_DELETE_SQL, (candidate_id,))
            conn.execute(REPLACE_SKILLS_INSERT_SQL, (candidate_id, [skill_ids[s] for s in skill_slugs]))
        if trait_slugs is not None:
            trait_ids = resolve_trait_ids(conn, trait_slugs)
            conn.execute(REPLACE_TRAITS_DELETE_SQL, (candidate_id,))
            conn.execute(REPLACE_TRAITS_INSERT_SQL, (candidate_id, [trait_ids[t] for t in trait_slugs]))
        if preference_slugs is not None:
            conn.execute(REPLACE_JOB_PREFERENCES_DELETE_SQL, (candidate_id,))
            conn.execute(REPLACE_JOB_PREFERENCES_INSERT_SQL, (candidate_id, preference_slugs))

        log_accepted(conn, "candidate", source, [slug or current_slug], [_payload(candidate_id, sent)])
        # Same transaction, so the new profile never appears with old matches.
        link_record_terms(conn, skill_slugs, trait_slugs)
        refresh_candidate_matches(conn, candidate_id)


def _payload(candidate_id: int, sent: dict[str, Any]) -> dict[str, Any]:
    return {"patch_candidate_id": candidate_id, **sent}
