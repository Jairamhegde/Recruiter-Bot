# DECISION.md — Recruiter Bot

The assumptions and design decisions behind this project, each with the reason for it.

_Last updated: 2026-10-28_

---

## Handling ambiguity

The brief leaves some requirements open on purpose. Where it does, we pick a reasonable default, write it down here, and keep it configurable, so a changed requirement means a config change rather than a rewrite.

---

## 1. Data

**D-01. Broken skill names in the source are PDF formatting artifacts.**
`pattern-recog nition` and `public-speaki ng` are layout artifacts, not real skill names, so they are corrected by hand in the seed data. Normalization (D-02) is still applied to all input, but it only fixes case and spacing between whole words. It can't rejoin a word broken mid-word (`pattern-recog nition` becomes `pattern-recog-nition`). Broken words sent through the API are therefore treated as unknown skills.

**D-02. Skills, traits and culture keywords are normalized.**
They are lowercased and trimmed, and spaces or repeated hyphens become a single hyphen. Reason: `stakeholder management` (Leslie, Miranda) has to match the job's `stakeholder-management`.

**D-03. No alias table; synonyms are decided in matching, not ingestion.**
Ingestion only cleans terms. Whether `calm` counts as `calm-under-pressure` is a matching rule, so changing it never needs a re-ingest.
_Amended by D-30:_ synonyms and related terms now live in a curated, ESCO-shaped taxonomy. It is stored apart from candidates and jobs, so editing it only reloads the taxonomy.

**D-04. Records get integer ids plus a unique slug.**
The source data has no ids. The slug (`sherlock-h`) lets repeated ingestion update existing rows instead of creating duplicates.

**D-05. Availability is stored as two fields.**
`open_to_opportunities` and `available_from DATE`. `Immediate` becomes (open, today), `2 weeks` becomes (open, today + 14), and `Not looking` becomes (not open, NULL). A CHECK constraint keeps the two consistent. Reason: the source mixes willingness to move with timing, and a date stays correct over time where "14 days from now" doesn't. "Today" comes from the database clock, so the result doesn't depend on the timezone of whoever runs the seed.

**D-06. Quirks and taglines are display-only.**
They are free text, so they are returned in responses but never scored.

**D-07. Experience means total career years.**
The source doesn't give years per skill.

---

## 2. Requirements

**D-08. Every skill a job lists is required, with no nice-to-have tier.**
Required means the skill counts toward the coverage score, not that a candidate must have all of them. Reason: no candidate has all three skills for Engineering Manager, Chaos Team, so treating "required" as all-or-nothing would leave that job with no matches.

**D-09. Candidate preferences are not modeled.**
The source has no preference data, so `GET /candidates/{id}/matches` ranks jobs by how well the candidate fits each one. No placeholder column is added; one can be added later when real data exists.

**D-10. Candidates who aren't looking are kept and flagged for a proactive offer.**
Their score is lowered through availability, and each of their matches carries `outreach: { status: "passive", recommended_action: "proactive-offer" }`. Reason: the brief's own example, Michael Scott, is not looking. Passing `?include_passive=false` excludes them.

---

## 3. Matching algorithm

**D-11. Each factor is scored separately, then combined with weights.**

| Factor | Formula (0 to 1) | Weight |
|---|---|---|
| Skills (S) | matched ÷ required | 0.60 |
| Experience (E) | 1 if years ≥ minimum, otherwise years ÷ minimum | 0.20 |
| Availability (A) | Immediate 1.0, 2 weeks 0.8, Not looking 0.3 | 0.10 |
| Culture (C) | matched keywords ÷ job keywords | 0.10 |

`score = round(100 × (0.6·S + 0.2·E + 0.1·A + 0.1·C), 1)`

Reason: the brief makes skills and experience mandatory. Availability and culture only break near-ties. Each part can be tested on its own, and all weights live in config.

**D-12. No skill overlap means no match.**
Reason: without this rule, a candidate with no relevant skills could still score up to 40 from experience and availability alone.

**D-13. Exceeding the minimum experience isn't penalized.**
Experience fit is capped at 1.0. Treating over-qualification as a negative is a possible later change.

**D-14. Skills are matched by exact standard name, with no skill taxonomy.**
Every skill a job requires appears exactly in at least one candidate's profile, so broad skills like `leadership` are matched directly. A related-skills table that gives partial credit is a possible later addition.
_Superseded by D-29 and D-30:_ partial credit now comes from the taxonomy. Scoring still uses exact names until it reads the taxonomy.

**D-15. Both directions use the same score for a candidate–job pair.**
The two match endpoints sort the same score in opposite directions, so they can never disagree.

**D-16. Ties are broken in a fixed order.**
`score`, then skills, then availability, then name (alphabetical). Scores are rounded before ranking so floating-point noise can't change the order. The last step uses name, not `id`, so the order doesn't depend on which record was inserted first.

**D-17. A minimum score of 50 decides what counts as a match.**
It's configurable, including per request with `?min_score=`. When no result reaches it, the response returns an empty list plus up to 3 near misses, each showing its missing skills. Reason: 50 means the candidate has at least about a third of the required skills and is otherwise strong. On a 3-skill job, one matching skill with everything else ideal scores exactly 50. On a 2-skill job, one matching skill scores 60. An unexplained empty list gives the recruiter nothing to act on.

**D-18. Every match includes a score breakdown and a reason built from it.**
Example reason: `3/3 skills · 8y vs 3y min · available now · culture: analytical`. Building the reason from the breakdown means it can never contradict the score.

### Expected rankings (regression tests)

These are hand-calculated from the formula above. The tests confirm the code implements the formula; they do not prove the formula ranks people the way a recruiter would.

| Job | Expected ranking |
|---|---|
| Backend Detective | Sherlock 95, Sheldon 50 |
| Rapid Prototyping Engineer | Rick 90, MacGyver 88, Tony 88 |
| Developer Relations Lead | Elle 90, Hermione 88 |
| Engineering Manager, Chaos Team | Miranda 63, Leslie 55, Ted 55 |
| Incident Commander | Olivia 93, Katniss 75, Dwight 50 |
| Sales Engineer | Dwight 70, Michael 68 |
| Ron S. (reverse direction) | No matches; near misses at 43 |

---

## 4. Architecture

**D-19. Raw SQL only.**
The schema is created by hand-written, numbered DDL migration files, applied by a small runner of our own. All queries are hand-written and parameterized.

**D-20. Skills are stored in normalized tables.**
`skills`, `candidate_skills` and `job_skills`, so skill overlap is computed in SQL with joins.

**D-21. Matches are stored in a `matches` table.**
Each row holds the score, breakdown, reason and algorithm version, and the table is recomputed on every ingest. Every pair with at least one shared skill is stored, including those below the threshold. The minimum score is applied only when reading, so `?min_score=` and near misses keep working. Reason: reads stay simple and every score can be audited. With only 90 candidate–job pairs, recomputing all of them costs almost nothing.

**D-22. Ingestion: seed data loads on startup (`python -m recruiter_bot.seed` for now), and two POST endpoints will use the same code.**
The brief asks for "a way to load" the data. Loading the seed files on startup covers that. `POST /candidates` and `POST /jobs` are a small extension that runs the same validation and insert code. A bulk `POST /ingest` was dropped, because startup seeding already does that job. Every write is an upsert, so repeated loads never create duplicates.

**D-23. The database is PostgreSQL, run with Docker Compose from the first commit.**
The brief allows any relational database. Postgres adds real foreign keys, `CHECK` constraints and `JSONB`. Docker Compose isn't required by the brief; it's added so reviewers can start everything with `docker compose up`. The setup includes a Postgres healthcheck the app waits for, no Postgres port exposed to the host, and README instructions for running without Docker. The driver is psycopg 3: it only executes the SQL we write and generates none.

For local development, Postgres is exposed on `127.0.0.1:5433`, which is bound to this machine only and avoids clashing with a local Postgres on 5432.

**D-24. Python 3.11+, psycopg 3 and pydantic.**
The brief says to use the language we're strongest in. psycopg 3 only sends the SQL we write. pydantic only validates input; it never builds SQL.

**D-25. Ingestion runs in three steps: extract, build the batch, write it in one transaction.**
1. `read_json_records` reads the file. `extract_candidates` and `extract_jobs` validate every record. A record missing a required field (candidate: name, skills, experience, availability; job: title, required skills, minimum experience), or with an invalid value, is **rejected with a reason and logged**. Valid records are kept, as in a typical bulk import, so one bad row doesn't block the rest. Unknown extra fields are ignored rather than rejected.
2. `build_candidate_batch` and `build_job_batch` turn the valid records into column lists that map directly onto the INSERT statements.
3. `insert_batch` writes the batch in one transaction, so the valid set is either fully applied or not at all. Inserts are set-based (`unnest` of arrays, one statement per table), not a loop of single-row inserts. Re-running is safe: upserts on slug only change rows whose data differs, and each record's skill and trait links are replaced as a whole. An advisory lock stops two concurrent loads from interleaving. Rejected input is logged to `ingestion_events` in its own transaction, independent of the batch.

**D-26. Skill and trait lookup is deterministic, by compact key.**
The compact key is the slug without hyphens, generated by the database. It catches words broken mid-word (`pattern-recog nition`). Symbols are rewritten before stripping (`c++` becomes `cplusplus`), so `C++`, `C#` and `C` stay distinct. Two other approaches were considered and rejected. A trie: lookups are exact matches against about 30 values, which a B-tree index already handles, and prefix matching would hand out skills candidates never listed. Automatic fuzzy matching with pg_trgm: on our own data it scores `crisis-management` against `project-management` at 0.42, above its default threshold of 0.3.

**D-27. Term similarity lives in one matching function: exact match in v1.**
`term_similarity(candidate_term, job_term)` returns 0 to 1. v1 returns 1 for identical normalized terms; related-skill credit and embeddings can replace it later without changing the scoring.
_Superseded by D-32:_ the hook is now a credit source passed into the scorer.

**D-28. Matching engine v1: score = 80% skills + 20% experience, computed on read.**
The two factors the brief requires; culture, availability and thresholds are added later. Pairs with no shared skill are excluded (D-12); ties break on score, then skills, then name (D-16 without availability). Results are not stored in `matches` yet.
_Superseded by D-32_ for the formula; the rest still holds.

**D-29. Skills, traits and culture keywords are matched through an ESCO-shaped taxonomy, not embeddings.**
Embeddings score words as similar when they appear in similar contexts, even when they mean opposite things. `chaotic` (Michael S.) and `organized` (Engineering Manager, Chaos Team) both describe how someone works, so an embedding would likely give partial credit for an opposite.

The taxonomy follows ESCO's data model, filled with our own data. ESCO stores each skill as a concept with an identifier, a description, one preferred label, any number of alternative labels (synonyms) and hidden labels (search-only variants such as misspellings). We keep the same shape, for skills and traits alike:

| Concept | Type | Preferred label | Alternative labels | Hidden labels |
|---|---|---|---|---|
| `persistence` | trait | `persistent` | `tenacious` | `persistant` |
| `stress-tolerance` | trait | `calm-under-pressure` | | |
| `sales` | skill | `sales` | | |

- **Same concept, any label:** 1.0, since ESCO's alternative labels are synonyms.
- **`related` concepts:** 0.5, for example `calmness` and `stress-tolerance`, or `persuasion` and `sales`. This is our extension: ESCO classifies skills and doesn't score matches.
- **`unrelated` concepts:** 0, recording a reviewed "no" such as `chaotic` / `organized` or `project-management` / `crisis-management`.
- **Anything else:** 0. A term outside the taxonomy only matches the identical term.
- **References:** each concept has an empty slot for an ESCO URI and an O\*NET Work Style ID, filled only when verified. Two are filled today, from the O\*NET 30.2 Work Styles file: `innovation` = `1.D.1.a` (Innovation) and `curiosity` = `1.D.1.c` (Intellectual Curiosity). No identifier is invented. We copy no ESCO or O\*NET data. Importing it later needs attribution: O\*NET is CC BY 4.0 and must be credited with its version, and ESCO's reuse terms must be checked first.
- **Why not real ESCO now:** the brief supplies the data, and ESCO covers skills far better than personality words like `blunt` or `chaotic`. The shape means ESCO concepts can be loaded into the same tables later.

The taxonomy only covers fixed words; it can't read free text. Quirks and taglines therefore stay display-only (D-06). Embeddings fail the same way there: Hermione's quirk ("reads the entire documentation") and the Rapid Prototyping tagline ("document never") share a topic but describe opposite fits. These are known embedding weaknesses illustrated with our data; no similarity scores were measured, since the project doesn't install an embedding model.

**D-30. The taxonomy is loaded at ingestion from `seed/taxonomy.json`.**
- **Storage:** `concepts`, `concept_labels` and `concept_relations`. A label belongs to one concept per type, matched by compact key (D-26), so `Persistent`, `persistent` and `per-sistent` find the same concept. Relations are stored in both directions and only connect concepts of the same type.
- **Independent of the data:** labels are stored as text, not tied to profile rows, because a taxonomy also describes words nobody has used yet. Hidden labels are mostly words nobody should use. A test checks that every preferred and alternative label in the seed taxonomy appears in the seed data, which catches typos in the file.
- **No hand-tuned numbers:** credit comes from the relation type.
- **Loading:** the file replaces the whole taxonomy in one transaction, under the ingest lock. It never touches candidate or job rows.
- **Validation:** a bad entry fails the whole load, and the file is checked before anything is written. Bad entries include an unknown type or relation, a duplicate concept, a label used twice within a type, a relation to a missing concept or to itself, and the same pair listed twice. The file is our own configuration, so silently skipping a typo would quietly change scores.
- **Misfiled traits:** `loyalty`, `optimism`, `precision`, `minimalism` and `resourcefulness` appear as skills in the source data but describe personality, so the taxonomy has no skill concepts for them. They show up as unknown skills in the report until the source is corrected.
- **Not used for scoring yet:** matching still uses exact names (D-27) until the next step reads the taxonomy.

**D-31. Unknown words get no credit for the MVP; automatic linking with embeddings comes after.**
A term with no label in the taxonomy is unknown. For the MVP:
- **No credit and no penalty:** it only matches the identical term.
- **Reported on every seed run:** the unknown terms, and the gaps: job terms no candidate covers, and candidate terms no job asks for.
- **Hints, never credit:** an unknown term that shares its first word with a label gets a hint, for example `calm-under-stress may be a label of stress-tolerance (like calm-under-pressure)`. Approving it means adding the label to `seed/taxonomy.json`.
- **Hint guards:** only the first word counts, since the last word would pair `project-management` with `crisis-management` (D-26). No hint when only one term contains a negation word (`not`, `non`, `no`, `un`, `anti`, `never`, `without`), or when the shared first word is itself a negation. The rule misses synonyms without a shared word (`composed`, `level-headed`) and pairs unrelated words as a vocabulary grows (`data-entry` / `data-science`), so it only sorts a review queue.

After the MVP, unknown words are linked automatically with embeddings, but only when three checks agree:
1. **A high similarity score** to one concept's labels.
2. **A clear winner:** the best concept beats the second-best by a margin.
3. **Not an opposite:** a confirming model (natural language inference) or an antonym list checks that the word supports the concept rather than contradicting it, which is the weakness D-29 describes.

When all three pass, the word is added as an alternative label marked `auto` and logged, so it can be seen and undone; otherwise it goes to review. Embeddings never create concepts or relations. The thresholds have to be set from 50–100 word pairs labelled by a person, which don't exist yet, so this waits until after the MVP. Picklists at input keep most words from arriving unknown in the first place.

**D-32. One scoring function serves both directions; one-sided signals go in that direction's ranker.**
Two-sided hiring marketplaces optimise a different goal on each side. A recruiter wants candidates who fit and will respond; a job seeker wants jobs they fit and want. Both start from the same fit between one candidate and one job, which is what the brief asks us to score, and D-15 requires both endpoints to agree on it. So:
- **`score_match(candidate, job, credit)`** is pure: no database, and no notion of direction.
- **`rank_candidates_for_job` and `rank_jobs_for_candidate`** only choose which side is fixed and how ties break. A signal that belongs to one side goes into that side's ranker as a later stage, never into the fit score. Examples are candidate preferences (D-09) and recruiter-only filters.
- **Credit is passed in, not built in:** the scorer asks a credit source how much a candidate term earns toward a job term. The taxonomy is the source in production, exact matching in unit tests. An ESCO import, or embeddings after the MVP (D-31), would change the source, not the scorer.
- **Input is the structured record.** A free-text job description or résumé isn't parsed (see Out of scope).

The formula, replacing D-28's:
- **Skills (S):** credit earned ÷ required skills. The credit is 1.0 for the same term or the same concept, 0.5 for a related concept, and 0 otherwise (D-29).
- **One-to-one:** each candidate skill covers at most one requirement, so `persuasion` can't earn half of both `sales` and `negotiation`. The best assignment is found exactly, not greedily.
- **Experience (E):** as in D-28: 1.0 at or above the minimum, proportional below it.
- **Culture (T):** the same coverage as skills, of the job's culture keywords by the candidate's traits. A job with no culture keywords leaves T out, and the other weights are rescaled.
- **`score = round(100 × (0.7·S + 0.2·E + 0.1·T), 1)`.** Experience and culture keep their D-11 weights. Skills take availability's 0.1 until availability is scored.
- **Gate:** no skill credit means no match (D-12), so experience and culture can't create one.
- **Reason:** built from the breakdown (D-18), with the source of each partial credit, for example `negotiation ≈ persuasion ½`.
- **Pinned rankings:** the expected results under this formula are in `tests/test_matching.py`, for example Sherlock 95.0 and Sheldon 43.3 for Backend Detective. The table under D-11 describes the full formula, and applies once availability is scored.

---

## Scope check against the brief

| Brief requirement | Covered by | Type |
|---|---|---|
| Ingestion: "a way to load" the data | D-22 (startup seed) | Required |
| Own schema, including how a match is represented | D-19 to D-21 | Required |
| Raw, hand-written SQL only | D-19, D-23 (psycopg 3) | Required |
| `GET /jobs/{id}/matches` with a score and a short reason | D-15, D-18 | Required |
| `GET /candidates/{id}/matches` | D-15 | Required |
| Score accounts for skill overlap and experience fit | D-11 | Required |
| Weights, traits, culture keywords, availability, tie-breaking | D-10, D-11, D-16 | Left to us by the brief |
| README with curl examples | README | Required (minimum demonstration) |
| Tests and API docs | Expected-rankings tests, API docs generated by the framework | Optional bonus |
| POST endpoints, Docker Compose, `?min_score=` / `?include_passive=` filters, score breakdown, near misses | D-10, D-17, D-18, D-22, D-23 | Our extensions |

## Out of scope

Authentication, a UI (the brief says no frontend is needed), ML or LLM scoring, résumé parsing, matching on compensation, location or work authorization, pipeline stages, and a tool-level skill taxonomy.

Résumé parsing is out of scope because the brief supplies structured records, not because production can skip it: real candidates arrive as documents. It would be a separate stage that produces the same structured record the seed files use, so nothing after ingestion changes.

## Open questions

1. Is there a Part 2? The brief we have is labeled "Part 1".
2. What is the expected time budget?
