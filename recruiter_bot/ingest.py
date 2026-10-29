"""Validates candidate and job input, and stores it. The seed and the POST endpoints both use this."""
import re
import unicodedata
from typing import ClassVar, Literal

import psycopg
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

DAYS_PER_UNIT = {"day": 1, "week": 7, "month": 30}
SYMBOL_WORDS = {"+": "plus", "#": "sharp"}


# ---- Cleaning terms

def normalize(text: str) -> str:
    """'  Stakeholder   Management ' -> 'stakeholder-management'"""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    for symbol, word in SYMBOL_WORDS.items():
        ascii_text = ascii_text.replace(symbol, word)  # c++ and c# stay different words
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")


def compact_key(slug: str) -> str:
    """'team-building' and 'teambuilding' are the same word."""
    return slug.replace("-", "")


def normalize_list(values: list[str], field_name: str) -> list[str]:
    """Normalizes each value and drops duplicates, keeping the original order."""
    result = []
    for value in values:
        slug = normalize(value)
        if slug == "":
            raise ValueError(f"{field_name} {value!r} has no letters or digits")
        if slug not in result:
            result.append(slug)
    return result


def parse_availability(text: str) -> tuple[bool, int | None]:
    """Returns (open_to_opportunities, days from today until they can start)."""
    value = " ".join(text.lower().split())
    if value == "not looking":
        return False, None
    if value in ("immediate", "immediately", "now"):
        return True, 0

    match = re.fullmatch(r"(\d+)\s*(day|week|month)s?", value)
    if match is None:
        raise ValueError(f"unrecognized availability {text!r}")
    return True, int(match.group(1)) * DAYS_PER_UNIT[match.group(2)]


# ---- Input: anything invalid is rejected here, before a single write (the API answers 422)

class CandidateInput(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str = Field(min_length=1)  # not unique: people share names
    skills: list[str] = Field(min_length=1)
    experience_years: int = Field(ge=0, le=70, strict=True)
    availability: str = Field(min_length=1)  # "Immediate", "2 weeks" or "Not looking"
    traits: list[str] = []
    quirk: str | None = None

    @field_validator("skills", "traits")
    @classmethod
    def _normalize_terms(cls, values: list[str], info: ValidationInfo) -> list[str]:
        return normalize_list(values, info.field_name)

    @field_validator("availability")
    @classmethod
    def _known_availability(cls, text: str) -> str:
        parse_availability(text)
        return text


class JobInput(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    title: str = Field(min_length=1)
    required_skills: list[str] = Field(min_length=1)
    min_experience_years: int = Field(ge=0, le=70, strict=True)
    # "required" (the default) makes the minimum a must; "preferred" makes it count, never exclude.
    experience_requirement: Literal["required", "preferred"] = "required"
    culture_keywords: list[str] = []
    tagline: str | None = None

    @field_validator("required_skills", "culture_keywords")
    @classmethod
    def _normalize_terms(cls, values: list[str], info: ValidationInfo) -> list[str]:
        return normalize_list(values, info.field_name)


# ---- PATCH input: every field optional, with the same rules as above

class Patch(BaseModel):
    # Unknown fields are refused, so a typo like "skils" fails instead of silently doing nothing.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    REQUIRED_FIELDS: ClassVar[tuple[str, ...]] = ()

    @model_validator(mode="after")
    def _required_fields_cannot_be_cleared(self):
        for name in self.REQUIRED_FIELDS:
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} can be changed but not removed")
        return self


class CandidatePatch(Patch):
    REQUIRED_FIELDS = ("name", "skills", "experience_years", "availability")

    name: str | None = Field(default=None, min_length=1)
    skills: list[str] | None = Field(default=None, min_length=1)
    experience_years: int | None = Field(default=None, ge=0, le=70, strict=True)
    availability: str | None = Field(default=None, min_length=1)
    traits: list[str] | None = None
    quirk: str | None = None  # null clears it

    @field_validator("skills", "traits")
    @classmethod
    def _normalize_terms(cls, values: list[str] | None, info: ValidationInfo) -> list[str] | None:
        return None if values is None else normalize_list(values, info.field_name)

    @field_validator("availability")
    @classmethod
    def _known_availability(cls, text: str | None) -> str | None:
        if text is not None:
            parse_availability(text)
        return text


class JobPatch(Patch):
    REQUIRED_FIELDS = ("title", "required_skills", "min_experience_years", "experience_requirement")

    title: str | None = Field(default=None, min_length=1)
    required_skills: list[str] | None = Field(default=None, min_length=1)
    min_experience_years: int | None = Field(default=None, ge=0, le=70, strict=True)
    experience_requirement: Literal["required", "preferred"] | None = None
    culture_keywords: list[str] | None = None
    tagline: str | None = None  # null clears it

    @field_validator("required_skills", "culture_keywords")
    @classmethod
    def _normalize_terms(cls, values: list[str] | None, info: ValidationInfo) -> list[str] | None:
        return None if values is None else normalize_list(values, info.field_name)


# ---- Storing

# The date is computed by the database, so "2 weeks" doesn't depend on the runner's clock.
INSERT_CANDIDATE_SQL = """
    INSERT INTO candidates (full_name, experience_years, open_to_opportunities, available_from, quirk)
    VALUES (%s, %s, %s, current_date + %s::int, %s)
    RETURNING candidate_id
"""

INSERT_JOB_SQL = """
    INSERT INTO jobs (title, min_experience_years, experience_requirement, tagline)
    VALUES (%s, %s, %s, %s)
    RETURNING job_id
"""

# New words are added to the vocabulary first, so the link step can find every id.
# Each new word is looked up in the taxonomy once, here, and keeps the concept it means.
ADD_WORDS_SQL = {
    "skills": """
        INSERT INTO skills (slug, concept_id)
        SELECT word, (SELECT concept_id FROM concept_labels
                      WHERE concept_type = 'skill' AND compact_label = replace(word, '-', ''))
        FROM unnest(%s::text[]) AS word
        ON CONFLICT DO NOTHING
    """,
    "traits": """
        INSERT INTO traits (slug, concept_id)
        SELECT word, (SELECT concept_id FROM concept_labels
                      WHERE concept_type = 'trait' AND compact_label = replace(word, '-', ''))
        FROM unnest(%s::text[]) AS word
        ON CONFLICT DO NOTHING
    """,
}

LINK_SQL = {
    "candidate_skills": """
        INSERT INTO candidate_skills (candidate_id, skill_id)
        SELECT %s, skill_id FROM skills WHERE slug = ANY(%s)
    """,
    "candidate_traits": """
        INSERT INTO candidate_traits (candidate_id, trait_id)
        SELECT %s, trait_id FROM traits WHERE slug = ANY(%s)
    """,
    "job_skills": """
        INSERT INTO job_skills (job_id, skill_id)
        SELECT %s, skill_id FROM skills WHERE slug = ANY(%s)
    """,
    "job_culture_traits": """
        INSERT INTO job_culture_traits (job_id, trait_id)
        SELECT %s, trait_id FROM traits WHERE slug = ANY(%s)
    """,
}

VOCABULARY_OF = {
    "candidate_skills": "skills", "candidate_traits": "traits",
    "job_skills": "skills", "job_culture_traits": "traits",
}


def insert_candidate(conn: psycopg.Connection, candidate: CandidateInput) -> int:
    """Stores one candidate with their skills and traits, and returns the new id."""
    open_to_opportunities, start_in_days = parse_availability(candidate.availability)

    candidate_id = conn.execute(INSERT_CANDIDATE_SQL, (
        candidate.name, candidate.experience_years, open_to_opportunities, start_in_days, candidate.quirk,
    )).fetchone()[0]
    _link(conn, "candidate_skills", candidate_id, candidate.skills)
    _link(conn, "candidate_traits", candidate_id, candidate.traits)
    return candidate_id


def insert_job(conn: psycopg.Connection, job: JobInput) -> int:
    """Stores one job with its skills and culture keywords, and returns the new id."""
    job_id = conn.execute(INSERT_JOB_SQL, (
        job.title, job.min_experience_years, job.experience_requirement, job.tagline,
    )).fetchone()[0]
    _link(conn, "job_skills", job_id, job.required_skills)
    _link(conn, "job_culture_traits", job_id, job.culture_keywords)
    return job_id


# ---- Updating: unsent fields keep their stored value; a sent list replaces the stored list

UPDATE_CANDIDATE_SQL = """
    UPDATE candidates
    SET full_name             = CASE WHEN %(set_name)s THEN %(name)s ELSE full_name END,
        experience_years      = CASE WHEN %(set_years)s THEN %(years)s ELSE experience_years END,
        open_to_opportunities = CASE WHEN %(set_availability)s THEN %(open)s ELSE open_to_opportunities END,
        available_from        = CASE WHEN %(set_availability)s THEN current_date + %(days)s::int
                                     ELSE available_from END,
        quirk                 = CASE WHEN %(set_quirk)s THEN %(quirk)s ELSE quirk END
    WHERE candidate_id = %(id)s
    RETURNING candidate_id
"""

UPDATE_JOB_SQL = """
    UPDATE jobs
    SET title                  = CASE WHEN %(set_title)s THEN %(title)s ELSE title END,
        min_experience_years   = CASE WHEN %(set_years)s THEN %(years)s ELSE min_experience_years END,
        experience_requirement = CASE WHEN %(set_requirement)s THEN %(requirement)s ELSE experience_requirement END,
        tagline                = CASE WHEN %(set_tagline)s THEN %(tagline)s ELSE tagline END
    WHERE job_id = %(id)s
    RETURNING job_id
"""

UNLINK_SQL = {
    "candidate_skills": "DELETE FROM candidate_skills WHERE candidate_id = %s",
    "candidate_traits": "DELETE FROM candidate_traits WHERE candidate_id = %s",
    "job_skills": "DELETE FROM job_skills WHERE job_id = %s",
    "job_culture_traits": "DELETE FROM job_culture_traits WHERE job_id = %s",
}


def update_candidate(conn: psycopg.Connection, candidate_id: int, patch: CandidatePatch) -> bool:
    """Changes only the fields sent. False if there is no such candidate."""
    sent = patch.model_fields_set
    open_to_opportunities, start_in_days = (
        parse_availability(patch.availability) if "availability" in sent else (None, None)
    )
    row = conn.execute(UPDATE_CANDIDATE_SQL, {
        "id": candidate_id,
        "set_name": "name" in sent, "name": patch.name,
        "set_years": "experience_years" in sent, "years": patch.experience_years,
        "set_availability": "availability" in sent, "open": open_to_opportunities, "days": start_in_days,
        "set_quirk": "quirk" in sent, "quirk": patch.quirk,
    }).fetchone()
    if row is None:
        return False
    if "skills" in sent:
        _relink(conn, "candidate_skills", candidate_id, patch.skills)
    if "traits" in sent:
        _relink(conn, "candidate_traits", candidate_id, patch.traits or [])
    return True


def update_job(conn: psycopg.Connection, job_id: int, patch: JobPatch) -> bool:
    """Changes only the fields sent. False if there is no such job."""
    sent = patch.model_fields_set
    row = conn.execute(UPDATE_JOB_SQL, {
        "id": job_id,
        "set_title": "title" in sent, "title": patch.title,
        "set_years": "min_experience_years" in sent, "years": patch.min_experience_years,
        "set_requirement": "experience_requirement" in sent, "requirement": patch.experience_requirement,
        "set_tagline": "tagline" in sent, "tagline": patch.tagline,
    }).fetchone()
    if row is None:
        return False
    if "required_skills" in sent:
        _relink(conn, "job_skills", job_id, patch.required_skills)
    if "culture_keywords" in sent:
        _relink(conn, "job_culture_traits", job_id, patch.culture_keywords or [])
    return True


def _relink(conn: psycopg.Connection, table: str, record_id: int, slugs: list[str]) -> None:
    conn.execute(UNLINK_SQL[table], (record_id,))
    _link(conn, table, record_id, slugs)


def _link(conn: psycopg.Connection, table: str, record_id: int, slugs: list[str]) -> None:
    if slugs:
        conn.execute(ADD_WORDS_SQL[VOCABULARY_OF[table]], (slugs,))
        conn.execute(LINK_SQL[table], (record_id, slugs))
