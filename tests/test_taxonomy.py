import copy
from datetime import date
from pathlib import Path

import psycopg
import pytest

from recruiter_bot.db import connect
from recruiter_bot.ingest import (
    ConceptHint,
    ConceptLabel,
    ConceptRelation,
    build_term_report,
    extract_candidates,
    extract_jobs,
    extract_taxonomy,
    read_json_records,
    read_taxonomy,
    save_taxonomy,
    suggest_concepts,
)

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"


def seed_taxonomy():
    return read_taxonomy(SEED_DIR / "taxonomy.json")


def concept(slug, concept_type="trait", preferred=None, **fields):
    return {"id": slug, "type": concept_type, "preferred_label": preferred or slug, **fields}


def taxonomy_file(concepts=None, relations=None):
    return {"concepts": concepts or [], "relations": relations or []}


VALID_FILE = taxonomy_file(
    concepts=[
        concept("stress-tolerance", preferred="calm-under-pressure"),
        concept("calmness", preferred="calm"),
        concept("persistence", preferred="persistent", alt_labels=["Tenacious"], hidden_labels=["persistant"]),
    ],
    relations=[{"type": "trait", "between": ["calmness", "stress-tolerance"], "relation": "related"}],
)


def with_change(change):
    data = copy.deepcopy(VALID_FILE)
    change(data)
    return data


# ---- Reading and validating the taxonomy file

def test_seed_taxonomy_is_valid():
    taxonomy = seed_taxonomy()
    assert len(taxonomy.concepts) == 51
    assert len(taxonomy.labels) == 54
    assert len(taxonomy.relations) == 22


def test_seed_labels_appear_in_seed_data():
    # Catches typos in the file: every visible label is a word the seed data uses.
    candidates = extract_candidates(read_json_records(SEED_DIR / "candidate_data.json"), date(2026, 1, 1)).records
    jobs = extract_jobs(read_json_records(SEED_DIR / "job_data.json")).records
    vocabulary = {
        "skill": {s for r in candidates for s in r.skill_slugs} | {s for r in jobs for s in r.skill_slugs},
        "trait": {t for r in candidates for t in r.trait_slugs} | {t for r in jobs for t in r.culture_trait_slugs},
    }
    for label in seed_taxonomy().labels:
        if label.label_type != "hidden":
            assert label.label in vocabulary[label.concept_type], label


def test_seed_references_are_only_the_verified_ones():
    references = {c.slug: c.onet_element_id for c in seed_taxonomy().concepts if c.onet_element_id or c.esco_uri}
    assert references == {"curiosity": "1.D.1.c", "innovation": "1.D.1.a"}


def test_labels_keep_their_type_and_are_normalized():
    labels = [label for label in extract_taxonomy(VALID_FILE).labels if label.concept_slug == "persistence"]
    assert labels == [
        ConceptLabel("persistence", "trait", "persistent", "preferred"),
        ConceptLabel("persistence", "trait", "tenacious", "alternative"),
        ConceptLabel("persistence", "trait", "persistant", "hidden"),
    ]


def test_relation_is_stored_in_both_directions_with_credit_from_its_type():
    assert extract_taxonomy(VALID_FILE).relations == [
        ConceptRelation("calmness", "stress-tolerance", "trait", "related", 0.5),
        ConceptRelation("stress-tolerance", "calmness", "trait", "related", 0.5),
    ]


def test_same_label_may_exist_in_both_types():
    data = taxonomy_file(concepts=[concept("loyalty", "skill"), concept("loyalty", "trait")])
    assert len(extract_taxonomy(data).labels) == 2


@pytest.mark.parametrize("change, expected_message", [
    (lambda d: d.pop("relations"), "expected an object with keys"),
    (lambda d: d["concepts"][0].pop("preferred_label"), "expected 'id', 'type', 'preferred_label'"),
    (lambda d: d["concepts"][0].update(weight=2), "expected 'id', 'type', 'preferred_label'"),
    (lambda d: d["concepts"][0].update(type="value"), "unknown type"),
    (lambda d: d["concepts"].append(concept("Calmness", preferred="serene")), "already defined"),
    (lambda d: d["concepts"][1].update(alt_labels=["calm-under pressure"]), "already belongs to stress-tolerance"),
    (lambda d: d["concepts"][2].update(alt_labels="tenacious"), "expected a list of strings"),
    (lambda d: d["concepts"][2].update(hidden_labels=["  "]), "no letters or digits"),
    (lambda d: d["concepts"][0].update(references={"lightcast": "x"}), "references"),
    (lambda d: d["concepts"][0].update(references={"esco_uri": " "}), "non-empty string or null"),
    (lambda d: d["relations"][0].update(relation="similar"), "unknown relation"),
    (lambda d: d["relations"][0].update(type="skill"), "no skill concept"),
    (lambda d: d["relations"][0].update(between=["calmness", "calmness"]), "related to itself"),
    (lambda d: d["relations"][0].update(between=["calmness", "zen"]), "no trait concept 'zen'"),
    (lambda d: d["relations"].append(
        {"type": "trait", "between": ["stress-tolerance", "calmness"], "relation": "unrelated"}),
     r"already related in relations\[0\]"),
])
def test_rejects_invalid_taxonomy(change, expected_message):
    with pytest.raises(ValueError, match=expected_message):
        extract_taxonomy(with_change(change))


# ---- Review hints (never credit)

def test_unknown_phrasing_is_hinted_for_each_matching_concept():
    labels = extract_taxonomy(VALID_FILE).labels
    assert suggest_concepts(["calm-under-stress", "decisive"], "trait", labels) == [
        ConceptHint("calm-under-stress", "trait", "calmness", ["calm"]),
        ConceptHint("calm-under-stress", "trait", "stress-tolerance", ["calm-under-pressure"]),
    ]


def test_hints_never_point_at_hidden_labels_or_the_other_type():
    labels = extract_taxonomy(VALID_FILE).labels
    assert suggest_concepts(["persistant-worker"], "trait", labels) == []
    assert suggest_concepts(["calm-under-stress"], "skill", labels) == []


def test_synonym_without_a_shared_first_word_is_missed():
    # The documented limit (D-31): hints only sort a review queue.
    assert suggest_concepts(["composed", "level-headed"], "trait", extract_taxonomy(VALID_FILE).labels) == []


@pytest.mark.parametrize("term", ["calm-not-under-pressure", "not-calm"])
def test_negation_blocks_hints(term):
    assert suggest_concepts([term], "trait", extract_taxonomy(VALID_FILE).labels) == []


# ---- Loading into the seeded database (rolled back, so the data is untouched)

@pytest.fixture
def conn():
    try:
        connection = connect()
    except psycopg.OperationalError:
        pytest.skip("Postgres is not running")
    with connection:
        with connection.transaction(force_rollback=True):
            yield connection


LABEL_SQL = """
    SELECT concepts.slug, concept_labels.label_type, concepts.onet_element_id
    FROM concept_labels
    JOIN concepts ON concepts.concept_id = concept_labels.concept_id
    WHERE concept_labels.concept_type = %s AND concept_labels.compact_key = replace(%s, '-', '')
"""


def test_loads_seed_taxonomy(conn):
    result = save_taxonomy(conn, seed_taxonomy())
    assert (result.concepts, result.labels, result.relations) == (51, 54, 22)
    assert conn.execute(LABEL_SQL, ("trait", "tenacious")).fetchone() == ("persistence", "alternative", None)
    assert conn.execute(LABEL_SQL, ("trait", "innovative")).fetchone() == ("innovation", "preferred", "1.D.1.a")
    # Matched by compact key, like profile terms (D-26).
    assert conn.execute(LABEL_SQL, ("trait", "calmunder-pressure")).fetchone()[0] == "stress-tolerance"


def test_reload_replaces_the_whole_taxonomy(conn):
    save_taxonomy(conn, seed_taxonomy())
    save_taxonomy(conn, extract_taxonomy(VALID_FILE))
    assert conn.execute("SELECT count(*) FROM concepts").fetchone()[0] == 3
    assert conn.execute("SELECT count(*) FROM concept_labels").fetchone()[0] == 5
    assert conn.execute("SELECT count(*) FROM concept_relations").fetchone()[0] == 2


def test_report_on_seed_data(conn):
    taxonomy = seed_taxonomy()
    save_taxonomy(conn, taxonomy)
    report = build_term_report(conn, taxonomy)

    assert report.unknown_skills == ["loyalty", "minimalism", "optimism", "precision", "resourcefulness"]
    assert report.unknown_traits == ["fast-paced"]
    assert report.hints == []
    # energetic is covered by Michael's enthusiastic, calm-under-pressure by the related calm and resilient.
    assert [slug for slug, side in report.unmatched_traits if side == "job"] == ["autonomous", "curious", "fast-paced"]
    # An unrelated relation gives no credit: chaotic still covers nothing.
    assert ("chaotic", "candidate") in report.unmatched_traits
    assert ("persuasion", "candidate") not in report.unmatched_skills


def test_hidden_label_makes_a_misspelling_known(conn):
    conn.execute("INSERT INTO traits (slug) VALUES ('persistant')")
    taxonomy = seed_taxonomy()
    save_taxonomy(conn, taxonomy)
    assert "persistant" not in build_term_report(conn, taxonomy).unknown_traits


def test_report_hints_a_new_phrasing(conn):
    conn.execute("INSERT INTO traits (slug) VALUES ('calm-under-stress')")
    taxonomy = seed_taxonomy()
    save_taxonomy(conn, taxonomy)
    report = build_term_report(conn, taxonomy)
    assert "calm-under-stress" in report.unknown_traits
    assert report.hints == [
        ConceptHint("calm-under-stress", "trait", "calmness", ["calm"]),
        ConceptHint("calm-under-stress", "trait", "stress-tolerance", ["calm-under-pressure"]),
    ]
