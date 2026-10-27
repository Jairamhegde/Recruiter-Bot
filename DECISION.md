# DECISION.md — Recruiter Bot

The assumptions and design decisions behind this project, each with the reason for it.

_Last updated: 2026-10-27_

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

## Open questions

1. Is there a Part 2? The brief we have is labeled "Part 1".
2. What is the expected time budget?
