from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from recruiter_bot.db import connect
from recruiter_bot.ingest.batch_inserter import INGEST_LOCK_SQL
from recruiter_bot.ingest.text_normalizer import compact_key, normalize
from recruiter_bot.linking.model_stage import model_linking_status
from recruiter_bot.matching.match_store import refresh_matches_for_terms

router = APIRouter(prefix="/taxonomy", tags=["taxonomy"])

ConceptType = Literal["skill", "trait"]

SUGGESTIONS_SQL = """
    SELECT concept_type, term, outcome, concept_slug, suggestions, evidence
    FROM term_suggestions
    ORDER BY outcome, concept_type, term
"""

VOCABULARY_SQL = {
    "skill": "SELECT EXISTS (SELECT 1 FROM skills WHERE slug = %s)",
    "trait": "SELECT EXISTS (SELECT 1 FROM traits WHERE slug = %s)",
}

LABEL_OWNER_SQL = """
    SELECT concepts.slug
    FROM concept_labels
    JOIN concepts ON concepts.concept_id = concept_labels.concept_id
    WHERE concept_labels.concept_type = %s AND concept_labels.compact_key = %s
"""

CONCEPT_EXISTS_SQL = "SELECT EXISTS (SELECT 1 FROM concepts WHERE concept_type = %s AND slug = %s)"

CURRENT_SQL = "SELECT outcome, concept_slug, suggestions FROM term_suggestions WHERE concept_type = %s AND term = %s"

RECORD_DECISION_SQL = """
    INSERT INTO term_suggestions (concept_type, term, outcome, concept_slug, suggestions, evidence, model_version, reviewed_at)
    VALUES (%s, %s, %s, %s, %s, %s, 'person', now())
    ON CONFLICT (concept_type, term) DO UPDATE SET
        outcome = EXCLUDED.outcome, concept_slug = EXCLUDED.concept_slug,
        evidence = EXCLUDED.evidence, reviewed_at = now()
"""


class SuggestedLink(BaseModel):
    concept_type: str
    term: str
    concept: str
    evidence: str


class ReviewItem(BaseModel):
    concept_type: str
    term: str
    suggestions: list[str]  # concept slugs, best first
    evidence: str


class Decision(BaseModel):
    concept_type: str
    term: str
    outcome: str            # "approved" or "rejected"
    concept: str | None     # for approved: the concept the word now means
    evidence: str


class Suggestions(BaseModel):
    model_linking: str        # "on", "off" or "unavailable"
    reason: str               # why, when it isn't on
    linked: list[SuggestedLink]   # the model's confident guesses: capped credit
    review: list[ReviewItem]      # waiting for a person
    approved: list[Decision]      # a person said yes: full synonym credit
    rejected: list[Decision]      # a person said no: never suggested again


class ApproveRequest(BaseModel):
    concept: str | None = None  # leave out to accept the model's own best concept


@router.get("/suggestions", response_model=Suggestions)
def list_suggestions() -> Suggestions:
    """Words the taxonomy didn't know, and what became of them (D-54, D-55): the model's capped guesses,
    the words waiting for review, and every decision a person made."""
    status, reason = model_linking_status()
    result = Suggestions(model_linking=status, reason=reason, linked=[], review=[], approved=[], rejected=[])
    with connect() as conn:
        for concept_type, term, outcome, concept, suggestions, evidence in conn.execute(SUGGESTIONS_SQL).fetchall():
            if outcome == "linked":
                result.linked.append(SuggestedLink(concept_type=concept_type, term=term, concept=concept, evidence=evidence))
            elif outcome == "review":
                result.review.append(ReviewItem(concept_type=concept_type, term=term, suggestions=suggestions, evidence=evidence))
            else:
                getattr(result, outcome).append(
                    Decision(concept_type=concept_type, term=term, outcome=outcome, concept=concept, evidence=evidence)
                )
    return result


@router.post("/suggestions/{concept_type}/{term}/approve", response_model=Decision)
def approve(concept_type: ConceptType, term: str, request: ApproveRequest | None = None) -> Decision:
    """A person confirms what a word means. From now on it earns full synonym credit, and every
    match using it is refreshed now (D-55)."""
    chosen = request.concept if request else None
    return _decide(concept_type, term, "approved", chosen)


@router.post("/suggestions/{concept_type}/{term}/reject", response_model=Decision)
def reject(concept_type: ConceptType, term: str) -> Decision:
    """A person says the model's guess is wrong. The word loses any suggested credit and is never
    suggested again; every match using it is refreshed now (D-55)."""
    return _decide(concept_type, term, "rejected", None)


def _decide(concept_type: str, raw_term: str, outcome: str, chosen: str | None) -> Decision:
    term = normalize(raw_term)
    with connect() as conn, conn.transaction():
        conn.execute(INGEST_LOCK_SQL)
        if not conn.execute(VOCABULARY_SQL[concept_type], (term,)).fetchone()[0]:
            raise HTTPException(status_code=404, detail=f"no candidate or job uses the {concept_type} {term!r}")
        owner = conn.execute(LABEL_OWNER_SQL, (concept_type, compact_key(term))).fetchone()
        if owner is not None:
            raise HTTPException(status_code=409, detail=f"{term!r} is already a taxonomy label of {owner[0]!r}")

        current = conn.execute(CURRENT_SQL, (concept_type, term)).fetchone()
        concept = None
        if outcome == "approved":
            # The person's choice, or else the model's confident guess, or else its first suggestion.
            concept = chosen or (current[1] if current and current[1] else None) or (current[2][0] if current and current[2] else None)
            if concept is None:
                raise HTTPException(status_code=422, detail="say which concept the word means: {\"concept\": \"<slug>\"}")
            concept = normalize(concept)
            if not conn.execute(CONCEPT_EXISTS_SQL, (concept_type, concept)).fetchone()[0]:
                raise HTTPException(status_code=422, detail=f"no {concept_type} concept {concept!r}")

        evidence = f"{outcome} by a person" + (f"; the model had said {current[0]}" if current else "")
        conn.execute(RECORD_DECISION_SQL, (concept_type, term, outcome, concept, current[2] if current else [], evidence))
        # Same transaction, so nobody sees the decision without the scores that follow from it (D-37).
        refresh_matches_for_terms(conn, {concept_type: [term]})
    return Decision(concept_type=concept_type, term=term, outcome=outcome, concept=concept, evidence=evidence)
