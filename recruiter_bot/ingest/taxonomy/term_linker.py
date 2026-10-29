from dataclasses import dataclass, field

import psycopg

from recruiter_bot.ingest.text_normalizer import compact_key, root_key

# Stage 1: a word containing one of these is negated and never linked.
NEGATING_WORDS = {"not", "no", "non", "never", "without", "lack", "lacks", "lacking",
                  "poor", "weak", "bad", "terrible", "unable"}
# A word starting with one of these is negated only if the rest is a known label.
NEGATING_PREFIXES = ("non", "dis", "un", "in", "im", "ir", "il")


@dataclass(frozen=True)
class Link:
    term: str
    concept_type: str
    concept: str   # concept slug
    method: str    # "root_key", "typo", "group", or "model" for a suggested link
    evidence: str  # the label it matched, or the words grouped together


@dataclass(frozen=True)
class LinkResult:
    links: list[Link]
    negated: list[tuple[str, str]]          # (term, what it negates)
    ambiguous: list[tuple[str, list[str]]]  # (term, the concepts it could mean)
    # The optional model stage, for words the rules left unplaced:
    suggested: list[Link] = field(default_factory=list)                 # capped "suggested" credit
    review: list[tuple[str, str, list[str]]] = field(default_factory=list)  # (type, term, suggestions)
    model_status: str = "off"                                           # "on", "off" or "unavailable"
    model_reason: str = ""
    model_failed: list[tuple[str, str]] = field(default_factory=list)   # (term, error): left unknown


HAS_LABEL_SQL = """
    SELECT EXISTS (SELECT 1 FROM concept_labels WHERE concept_type = %s AND compact_key = %s)
"""

HAS_CURATED_LABEL_SQL = """
    SELECT EXISTS (
        SELECT 1 FROM concept_labels
        WHERE concept_type = %s AND compact_key = %s AND source = 'curated' AND label_type <> 'hidden'
    )
"""

# Only reviewed labels can attract a word, so automatic links never chain.
CONCEPTS_WITH_ROOT_SQL = """
    SELECT DISTINCT ON (concepts.concept_id) concepts.concept_id, concepts.slug, concept_labels.label
    FROM concept_labels
    JOIN concepts ON concepts.concept_id = concept_labels.concept_id
    WHERE concept_labels.concept_type = %s
      AND concept_labels.root_key = %s
      AND concept_labels.label_type <> 'hidden'
      AND (concept_labels.source = 'curated' OR concept_labels.label_type = 'preferred')
    ORDER BY concepts.concept_id, concept_labels.label
"""

# The one scan: labels of one type, narrowed by key length.
TYPO_CANDIDATES_SQL = """
    SELECT concepts.concept_id, concepts.slug, concept_labels.label, concept_labels.root_key
    FROM concept_labels
    JOIN concepts ON concepts.concept_id = concept_labels.concept_id
    WHERE concept_labels.concept_type = %s
      AND concept_labels.label_type <> 'hidden'
      AND (concept_labels.source = 'curated' OR concept_labels.label_type = 'preferred')
      AND length(concept_labels.root_key) BETWEEN %s AND %s
"""

SAME_ROOT_VOCABULARY_SQL = {
    "skill": "SELECT slug FROM skills WHERE root_key = %s ORDER BY slug",
    "trait": "SELECT slug FROM traits WHERE root_key = %s ORDER BY slug",
}

INSERT_AUTO_CONCEPT_SQL = """
    INSERT INTO concepts (concept_type, slug, description, source)
    VALUES (%s, %s, %s, 'auto')
    ON CONFLICT (concept_type, slug) DO UPDATE SET slug = EXCLUDED.slug
    RETURNING concept_id
"""

INSERT_AUTO_LABEL_SQL = """
    INSERT INTO concept_labels (concept_id, concept_type, label, label_type, root_key, source, method, evidence)
    VALUES (%s, %s, %s, %s, %s, 'auto', %s, %s)
    ON CONFLICT DO NOTHING
"""

MISSING_ROOT_KEYS_SQL = {
    "skill": "SELECT slug FROM skills WHERE root_key IS NULL",
    "trait": "SELECT slug FROM traits WHERE root_key IS NULL",
}

SET_ROOT_KEY_SQL = {
    "skill": "UPDATE skills SET root_key = %s WHERE slug = %s",
    "trait": "UPDATE traits SET root_key = %s WHERE slug = %s",
}

ALL_VOCABULARY_SQL = {
    "skill": "SELECT slug FROM skills ORDER BY slug",
    "trait": "SELECT slug FROM traits ORDER BY slug",
}


def link_terms(conn: psycopg.Connection, concept_type: str, terms: list[str]) -> LinkResult:
    """Links unlabelled terms by the rules, then by the optional model stage."""
    links = []
    negated = []
    ambiguous = []
    unplaced = []
    for term in sorted(set(terms)):
        if _has_label(conn, HAS_LABEL_SQL, concept_type, term):
            continue  # already known, possibly linked earlier in this loop by grouping

        negates = _negates(conn, concept_type, term)
        if negates is not None:
            negated.append((term, negates))
            continue

        key = root_key(term)
        concepts = conn.execute(CONCEPTS_WITH_ROOT_SQL, (concept_type, key)).fetchall()
        if len(concepts) > 1:
            ambiguous.append((term, [slug for _, slug, _ in concepts]))
            continue
        if len(concepts) == 1:
            concept_id, concept_slug, label = concepts[0]
            links.append(_add_label(conn, concept_id, concept_slug, concept_type, term, "alternative", "root_key", label))
            continue

        typo = _typo_match(conn, concept_type, key)
        if typo is not None:
            concept_id, concept_slug, label = typo
            # ESCO keeps misspellings as hidden labels: matchable, never shown.
            links.append(_add_label(conn, concept_id, concept_slug, concept_type, term, "hidden", "typo", label))
            continue

        grouped = _group_unknown_words(conn, concept_type, key)
        links.extend(grouped)
        if not grouped:
            unplaced.append(term)

    return _with_model_stage(conn, concept_type, LinkResult(links, negated, ambiguous), unplaced)


def _with_model_stage(conn: psycopg.Connection, concept_type: str, result: LinkResult, unplaced: list[str]) -> LinkResult:
    """Adds what the model stage concluded. It never raises, so the rules' result always stands."""
    # Imported here: the model stage is optional, and its heavy libraries load only when it runs.
    from recruiter_bot.linking.model_stage import suggest_for_unknown_terms

    stage = suggest_for_unknown_terms(conn, concept_type, unplaced)
    suggested = [Link(s.term, s.concept_type, s.concept, "model", s.evidence) for s in stage.suggestions if s.outcome == "linked"]
    review = [(s.concept_type, s.term, s.suggestions) for s in stage.suggestions if s.outcome == "review"]
    return LinkResult(result.links, result.negated, result.ambiguous, suggested, review,
                      stage.status, stage.reason, stage.failed)


def link_record_terms(conn: psycopg.Connection, skills: list[str] | None, traits: list[str] | None) -> list[Link]:
    """Links one record's new words, then refreshes the other records that use them."""
    links = []
    for concept_type, terms in (("skill", skills), ("trait", traits)):
        if terms:
            result = link_terms(conn, concept_type, terms)
            # A suggested link changes credit too, so the records using it are refreshed like any other link.
            links.extend(result.links + result.suggested)
    if links:
        # Imported here: matching depends on ingest, so ingest only reaches into it when it must.
        from recruiter_bot.matching.match_store import refresh_matches_for_terms
        refresh_matches_for_terms(conn, {
            "skill": [link.term for link in links if link.concept_type == "skill"],
            "trait": [link.term for link in links if link.concept_type == "trait"],
        })
    return links


def link_all_terms(conn: psycopg.Connection) -> LinkResult:
    """After a taxonomy load: fills missing root keys, then links the whole vocabulary."""
    # The taxonomy may have changed, so every model decision is made again.
    from recruiter_bot.linking.model_stage import clear_suggestions
    clear_suggestions(conn)

    links = []
    negated = []
    ambiguous = []
    suggested = []
    review = []
    failed = []
    status, reason = "off", ""
    for concept_type in ("skill", "trait"):
        missing = [slug for (slug,) in conn.execute(MISSING_ROOT_KEYS_SQL[concept_type]).fetchall()]
        if missing:
            with conn.cursor() as cursor:
                cursor.executemany(SET_ROOT_KEY_SQL[concept_type], [(root_key(slug), slug) for slug in missing])
        terms = [slug for (slug,) in conn.execute(ALL_VOCABULARY_SQL[concept_type]).fetchall()]
        result = link_terms(conn, concept_type, terms)
        links.extend(result.links)
        negated.extend(result.negated)
        ambiguous.extend(result.ambiguous)
        suggested.extend(result.suggested)
        review.extend(result.review)
        failed.extend(result.model_failed)
        status, reason = result.model_status, result.model_reason
    return LinkResult(links, negated, ambiguous, suggested, review, status, reason, failed)


def _has_label(conn: psycopg.Connection, sql: str, concept_type: str, term: str) -> bool:
    return conn.execute(sql, (concept_type, compact_key(term))).fetchone()[0]


def _negates(conn: psycopg.Connection, concept_type: str, term: str) -> str | None:
    """What the term negates, or None. 'not-a-team-player' -> 'not'; 'disorganized' -> 'organized'."""
    for word in term.split("-"):
        if word in NEGATING_WORDS:
            return word
    for prefix in NEGATING_PREFIXES:
        rest = term[len(prefix):].lstrip("-")
        # Only when the rest is a real label: 'discovery' isn't 'dis' + 'covery'.
        if term.startswith(prefix) and len(rest) >= 3 and _has_label(conn, HAS_CURATED_LABEL_SQL, concept_type, rest):
            return rest
    return None


def _typo_match(conn: psycopg.Connection, concept_type: str, key: str) -> tuple[int, str, str] | None:
    """The one concept a typo away, in exactly one word, or None."""
    words = key.split("-")
    best_distance = 3
    best = {}
    rows = conn.execute(TYPO_CANDIDATES_SQL, (concept_type, len(key) - 2, len(key) + 2)).fetchall()
    for concept_id, concept_slug, label, label_key in rows:
        distance = _one_word_typo(words, label_key.split("-"))
        if distance is None:
            continue
        if distance < best_distance:
            best_distance = distance
            best = {concept_id: (concept_id, concept_slug, label)}
        elif distance == best_distance:
            best.setdefault(concept_id, (concept_id, concept_slug, label))
    if len(best) == 1:
        return next(iter(best.values()))
    return None  # nothing close enough, or a tie between concepts


def _one_word_typo(words: list[str], label_words: list[str]) -> int | None:
    """The edit distance when the two keys differ in exactly one word, within that word's limit."""
    if len(words) != len(label_words):
        return None
    only_here = [word for word in words if word not in label_words]
    only_there = [word for word in label_words if word not in words]
    if len(only_here) != 1 or len(only_there) != 1:
        return None
    typed, intended = only_here[0], only_there[0]
    if len(intended) < 5:
        return None  # sale, java, sql: too short to correct safely
    if typed[0] != intended[0]:
        return None  # typos rarely change the first letter; apathetic is not a typo of empathetic
    limit = 1 if len(intended) < 8 else 2
    distance = _edit_distance(typed, intended)
    return distance if distance <= limit else None


def _group_unknown_words(conn: psycopg.Connection, concept_type: str, key: str) -> list[Link]:
    """Unknown words sharing a root key become one provisional concept; a lone word stays unknown."""
    words = [slug for (slug,) in conn.execute(SAME_ROOT_VOCABULARY_SQL[concept_type], (key,)).fetchall()]
    words = [word for word in words if not _has_label(conn, HAS_LABEL_SQL, concept_type, word)]
    if len(words) < 2:
        return []

    concept_slug = f"auto-{words[0]}"
    concept_id = conn.execute(INSERT_AUTO_CONCEPT_SQL, (
        concept_type, concept_slug, f"Grouped automatically: {', '.join(words)} share the same word roots.",
    )).fetchone()[0]
    evidence = ", ".join(words)
    links = [_add_label(conn, concept_id, concept_slug, concept_type, words[0], "preferred", "group", evidence)]
    for word in words[1:]:
        links.append(_add_label(conn, concept_id, concept_slug, concept_type, word, "alternative", "group", evidence))
    return links


def _add_label(
    conn: psycopg.Connection, concept_id: int, concept_slug: str, concept_type: str,
    term: str, label_type: str, method: str, evidence: str,
) -> Link:
    conn.execute(INSERT_AUTO_LABEL_SQL, (concept_id, concept_type, term, label_type, root_key(term), method, evidence))
    return Link(term, concept_type, concept_slug, method, evidence)


def _edit_distance(first: str, second: str) -> int:
    """Damerau-Levenshtein (optimal string alignment): a swap of two letters counts as one edit."""
    previous_row = None
    row = list(range(len(second) + 1))
    for i in range(1, len(first) + 1):
        before_previous, previous_row = previous_row, row
        row = [i] + [0] * len(second)
        for j in range(1, len(second) + 1):
            cost = 0 if first[i - 1] == second[j - 1] else 1
            row[j] = min(previous_row[j] + 1, row[j - 1] + 1, previous_row[j - 1] + cost)
            if i > 1 and j > 1 and first[i - 1] == second[j - 2] and first[i - 2] == second[j - 1]:
                row[j] = min(row[j], before_previous[j - 2] + 1)
    return row[len(second)]
