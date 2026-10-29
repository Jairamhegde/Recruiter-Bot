"""The optional model stage for unknown words; any failure falls back to the rules alone."""
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import psycopg

log = logging.getLogger(__name__)

TAXONOMY_PATH = Path(__file__).resolve().parent.parent.parent / "seed" / "taxonomy.json"

# Stored with every row, so a later model or threshold change can tell which rows it made.
MODEL_VERSION = "bge-small-en-v1.5 + nli-deberta-v3-xsmall, calibrated thresholds"

HAS_SUGGESTION_SQL = "SELECT EXISTS (SELECT 1 FROM term_suggestions WHERE concept_type = %s AND term = %s)"

# Only the model's own conclusions: a person's approved or rejected decision is kept.
CLEAR_SUGGESTIONS_SQL = "DELETE FROM term_suggestions WHERE outcome IN ('linked', 'review')"

INSERT_SUGGESTION_SQL = """
    INSERT INTO term_suggestions (concept_type, term, outcome, concept_slug, suggestions, evidence, model_version)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (concept_type, term) DO UPDATE SET
        outcome = EXCLUDED.outcome, concept_slug = EXCLUDED.concept_slug, suggestions = EXCLUDED.suggestions,
        evidence = EXCLUDED.evidence, model_version = EXCLUDED.model_version, created_at = now()
"""


@dataclass(frozen=True)
class Suggestion:
    concept_type: str
    term: str
    outcome: str             # "linked" or "review"
    concept: str | None      # for linked
    suggestions: list[str]   # for review, best first
    evidence: str


@dataclass(frozen=True)
class ModelStageResult:
    status: str                     # "on", "off" or "unavailable"
    reason: str                     # why, when it isn't on
    suggestions: list[Suggestion]
    failed: list[tuple[str, str]]   # (term, what went wrong); those words simply stay unknown


class _Pipeline:
    """The loaded models with the taxonomy's concepts already embedded."""

    def __init__(self) -> None:
        # Imported here: these need numpy and onnxruntime, which the rules-only install doesn't have.
        from recruiter_bot.ingest import read_taxonomy
        from recruiter_bot.linking.concept_search import build_concept_index
        from recruiter_bot.linking.models import load_models
        from recruiter_bot.linking.verification import CandidateVerifier, labels_by_concept_from_taxonomy

        models = load_models()
        if models is None:
            raise FileNotFoundError("model files are not downloaded (python -m recruiter_bot.linking.model_files)")
        # The curated taxonomy file, never the automatic labels, so one guess can't build on another.
        taxonomy = read_taxonomy(TAXONOMY_PATH)
        self._index = build_concept_index(models.embedding, taxonomy)
        self._verifier = CandidateVerifier(models.nli, labels_by_concept_from_taxonomy(taxonomy))

    def decide(self, concept_type: str, term: str) -> Suggestion | None:
        from recruiter_bot.linking.decision import decide

        candidates = self._index.closest(concept_type, term)
        decision = decide(self._verifier.verify(concept_type, term, candidates), automatic_linking=True)
        if decision.outcome == "auto_link":
            return Suggestion(concept_type, term, "linked", decision.concept, [], decision.explain())
        if decision.outcome == "review":
            return Suggestion(concept_type, term, "review", None, decision.suggestions, decision.explain())
        return None


_pipeline: _Pipeline | None = None
_unavailable_reason: str | None = None


def _get_pipeline() -> tuple[_Pipeline | None, str]:
    """Loads the models once per process. A failure is remembered, so it isn't retried on every request."""
    global _pipeline, _unavailable_reason
    if _pipeline is not None:
        return _pipeline, ""
    if _unavailable_reason is not None:
        return None, _unavailable_reason
    try:
        _pipeline = _Pipeline()
        return _pipeline, ""
    except ImportError as error:
        _unavailable_reason = f"model libraries are not installed ({error.name}); pip install -r requirements-linking.txt"
    except Exception as error:  # a corrupt file, an onnxruntime error: any of them means "rules only"
        _unavailable_reason = f"models failed to load: {error}"
    log.warning("model linking unavailable, using the rules only: %s", _unavailable_reason)
    return None, _unavailable_reason


def model_linking_status() -> tuple[str, str]:
    """('on', ''), ('off', reason) or ('unavailable', reason), for the API and the seed output."""
    if os.environ.get("MODEL_LINKING", "auto").strip().lower() == "off":
        return "off", "MODEL_LINKING=off"
    pipeline, reason = _get_pipeline()
    return ("on", "") if pipeline is not None else ("unavailable", reason)


def clear_suggestions(conn: psycopg.Connection) -> None:
    """Forgets every decision, after a taxonomy load. In a savepoint, so a failure can't stop the seed."""
    try:
        with conn.transaction():
            conn.execute(CLEAR_SUGGESTIONS_SQL)
    except psycopg.Error as error:
        log.warning("could not clear old model suggestions: %s", error)


def suggest_for_unknown_terms(conn: psycopg.Connection, concept_type: str, terms: list[str]) -> ModelStageResult:
    """Runs the model stage on words the rules couldn't place. Never raises: the caller's write always goes on."""
    status, reason = model_linking_status()
    if status != "on" or not terms:
        return ModelStageResult(status, reason, [], [])
    pipeline, _ = _get_pipeline()

    suggestions = []
    failed = []
    for term in sorted(set(terms)):
        # Each database step has its own savepoint, so a failure never aborts the caller's transaction.
        try:
            with conn.transaction():
                decided_before = conn.execute(HAS_SUGGESTION_SQL, (concept_type, term)).fetchone()[0]
        except psycopg.Error as error:
            failed.append((term, f"could not read earlier suggestions: {error}"))
            continue
        if decided_before:
            continue  # deterministic models give the same answer, and a person's decision always stands

        try:
            suggestion = pipeline.decide(concept_type, term)
        except Exception as error:
            failed.append((term, str(error)))
            log.warning("model linking skipped %s %r: %s", concept_type, term, error)
            continue
        if suggestion is None:
            continue
        try:
            with conn.transaction():  # a savepoint: a failed write undoes only this word
                conn.execute(INSERT_SUGGESTION_SQL, (
                    concept_type, term, suggestion.outcome, suggestion.concept, suggestion.suggestions,
                    suggestion.evidence, MODEL_VERSION,
                ))
            suggestions.append(suggestion)
        except psycopg.Error as error:
            failed.append((term, f"could not store the suggestion: {error}"))
            log.warning("model linking could not store %s %r: %s", concept_type, term, error)
    return ModelStageResult(status, reason, suggestions, failed)
