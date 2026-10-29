# DECISION.md — Recruiter Bot

The assumptions and design decisions behind this project, each with the reason for it.

_Last updated: 2026-10-29_

---

## Latest decision: how ties are broken (D-16, revised)

When two candidates have the same score for a job, `GET /jobs/{id}/matches` orders them by:

| Step | Rule | Why |
|---|---|---|
| 1 | **Total score**, highest first | The best fit always comes first. Nothing below can push a stronger candidate under a weaker one. |
| 2 | **Open before not looking** | Among equal fits, a recruiter calls the one who is looking first. Someone not looking is still listed; they need a different approach, not a lower rank (D-10). |
| 3 | **Earliest start date** | Among open candidates, whoever can start soonest. A date in the past counts as today, since "Immediate" is stored as the day it was loaded. |
| 4 | **A neutral hash** of the job and candidate ids | Still tied means genuinely equivalent. The hash gives the same order on every call, but favours no one, and it differs per job. |

**Not used, on purpose:**
- **The name.** Alphabetical order puts the same people first on every tie, for every job (Aaron always beats Zoe). That's a documented source of bias.
- **Years of experience.** Experience is already 20% of the score, capped at 1.0 once the minimum is met (D-13), so candidates tied on the total usually both meet it. Breaking ties by raw years would:
  - reward over-qualification, which D-13 rejects: 15 years isn't a better fit than 8 for a 3-year job;
  - favour older candidates, since years of experience track age. That's an age-discrimination risk under the US Age Discrimination in Employment Act and EU equal-treatment law.
- **Skill score.** It was an earlier step: with equal totals it preferred the candidate whose score came more from skills. It was removed to keep the rule simple. In this data every tie also had equal skill scores, so nothing changed.

The full reasoning is under D-16 in section 3. Since D-49, a job's `matches` only hold open candidates, so step 2 in effect sorts candidates who aren't looking into their own `proactive_offers` section.

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

*Superseded by D-53: names and titles are no longer unique; identity is an optional email, or company plus title.*

**D-05. Availability is stored as two fields.**
`open_to_opportunities` and `available_from DATE`. `Immediate` becomes (open, today), `2 weeks` becomes (open, today + 14), and `Not looking` becomes (not open, NULL). A CHECK constraint keeps the two consistent. Reason: the source mixes willingness to move with timing, and a date stays correct over time where "14 days from now" doesn't. "Today" comes from the database clock, so the result doesn't depend on the timezone of whoever runs the seed.
_Amended by D-39:_ "today" is the day the statement was made: the first load for seed records, or the day of a `PATCH` that changes availability. Re-running the seed no longer restarts the clock.

**D-06. Quirks and taglines are display-only.**
They are free text, so they are returned in responses but never scored.
Each match shows what its reader needs: a job's candidates carry their `quirk` for the recruiter, and a candidate's jobs carry their `tagline` (D-46). Matching quirks against taglines was considered and rejected: the structured form of both already exists (traits and culture keywords), the text is mostly jokes and sarcasm, and the model step measured 67% precision even on plain words (D-45).

**D-07. Experience means total career years.**
The source doesn't give years per skill.

---

## 2. Requirements

**D-08. Every skill a job lists is required, with no nice-to-have tier.**
Required means the skill counts toward the coverage score, not that a candidate must have all of them. Reason: no candidate has all three skills for Engineering Manager, Chaos Team, so treating "required" as all-or-nothing would leave that job with no matches.

**D-09. Candidate preferences are not modeled.**
The source has no preference data, so `GET /candidates/{id}/matches` ranks jobs by how well the candidate fits each one. No placeholder column is added; one can be added later when real data exists.
_Amended by D-47:_ job preferences are now collected and stored, but still not used in ranking.

**D-10. Candidates who aren't looking are kept and flagged for a proactive offer.**
Their score is lowered through availability, and each of their matches carries `outreach: { status: "passive", recommended_action: "proactive-offer" }`. Reason: the brief's own example, Michael Scott, is not looking. Passing `?include_passive=false` excludes them.
_Amended by D-49:_ built differently. Their score isn't lowered; a passive candidate who scores higher than every open one appears in a separate `proactive_offers` section, with `recommended_action: proactive-offer`. `?include_passive=` isn't needed.

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
- **Availability, in `GET /jobs/{id}/matches`:** among equal fits, open candidates come before those not looking, then the earliest start date. A start date in the past counts as today, because "Immediate" is stored as the day it was loaded. Without that, a candidate loaded earlier would outrank one loaded later, though both can start now.
- **The best fit always wins first.** Availability only reorders equal scores, so a strong candidate who isn't looking is never pushed below a weaker one. Ties are common in this data, because jobs list only two or three skills: six groups of tied scores, such as Elle and Hermione at 90.0, where Elle starts now and Hermione in two weeks.
- **Not in the candidate's view:** every job a candidate sees shares that candidate's availability, so it can't break a tie there. Those ties still break by job title.
- **Not yet in `show_matches` or the tests,** which compute matches directly and break ties by name.
- **Revised: no name, no skill-score step, in `GET /jobs/{id}/matches`.** The order is now score, then open before not looking, then the earliest start date, then a hash of the job and candidate ids.
  - **Why not the name:** sorting by name always puts the same people first, for every job; Aaron beats Zoe on every tie. Alphabetical order is a documented source of bias. The hash still gives the same order on every call, but differs per job, so no one is systematically first.
  - **Why skill score was dropped:** with equal totals, it preferred whoever's score came more from skills. In this data every tie also has equal skill scores, so removing it changed nothing today.
  - **Why experience isn't a tie-breaker:** experience is already in the score, capped at 1.0 at the minimum (D-13). Ranking ties by raw years would reward over-qualification, which D-13 rejects. Years of experience also track age, so it would favour older candidates; that's a discrimination risk (the US ADEA, EU equal-treatment law).
  - **Not done:** marking tied candidates in the response (`tied_with`), so a recruiter can see when an order means nothing.

**D-17. A minimum score of 50 decides what counts as a match.**
It's configurable, including per request with `?min_score=`. When no result reaches it, the response returns an empty list plus up to 3 near misses, each showing its missing skills. Reason: 50 means the candidate has at least about a third of the required skills and is otherwise strong. On a 3-skill job, one matching skill with everything else ideal scores exactly 50. On a 2-skill job, one matching skill scores 60. An unexplained empty list gives the recruiter nothing to act on.
_Built in D-49:_ near misses appear only when nothing reaches 50, at most 3, with a `near_misses_included` flag. `?min_score=` isn't built.

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
_Amended by D-39:_ the seed now only inserts records that don't exist yet; updates go through `PATCH` (D-38).

**D-23. The database is PostgreSQL, run with Docker Compose from the first commit.**
The brief allows any relational database. Postgres adds real foreign keys, `CHECK` constraints and `JSONB`. Docker Compose isn't required by the brief; it's added so reviewers can start everything with `docker compose up`. The setup includes a Postgres healthcheck the app waits for, no Postgres port exposed to the host, and README instructions for running without Docker. The driver is psycopg 3: it only executes the SQL we write and generates none.

For local development, Postgres is exposed on `127.0.0.1:5433`, which is bound to this machine only and avoids clashing with a local Postgres on 5432.

**D-24. Python 3.11+, psycopg 3 and pydantic.**
The brief says to use the language we're strongest in. psycopg 3 only sends the SQL we write. pydantic only validates input; it never builds SQL.

**D-25. Ingestion runs in three steps: extract, build the batch, write it in one transaction.**
1. `read_json_records` reads the file. `extract_candidates` and `extract_jobs` validate every record. A record missing a required field (candidate: name, skills, experience, availability; job: title, required skills, minimum experience), or with an invalid value, is **rejected with a reason and logged**. Valid records are kept, as in a typical bulk import, so one bad row doesn't block the rest. Unknown extra fields are ignored rather than rejected.
2. `build_candidate_batch` and `build_job_batch` turn the valid records into column lists that map directly onto the INSERT statements.
3. `insert_batch` writes the batch in one transaction, so the valid set is either fully applied or not at all. Inserts are set-based (`unnest` of arrays, one statement per table), not a loop of single-row inserts. Re-running is safe: upserts on slug only change rows whose data differs, and each record's skill and trait links are replaced as a whole. An advisory lock stops two concurrent loads from interleaving. Rejected input is logged to `ingestion_events` in its own transaction, independent of the batch.
_Amended by D-39:_ the seed skips records that already exist, so re-running it never changes stored data.

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
- **One-to-one:** each candidate skill covers at most one requirement, so `persuasion` can't earn half of both `sales` and `negotiation`. The best assignment is found exactly, not greedily (and in polynomial time since D-52).
- **Experience (E):** as in D-28: 1.0 at or above the minimum, proportional below it.
- **Culture (T):** the same coverage as skills, of the job's culture keywords by the candidate's traits. A job with no culture keywords leaves T out, and the other weights are rescaled.
- **`score = round(100 × (0.7·S + 0.2·E + 0.1·T), 1)`.** Experience and culture keep their D-11 weights. Skills take availability's 0.1 until availability is scored.
- **Gate:** no skill credit means no match (D-12), so experience and culture can't create one.
- **Reason:** built from the breakdown (D-18), with the source of each partial credit, for example `negotiation ≈ persuasion ½`.
- **Pinned rankings:** the expected results under this formula are in `tests/test_matching.py`, for example Sherlock 95.0 and Sheldon 43.3 for Backend Detective. The table under D-11 describes the full formula, and applies once availability is scored.

**D-33. The API is FastAPI with plain synchronous handlers, in `recruiter_bot/api/`.**
- **Why FastAPI:** it validates input and generates the API docs (`/docs`) from the same pydantic models, which covers the brief's optional API-docs bonus. It generates no SQL, so D-19 still holds.
- **Synchronous handlers:** psycopg is used synchronously throughout, and FastAPI runs sync handlers in a thread pool. Async would add complexity with no gain at this size.
- **One connection per request,** closed at the end. A connection pool is a later change if load needs it.
- **Thin handlers:** they call the rankers (D-32) and shape the response. No scoring logic lives in the API.
- **`GET /candidates/{id}/matches`** returns the candidate id and its matching jobs grouped into `strong_match`, `possible_match` and `near_miss` (D-34). Each tier is a list, best first, and every job carries its score, breakdown and reason (D-18). An empty tier is an empty list, so clients always see all three keys. An unknown id returns 404. Results are read from the `matches` table (D-37).
- **`GET /jobs/{id}/matches`** is the recruiter's view, with the same shape: the job id and its matching candidates grouped into the same three tiers.

**D-35. `POST /candidates` stores a new candidate and returns its matching jobs.**
- **Same code as the seed (D-22):** the body is the seed's `CandidateInput` model, so Swagger documents the fields. It then goes through `extract_candidates` and `insert_batch`, so normalization and validation are identical.
- **A name that already exists returns 409, not an overwrite.** The seed upserts by name, but the source data has no email or other identity. Through a public endpoint, posting "Sherlock H." would otherwise replace Sherlock's profile. Updating a profile would be a separate `PUT` later. The name check and the insert run in one transaction under the ingest lock, so two simultaneous requests can't both pass the check.
- **Rejections:** content that fails ingestion's rules, such as an unrecognized availability, returns 422 and is logged to `ingestion_events` with source `api` (D-25). Input with the wrong shape is rejected by FastAPI with 422 before it reaches our code, so it isn't logged; logging it would need a custom error handler.
- **Response:** 201 with the new `candidate_id` and its matching jobs, grouped by tier as in `GET /candidates/{id}/matches`. Unknown skills and traits are stored as usual and earn no credit (D-31).

**D-36. `GET /candidates` and `GET /jobs` list every record with its id.**
The match endpoints take an id, and ids aren't predictable: re-running the seed uses up identity values, so a new record can get id 76. Each list returns, sorted by id:
- **Candidates:** id, name, experience, skills and traits.
- **Jobs:** id, title, minimum experience, required skills and culture keywords.

Both reuse the profile queries the rankers use, so a list shows exactly what matching sees. There's no pagination or search: at 15 candidates and 6 jobs a plain list is simpler, and either can be added when the data grows.

**D-37. Matches are stored in the `matches` table and refreshed in the same transaction as the write that changes them.**
This puts D-21 into practice.
- **Postgres, one row per pair, not JSON.** Both directions read the same row through its two indexes, so they can never disagree (D-15). The row keeps the score, the breakdown, matched and missing skills, the reason and the algorithm version. Foreign keys remove a deleted person's or job's rows automatically. A JSON file or a list of ids per side would store each pair twice, lose the breakdown, and isn't safe under concurrent writes.
- **What triggers a refresh:**
  - **A candidate is added:** that candidate's rows are replaced, against every job.
  - **A job is added:** that job's rows are replaced, against every candidate. There's no job POST yet.
  - **A seed run, a taxonomy reload, or a changed formula:** every row is replaced.
- **Replace, never append.** An entity's old rows are deleted and fresh ones inserted. Appending would keep matches that no longer qualify, or scores that changed.
- **Same transaction as the write,** under the ingest lock. A reader sees either the old data with its old matches, or the new data with its new matches, never a mix.
- **`algorithm_version`:** reads only return rows with the current version. When the API starts and finds rows from another version, or an empty table, it recomputes everything. A formula change therefore can't silently serve old scores.
- **Tiers are worked out when reading,** from the stored score (D-34). Changing the 70 / 50 thresholds needs no recompute.
- **Stored:** every qualifying pair, including near misses (D-12, D-21).
- **At scale:** storing every pair stops working (100,000 × 10,000 is a billion rows). Real systems shortlist likely matches first, score only those, store the top results per entity, and recompute in a background queue. The table and the refresh functions stay the same; only what fills them changes.

**D-38. `PATCH /candidates/{id}` and `PATCH /jobs/{id}` change a stored record.**
- **Partial updates:** only the fields sent are changed. A list that is sent (skills, traits, required skills, culture keywords) replaces the stored list as a whole. Sending `null` for `quirk` or `tagline` clears it.
- **Same rules as ingestion:** the same constraints as `CandidateInput` and `JobInput`, and the same normalization (D-02). An empty skills list or an unknown availability returns 422 and is logged to `ingestion_events` with source `api`, like `POST`.
- **Renaming is allowed,** but a name or title that belongs to another record returns 409, since the slug is the identity (D-04). An unknown id returns 404.
- **Matches are refreshed in the same transaction** (D-37): the patched record's rows are replaced against the other side. The response is the record's matches, grouped by tier, as in `GET …/matches`.
- **No preferences:** the source data has none (D-09), so there's nothing to patch yet. Adding a preference field would come with its own decision on how it affects ranking.

**D-39. The seed only inserts records that don't exist yet.**
Once records can be edited, re-running the seed as an upsert would overwrite people's edits with the seed file. It also restarted the availability clock: a re-seed recalculated "2 weeks" from the new day, so Hermione's start date moved one day further out on every run and never arrived.
- **The seed bootstraps; the API owns changes after that.** Records already stored, matched by slug (D-04), are skipped and reported. New records in the file are still inserted.
- **This fixes the clock** (D-05): a seed record's availability is counted from its first load and never recalculated. A `PATCH` that changes availability counts from the day of the `PATCH`, when the person said it.
- **Cost:** editing an existing record in the seed file has no effect after the first load. Change it with `PATCH`, or start from an empty database. The taxonomy still reloads in full on every seed run, since it's configuration, not user data (D-30).

**D-40. `POST /jobs` stores a new job and returns its matching candidates.**
It mirrors `POST /candidates` (D-35):
- **Same code as the seed:** the body is the seed's `JobInput` model, then `extract_jobs` and `insert_batch`.
- **A title that already exists returns 409, not an overwrite.** The check and the insert run under the ingest lock. Changing an existing job goes through `PATCH` (D-38).
- **Rejections:** content that fails ingestion's rules returns 422 and is logged with source `api`.
- **Matches:** the new job's matches are computed against every candidate in the same transaction (D-37). The response is 201 with the `job_id` and its candidates grouped by tier.

This completes D-22's two POST endpoints.

**D-41. Unknown words are linked by deterministic rules first: negation, word roots, typos, and grouping.**
These are stages 0–3 of the linking pipeline, with the grouping step brought forward from stage 6. They run on every word that has no taxonomy label, at seed, `POST` and `PATCH`. No model is involved, so the same input always gives the same links.
- **A wrong link is worse than a missing one.** A missing link costs some credit, and the report shows it. A wrong link silently changes every score that uses the word. Every rule is tuned for precision.
- **1. Negation:** a word is negated when it contains a negating word (`not`, `no`, `non`, `never`, `without`, `lack`, `poor`, `weak`, `bad`, `terrible`, `unable`), or when it starts with `un`, `dis`, `in`, `im`, `ir`, `il` or `non` **and** what remains is a known label (`disorganized` → `organized`). A negated word is never linked. `discovery` isn't negated, because `covery` isn't a label.
- **2. Root key:** filler words are dropped (`of`, `in`, `and`, `skill`…), each word is reduced to its root, and the roots are sorted. `manage-product`, `managing-products` and `product-management` all become `manag-product`. A word whose root key matches the labels of exactly one concept becomes an alternative label of it. Matching more than one concept is reported as ambiguous and not linked.
  - **Conservative suffix rules:** `-ment`, `-ing`, `-ed`, `-es`, `-s`, and `-ion` only after `t`, then a trailing `e` and doubled consonants. Agent endings (`-er`, `-or`) are kept, because stripping them turns `customer` into `custom` and merges unrelated words. So `product-manager` doesn't link to `product-management`.
- **3. Typos:** Damerau-Levenshtein distance, with the limit applied **per word**: the two root keys must differ in exactly one word. That word gets at most 1 edit at 5–7 letters, at most 2 when longer, and none below 5, so `sale`, `java` and `sql` are never corrected. Only a single closest concept counts. A first version applied the limit to the whole key, and linked `product-management` to `project-management` (2 edits). Per word, that's 2 edits in a 7-letter word, and it's rejected. **The first letter must also match:** typos rarely change it, and the evaluation set (D-42) caught `apathetic` being linked to `empathetic`, an opposite only 2 edits away. The word becomes a hidden label, as ESCO uses hidden labels for misspellings: `persistant`, `organised`.
- **4. Grouping unknown words:** unknown words with the same root key that match no concept become one provisional concept (`auto-…`). The first word alphabetically is its preferred label. This covers both words being unknown: Steeven's `product-management` and a job's `manage-product`.
- **Linking only through reviewed labels:** words link through curated labels, or through a provisional concept's preferred label, never through another automatic label. That stops chains from drifting (A → B → C).
- **Audit:** automatic labels and concepts are marked `source = 'auto'`, with the method (`root_key`, `typo`, `group`) and the label they matched. A taxonomy reload deletes them, and the seed recreates them from the same rules.
- **Throughput:** root keys are stored, indexed, on the vocabulary and label rows. Negation, root matching and grouping are therefore index lookups for each new word, and a request only links the words it brings. Afterwards only the records that use a newly linked word are refreshed, with the credit source loaded once. Typo correction is the one scan: the labels of one type, narrowed by key length. At ESCO scale it would move to a SymSpell index.
- **Not done here:** splitting entries that name several skills (one term would need several concepts), meaning-based matching with models, and review screens. Those are the later stages, measured against a labelled evaluation set before automatic linking is switched on.

**D-42. Meaning-based linking runs on two small local ONNX models, measured against a labelled evaluation set.**
Stages 4–6 handle what the rules can't: words that mean the same but are written differently (`calm-under-stress` ↔ `calm-under-pressure`).
- **ONNX Runtime, not PyTorch:** the same models at a fraction of the size, roughly 0.5 GB for the image instead of 2 GB. No GPU, no API key, and no network once the files are present.
- **Embedding model (stage 4):** `BAAI/bge-small-en-v1.5` as the int8 ONNX export `Xenova/bge-small-en-v1.5`. 34 MB, MIT licence. It finds the concepts closest in meaning.
- **NLI model (stage 5):** `cross-encoder/nli-deberta-v3-xsmall` as the int8 export `Xenova/nli-deberta-v3-xsmall`. 87 MB, Apache-2.0, trained on MNLI and SNLI. It checks whether one phrase implies the other, and catches contradictions, which embeddings miss. The label order (`0 = contradiction, 1 = entailment, 2 = neutral`) is read from the model's config, never assumed.
- **Pinned and verified:** each file comes from a fixed commit (`ea104dac…`, `2a4f614a…`) and is checked against its SHA-256 before use, via `python -m recruiter_bot.linking.model_files`. The `.onnx` hashes are the ones Hugging Face publishes. The JSON files aren't in Git LFS, so their hashes were computed once from the fixed commit. The files live in `models/`, outside git.
- **Evaluation set:** 116 hand-labelled unknown words in `recruiter_bot/linking/evaluation_cases.json`, each with the outcome it should get:
  - **same (47):** linking is correct;
  - **related (29):** must only ever go to review;
  - **none (35):** near-misses (`product-management`), opposites (`anxious`), and new skills;
  - **negated (5).**
  
  The loader checks every case against the taxonomy, so a typo fails immediately.
- **Split by hash, not by hand:** about 60% of the cases tune the thresholds and 40% judge them. A case's split comes from a hash of its word, so nobody chooses which case lands where.
- **Limits, stated plainly:** the labels are our judgment, not a recruiter's. "Same" versus "related" is sometimes a matter of opinion, and 116 cases give wide error margins, so a test score is an estimate, not a guarantee. At production scale the set would grow from review decisions and from ESCO's alternative labels, which are human-curated synonyms.
- **It has already paid off:** running the rules over it exposed `apathetic` being linked to `empathetic` as a typo (D-41).
- **One input per model run, never a padded batch.** The int8 models scale their numbers over the whole batch, so batching made a phrase's vector depend on the other phrases in it: a measured difference of 0.012, enough to flip a threshold. Run one at a time, results are identical however they're grouped. It costs about 3 ms per phrase and 9 ms per NLI pair, so roughly 100 ms per unknown word at most.
- **Measured weaknesses the later stages must handle:**
  - The embedding scores `calm` closer to `anxious` (0.79) than to `level headed` (0.64), the opposite problem D-29 describes. So stage 4 only proposes candidates, and stage 5 must confirm them.
  - The NLI model calls some neutral pairs contradictions (`eating` vs `a doctor`: 0.92). So stage 6 calibrates its thresholds on the evaluation set rather than trusting the raw scores.

**D-43. Stage 4 represents each concept by its labels, name and description, words in short sentences, and proposes 10 candidates.**
For each unknown word, every concept of the same type gets the cosine similarity of its closest text. The top 10 go to stage 5. The choice was measured on the 43 calibration cases that have a known concept:

| How a concept is represented | Top 1 | Top 3 | Top 5 | Top 10 |
|---|---|---|---|---|
| A: labels | 63% | 70% | 84% | 88% |
| B: labels + names | 60% | 72% | 84% | 88% |
| C: labels + names + descriptions | 72% | 81% | 86% | 93% |
| **D: C, with words in short sentences** ("a person who is meticulous", "the skill of carpentry") | 70% | 81% | **88%** | **95%** |

- **Descriptions help most.** "Careful and thorough with details" carries meaning a two-word slug doesn't. Short sentences help lone adjectives the same way.
- **The difference between C and D is small:** one case is 2.3 points. D is chosen because it's at least as good at every cut that matters for retrieval.
- **10 candidates, not 5:** this stage sets the ceiling for the whole pipeline, since a concept it misses can never be linked. Wrong candidates only cost a check in stage 5, about 0.2 s per unknown word for 20 NLI checks, and only for words the rules couldn't place.
- **Not tuned to the test:** the remaining misses (`level-headed` and `composed` → calmness, `outspoken` → bluntness) come partly from thin descriptions. Rewriting descriptions until these cases pass would make the scores meaningless, so they were left alone. Richer ESCO descriptions are the production fix.
- **Scale:** the index embeds about 160 texts in about 0.4 s at startup, and a search is one matrix product. At ESCO scale (around 100,000 labels), the vectors would be computed once and stored, for example in pgvector, rather than re-embedded at every start.

**D-44. Stage 5 checks every candidate with NLI in both directions, against each of the concept's labels.**
The unknown word and a label are put into sentences ("This person is level headed." / "This person is skilled in carpentry."), and the model is asked whether each implies the other. Each candidate keeps its best-agreeing label and records:
- **forward and backward entailment.** Both high means a synonym; one high means broader or narrower.
- **contradiction,** the higher of the two directions.

Measured on the 630 candidate pairs of the calibration cases (27 synonyms against 603 other pairs):

| Signal | AUC for synonym vs everything else |
|---|---|
| Similarity alone (stage 4) | 0.890 |
| Entailment, one direction | 0.956 |
| Mutual entailment (the weaker direction) | 0.936 |
| Mutual entailment × (1 − contradiction) | 0.933 |

- **NLI adds real value:** it catches opposites that similarity ranks highest. `pessimistic` vs optimism, `apathetic` vs empathy, `lazy` vs overachievement and `fragile` vs resilience all have similarity 0.85–0.90, and a contradiction of 1.00.
- **It can't tell synonyms from related concepts:** both have a median mutual entailment of about 0.95. To the model, `coaching` and `mentorship` imply each other as strongly as `bargaining` and `negotiation`. That's the hardest decision in the pipeline, and stage 6 has to measure how often a related word would be auto-linked.
- **Contradiction is noisy:** it's high (median 0.90) for unrelated pairs too. It means "not the same" more than "opposite", so it can reject candidates but can't detect opposites.
- **One label was corrected:** `careless` was labelled 'none', as the opposite of detail-oriented. The system linked it to recklessness, with mutual entailment 0.99, and *careless* and *reckless* are near-synonyms. Changing labels after seeing results can quietly fit the test to the system, so this was the only change. It's recorded in the case's note, and the case is in the calibration split, not the test split.
- **Cost:** about 20–30 NLI checks per unknown word (10 candidates, 1–2 labels, both directions). That's 14 s for 63 calibration words, about 0.2 s per word.

**D-45. Stage 6 suggests, it doesn't link: automatic linking failed its precision target on the test cases.**

*Revised by D-54: confident links now earn capped "suggested" credit (0.25), never synonym credit.*
The rule: take the candidate with the highest mutual entailment, and auto-link it only if its mutual entailment, its similarity, and its margin over the runner-up all clear a threshold. Otherwise send it to review with the top 3 suggestions, or call it no match.
- **Calibration** (63 words, 616 settings tried, no wrong links allowed, then the most right ones): mutual entailment ≥ 0.50, similarity ≥ 0.86, margin ≥ 0.30. In words: one concept must clearly beat every other. Result: 7 right automatic links, 0 wrong.
- **Test** (48 untouched words, run once with those thresholds): **8 right, 4 wrong, a precision of 67%,** against a target of 98%.
  - 3 errors are related words linked as synonyms: `cybersecurity` → security, `eager-to-learn` → curiosity, `caring` → empathy (mutual entailment 0.96). That's the weakness D-44 measured, and no threshold removes it.
  - 1 is a near-miss: `pattern-making` → pattern-recognition, at mutual entailment 0.51, just over the line.
  - The 100% on calibration was overfitting: with 63 words, the zero-error region is small, and the chosen setting sat on its edge.
- **Not re-tuned:** changing the thresholds now would mean choosing them on the test set, which would make its 67% meaningless. The test set has been used, so any future threshold claim needs new test data.
- **Decision: automatic linking is off (`AUTOMATIC_LINKING = False`).** A confident match becomes the first review suggestion instead. In that mode, on the test words, the right concept is the first suggestion for 23 of 32 words (72%), and among the 3 suggestions for 25 of 32 (78%). Matching keeps the rules' precision (D-41), and the models save a reviewer most of the searching.
- **What would justify switching it on:**
  - **a larger labelled set,** several hundred words, for example from ESCO's alternative labels and from review decisions;
  - **a signal that separates "same" from "related",** for example ESCO's broader/narrower hierarchy, or a model fine-tuned on ESCO synonyms (the SapBERT recipe);
  - **precision of at least 98% on fresh test data** that played no part in the choice.
- **Not built:** meaning-based grouping of two unknown words with each other. The evaluation set doesn't cover it, so it couldn't be measured. Grouping stays rule-based (D-41).

**D-46. One command runs everything: a migration runner, and the API in Docker Compose.**
- **`python -m recruiter_bot.migrate`** applies the SQL files in `migrations/` that a database hasn't run yet, in name order.
  - **History:** a `schema_migrations` table records each file applied.
  - **All or nothing:** each file runs in one transaction together with its history row, so it's applied completely or not at all.
  - **Lock:** an advisory lock stops two copies starting at once from applying the same file twice.
  - **Older databases:** `--mark-applied` records every file without running it, once, for a database set up by hand before the runner existed.
  - **One file until the first release:** the schema grew through twelve migrations during development, several of which undid earlier ones. No shared database had run them, so they were merged into `001_init.sql`, which now shows the whole schema as it is. A local database that ran all of the old files already has this schema; one that ran only some of them needs a fresh start (`docker compose down -v`). After a release, changes go in new numbered files and existing ones are never edited.
- **`docker compose up --build`** starts Postgres, waits for its healthcheck, then starts the API. On every start the API runs the migrations, then the seed, then serves. Both steps are safe to repeat: migrations skip what's applied, and the seed only inserts records that aren't stored (D-39).
- **The image:** `python:3.12-slim`, running as an unprivileged user, with only the API's dependencies.
  - **Not included:** the model files and `onnxruntime`, `tokenizers` and `numpy`. They live in `requirements-linking.txt`, since the API doesn't use the model step (D-45).
  - **Port:** the API is published on `127.0.0.1:8000`, or on `API_PORT` if 8000 is taken.
- **Not yet:** the database port (`127.0.0.1:5433`) is still published for local development, which D-23 wanted to avoid. Only this machine can reach it.

**D-47. Candidates can state job preferences; they're stored now and used later. The job title isn't scored.**
- **The gap:** the score only measures how well a candidate *fits* a job. Nothing captures what the candidate *wants*, or what role they're aiming for. A job's title isn't scored either: candidates have no current title, past titles or desired role to compare it with, and the seed titles are jokes ("Backend Detective"), whose meaning already comes through their required skills.
- **Why collect preferences before using them:** this reverses D-09's "no placeholder column". Preferences can't be backfilled, so every profile created without them would be lost to the later feature. Collecting them now makes that feature possible without rewriting ingestion.
- **What exists:**
  - **Field:** `job_preferences`, an optional list in `POST` and `PATCH /candidates` (for example `["Sales Engineer", "Solutions Architect"]`). It's normalized like every term (D-02), and duplicates are removed.
  - **Storage:** one row per preference in `candidate_job_preferences`, like skills and traits (D-20), so a ranking step can join on it.
  - **PATCH:** a list replaces the stored one, and `null` clears it.
  - **Listing:** `GET /candidates` shows it.
- **Not used in scoring:** match scores are identical with or without preferences, as checked through the API. Using them would be a one-sided signal in the candidate's ranker, after the fit score, never inside it (D-32). For example, jobs whose title matches a preference would rank first among equal fits. Comparing titles fairly would also need them mapped to an occupation taxonomy (ESCO occupations, O\*NET-SOC), since free-text titles vary as much as skill names.

**D-48. The weights 0.7 / 0.2 / 0.1 are backed by a sensitivity analysis, not just judgment.**
There are no hiring outcomes to learn weights from, so the next best evidence is how much the rankings depend on the choice. `python -m recruiter_bot.sensitivity.report` re-ranks every job's stored matches with other weights. The stored skill, experience and culture scores are reused, so no matching code runs again. It first checks that the production weights reproduce all 32 stored scores exactly.
- **Real flips are told apart from ties:** a change of first place counts as a flip only when the new winner scores *strictly higher* than the old one. If the old winner is still level, only the tie-break order moved. Pairs tied under the new weights are also left out of the rank agreement. A first version counted ties as flips, and reported a misleading 77%.
- **One weight at a time, ±0.05 and ±0.10:** **0 real flips.** The only two changes are ties, at culture 0: Tony with MacGyver (all three Rapid Prototyping candidates score 100), and Michael with Dwight for Sales Engineer.
- **All 31 plausible weightings** (skills ≥ experience ≥ culture): in 5 of the 6 jobs, the winner is never beaten. Engineering Manager is the exception: Ted beats Miranda in 3 of the 31.
- **That boundary is exact:** Miranda has 2/3 skills and no culture match; Ted has 1/2 skills and 1/2 culture; both have full experience. Ted wins only when **the culture weight exceeds one third of the skills weight.** Production uses 0.10 against 0.70 ÷ 3 ≈ 0.23, far from it.
- **Rank agreement** never drops below 0.83, where 1.0 means the same order.
- **Tiers are more fragile than winners:** candidates just below or above a boundary change tier under small moves. Leslie, Ted and Miranda sit at 48.3, just under 50; Michael at 71.7, just over 70. That's a property of any threshold, which is why every match shows its score next to its tier.
- **Conclusion: the analysis supports the formula.** While skills stay dominant, the exact weights don't decide who comes first; the data does. Culture's real effect is separating otherwise equal candidates, the role D-11 gave it. The only genuine flip needs culture above a third of skills, which contradicts the design. Changing a weight therefore needs evidence of a better ranking, such as outcome data, not a different opinion.
- **What it doesn't prove:** robustness isn't correctness. It shows the ranking doesn't hinge on 0.7 versus 0.65. It doesn't show a recruiter would rank people this way; only outcome data can, and this is 6 jobs.
- **Guard test, to be written:** "under any ±0.05 change to one weight, no job's top candidate changes." It holds today, and it would catch a future formula change that quietly reshuffles winners.

**D-49. The recruiter's view has two sections: who can be hired now, and who is worth a proactive offer. Near misses appear only when nothing else does.**
"Who can I hire?" and "who should I approach?" are two different workflows, so `GET /jobs/{id}/matches` (and the job `POST` and `PATCH` responses) return:

1. **`matches`:** candidates **open to opportunities**, whatever their start date, grouped by tier and ordered by score, then the earliest start, then the neutral hash (D-16).
2. **`proactive_offers`,** second: candidates **not looking** who are a strong or possible match **and score higher than the best open candidate**. Each carries its tier and `recommended_action: proactive-offer`.

- **Why "beats the best open candidate", not "strong matches only":** a proactive offer costs real effort, and it only pays off when nobody available is as good. A tier rule gets both directions wrong on this data:
  - Engineering Manager's best candidate overall, Miranda (66.7, possible, not looking), would vanish from both sections.
  - Michael (60.0) would be chased for Developer Relations, where four open candidates score 55–90.

  With the chosen rule, the offers are Tony (Rapid Prototyping, 95.0 against 92.5), Miranda (Engineering Manager, 66.7 against 60.0) and Michael (Sales Engineer, 71.7 against 66.7).
- **This answers the brief's planted contradiction:** "Michael Scott is applying to be a sales engineer", but the data says "Not looking". He is neither hidden nor ranked as if he could interview tomorrow: he's the one Sales Engineer worth an offer.
- **`proactive_offers_included`** is always in the recruiter response: `true` when at least one candidate is worth a proactive offer, `false` when nobody who isn't looking beats the best open candidate. An empty `proactive_offers` list on its own can't say which, so a reader would have to guess the rule. It sits next to `near_misses_included` for the same reason, and it always equals `len(proactive_offers) > 0`; this was checked on every job. It's a response field, not a request option: the section is part of the answer, not something the caller asks for.
- **Near misses** (below 50) appear only when there is no strong or possible match, as D-17 decided, and then at most 3, best first. They explain what's missing; next to real matches they're noise. A `near_misses_included` flag says whether they're there, and the `near_miss` key is always present, so the shape never changes. This applies to the candidate's view too: Ron, whose best job scores 43.3, sees two near misses, while Elle sees none.
- **Unchanged:** scores, stored matches and the sensitivity results. This only decides which section a match goes into. The candidate's view has no passive split, since the candidate is always the same person.
- **Not built:** `?include_near_misses=true` to see them anyway, and `?min_score=`.

**D-50. Every match carries its rank and the evidence behind its score.**
A score is only useful if a recruiter can see what it's based on, so each entry has:
- **`rank`:** its position, 1 being the best. It runs across the tiers within `matches`; proactive offers are ranked among themselves.
- **`evidence`, the default:** for skills and culture, only what was **matched** and what is **missing**; for experience, which has no list of terms, one sentence (`"11 years, meets the 3-year minimum"`). Nothing else. It's the same on the recruiter's and the candidate's endpoint.
- **`score` and `reason`** stay on the entry, as the brief asks: "a score and a short reason".

- **`score_breakdown`, only with `?explain=true`:** for skills, experience and culture: the factor's score, its weight, the **points** it adds (100 × weight × score), a sentence, and what matched and is missing. **The points add up to the score:** Michael for Sales Engineer is 46.7 + 20.0 + 5.0 = 71.7. This was checked on every entry of every view: 44 entries, all exact. For a job with no culture keywords, the weights shown are the rescaled 0.778 / 0.222.
- **Why compact by default:** the numbers suit an audit of one candidate, not a list of many. The weight is the same on every entry, and a reader acts on *what matched and what is missing* ("ask about negotiation"), not on 46.7 points. This is the progressive-disclosure pattern production systems use: a short answer, the full detail on request.
- **How it's built:** `?explain=true` is an optional query parameter of `GET /jobs/{id}/matches` and `GET /candidates/{id}/matches`. Without it, `score_breakdown` isn't sent at all, rather than sent as `null`. Scores, ranks and order are identical either way, as checked on every endpoint. POST and PATCH always return the compact view, and a value that isn't a boolean returns 422.
- **Stored, not parsed:** matched and missing culture keywords are now stored with each match, like skills. The reason text is never read back. `ALGORITHM_VERSION` went to 3, so every stored match is recomputed once (D-37).
- **Simpler entries:** the flat `skill_score`, `matched_skills` and similar fields moved into `evidence`, so nothing is duplicated.
- **The quirk stays a shown detail,** next to the evidence and never inside it (D-06). Scoring jokes was rejected on evidence: the model step reached only 67% precision even on plain words (D-45).

**D-51. A candidate's jobs are ordered by fit, then preference, then their chance of getting the job.**
`GET /candidates/{id}/matches`, and the candidate `POST` and `PATCH` responses, order jobs by:
1. **Score:** the fit, the same number the recruiter sees (D-15).
2. **Preference:** jobs whose title is one of the candidate's `job_preferences` come first (D-47).
3. **Standing:** the share of rivals the candidate beats.
4. **Posting date,** newest first.
5. **The neutral hash** of the job and candidate ids (D-16).

- **Standing:** a rival is another candidate with a strong or possible match (50 or more) for the same job **who is open to opportunities**, since someone not looking isn't competing for the role now.
  - **Calculation:** `(rivals below + ½ × rivals level) ÷ all rivals`, or 100% with no rivals. One query computes it for all of a candidate's jobs.
  - **Example:** Elle beats 88% of rivals for Developer Relations (3 below, Hermione level). Ted is the top applicant for Engineering Manager (60.0): Miranda scores higher but isn't looking.
  - **Why it separates tied jobs:** the tie is the candidate's *own* score for two jobs. Standing compares that score with the *other* candidates for each job, a different group per job. With 70 for both Job A and Job B, one rival at 90 for Job A gives 0%, and two rivals at 55 for Job B give 100%, so Job B comes first. Only the total score is compared, since it already combines skills, experience and culture with the agreed weights. Comparing the parts separately would contradict that weighting.
  - **When it doesn't separate them:** when the candidate's position is also the same in both pools. Ron scores 43.3 for both his jobs, with 2 rivals above and none below in each, so 0% in both. The posting date and then the hash decide.
- **Why standing comes after the score, never first:** score measures fit; standing measures competition. Sorting by standing first would put a weak-fit job with few rivals (52, nobody else) above a strong-fit one (90, three rivals), steering candidates toward the jobs they fit worst. It also changes whenever someone joins, so as a first key the whole list would keep reshuffling.
- **Privacy:** the exact share is used only for ordering. The response shows `top_applicant` (no rival scores higher, like LinkedIn's badge) and `matches_preference`. A percentage in a pool of three would reveal other candidates' scores.
- **The posting date** (`jobs.created_at`) comes late on purpose. Older ads are more likely to be filled, but every seed job was posted the same day, and companies repost ads to look fresh, so it decides almost nothing here.
- **Verified:** with a preference for Sales Engineer added in a rolled-back transaction, Ron's two jobs tied at 43.3 swapped, Sales Engineer first. Without one, his equal standing (0% in both) falls through to the date, then the hash.
- **The production direction:** a learned model of the chance of getting hired would replace these hand-ordered steps, once there's outcome data. Until then, the steps are transparent and each answers a question the candidate has.

**D-34. Every qualifying match is labelled with a tier.**
| Tier | Score | Meaning for the recruiter |
|---|---|---|
| `strong_match` | ≥ 70 | Worth contacting |
| `possible_match` | 50 to < 70 | Worth a closer look |
| `near_miss` | < 50 | Has some skill credit but falls short; the near misses of D-17 |

- **The gate comes first:** a pair with no skill credit is not a match at all (D-12) and gets no tier. The tier only grades pairs that pass.
- **50 counts as a match,** as D-17 sets it. The thresholds are named constants (`STRONG_MATCH_SCORE`, `MATCH_SCORE`), so a change is one line.
- **Rankers still return one sorted list,** with the tier on each result, so no result is dropped and both directions answer in the same shape. Grouping happens where results are shown: the API groups them into three lists, and `show_matches` prints the tier on each line.
- **Not yet:** the `?min_score=` filter and the limit of three near misses from D-17. Every near miss is listed for now.

**D-52. The best skill pairing is found by the Hungarian algorithm, not by trying every combination.**
D-32 pairs each candidate skill with at most one requirement so that the total credit is highest. The first implementation tried every combination, which is exact but grows exponentially. Measured on synthetic jobs where each candidate skill is related to a few requirements:

| Required skills | Candidate skills | Exhaustive search | Hungarian |
|---|---|---|---|
| 8 | 25 | 5 s | 0.2 ms |
| 10 | 25 | 109 s | 0.3 ms |
| 12 | 25 | did not finish | 0.3 ms |
| 40 | 80 | not run | 3.8 ms |

- **Why it mattered:** matches are computed at write time, inside a transaction that holds the ingest lock, so one slow job would freeze every other write. It was invisible on the seed data, where jobs list 2–3 skills and the taxonomy has few relations. Real postings list 8–20 skills, and a larger taxonomy makes credit denser.
- **Same answers:** the new code was compared with the old search, loaded from git, on all 272 real candidate-and-job pairs and on 20,000 random tie-heavy cases. The total credit, the pairing, the matched and the missing terms were identical in every one. Refreshing all 37 stored matches changed none of them, so `ALGORITHM_VERSION` stays 3.
- **Ties are settled by a stated rule,** the one the old search happened to follow, now encoded in the weights (`term_matcher.py`): requirement by requirement from the first, leave it unpaired if that loses nothing, otherwise take the term with the most credit, then the alphabetically first. For example, Elle's `persuasion` is equally related to `negotiation` and `sales`, and goes to `sales`, the later one: the evidence reads `sales ≈ persuasion ½ · missing negotiation`. The score is the same either way; only which requirement is named missing depends on the rule.
- **Not a library:** `scipy.optimize.linear_sum_assignment` solves the same problem, but pulls in a large dependency for about 70 lines, and its tie handling can't be controlled.
- **Where it lives:** `matching/assignment.py` is a plain maximum-weight assignment on whole numbers, knowing nothing about skills. `term_matcher.py` turns credits into weights and reads the answer back.

**D-53. Names and titles aren't unique: identity is an optional email for candidates, and company plus title for jobs.**
D-04 made the normalized name the identity, because the data has no email or id. That stops two people with the same name from both being stored, which is wrong for real people. Migration 008 changes it:

| | Before | Now |
|---|---|---|
| Candidate identity | `UNIQUE (slug)`, the name | `email`, optional, `UNIQUE` when present, stored in lower case |
| Job identity | `UNIQUE (slug)`, the title | `company`, optional, with `UNIQUE (lower(company), slug)`: one title per company |
| How the writers and the seed recognise a record | the slug | `source_key`, always filled and unique: `seed:<slug>` for seed records, `api:<random id>` for API records |

- **NULL is allowed and never clashes.** A primary key can't be NULL, so the primary key stays `candidate_id` / `job_id`. `UNIQUE` treats every NULL as different, so the 15 seed candidates without email, and two "Alex Kim"s, are all allowed, while the same email twice is refused.
- **What returns `409` now:**
  - a candidate whose email is already used, in any letter case;
  - a job whose title already exists at the same company, in any letter case;
  - the same, through a PATCH.
  - A repeated name, or a repeated title with no company, is accepted.
- **The cost, stated honestly:** while email is missing, the same person posted twice can't be detected; there is nothing to compare. The same goes for a job with no company. That's a limit of the data, not a rule the code can supply.
- **Why `source_key`:** the batch writer linked skills to records by slug, which would mix up two people with the same name. Seed keys come from the name, so rerunning the seed still adds nobody twice; API keys are random.
- **Shown, never scored:** `email` in the candidate list, `company` in the job list and in a candidate's job matches, so namesakes and same-title jobs can be told apart. Matching uses ids only, so no score changed.
- **Verified** on a throwaway database, 17 checks: seeding twice gives 15 and 6; namesakes are separate records with their own matches; email clashes are refused in any case, and by the database itself as a backstop; same title is refused at the same company, allowed at another or with none; PATCH follows the same rules; `email: null` clears it. The 16 tests pass.

**D-54. Words the rules can't place go to an optional model stage, which can only add capped "suggested" credit.**
D-45 kept the models out because a confident link counted as a full synonym, and only 8 of 12 test links were. Re-scored with the credit a guess deserves, 11 of the 12 were acceptable: 8 synonyms, plus 3 related words linked to the right concept. So the models now run inside ingestion, at a strength that matches their measured reliability:

| | Credit | Who decides |
|---|---|---|
| Same word, synonym (curated) | 1.0 | the taxonomy |
| Related concept (curated) | 0.5 | the taxonomy |
| **Suggested by the model** | **0.25** | **the model, until a person reviews it** |

- **Order:** exact label → negation → word roots → typos → grouping (the rules, D-41) → **the model stage**, only for words still unplaced. Negated words never reach it.
- **The model stage** is the existing D-43 to D-45 pipeline: the embedding model finds the 10 closest concepts, NLI checks each in both directions, and the calibrated thresholds decide:
  - **confident:** stored as `linked`; the word earns 0.25 toward that concept;
  - **plausible:** stored as `review`, with up to 3 suggestions, for a person to decide;
  - **neither:** no row; the word stays unknown, as before.
- **Guards:**
  - **A guess never creates a match on its own.** At least one required skill must match through the taxonomy itself, so the one wrong confident link in the evaluation (`pattern-making` → pattern-recognition) can't put anyone on a list.
  - **One guess per pair:** two unknown words suggested to the same concept earn nothing, and a suggestion never travels through a relation.
  - **Labelled:** the reason reads `crisis-management ≈ crisis-handling (suggested ¼)`.
  - **Auditable:** every row in `term_suggestions` keeps the model scores behind it and the model version. `GET /taxonomy/suggestions` lists the linked words and the review queue, and says whether the models are running.
  - **Reproducible:** the curated taxonomy file is the index, never the automatic labels, so one guess can't build on another; every seed run recomputes all decisions.
- **Fallback, never failure.** Ingestion carries on with the rules alone when:
  - `MODEL_LINKING=off` is set (the tests use this, so they don't depend on model files);
  - the libraries or model files are missing, or a model fails to load (remembered for the process);
  - one word fails in the model (only that word is skipped);
  - storing a suggestion fails: every database step runs in its own savepoint, so the POST, PATCH or seed that called it still commits.
- **Docker: off by default.** A plain `docker compose up --build` builds a rules-only image (230 MB) with no download, so the first run doesn't depend on Hugging Face or a 125 MB fetch. `WITH_MODELS=true docker compose up --build` installs `requirements-linking.txt` and downloads the two pinned, hash-checked models (a 698 MB image). If that download fails, the build still succeeds and the API runs rules-only. Both builds were run and checked: the default reports `model linking: unavailable, rules only` and serves matches; the model build reports `on`.
- **Verified** on a throwaway database, 12 checks:
  - the seed with the models on gives scores identical to the seed with them off;
  - `crisis-handling` and `calm-under-stress` earn ¼ each and are labelled;
  - a candidate whose only skill is a suggested one gets no match;
  - off, missing libraries, a failing word, and a write rejected by Postgres all leave the POST succeeding.

  On the seed data the models link nothing: all 13 unknown words fall below the thresholds and go to review. That's the thresholds working; some suggestions are poor (`fast-paced` → enthusiasm).
- **Cost:** about 2 s to load the models once per process, and 0.2 s per new unknown word, paid at write time, never when reading matches.
- **`ALGORITHM_VERSION` is 4,** because credit rules changed; stored matches are recomputed on startup.
- **Still honest about the limits:** the 0.25 cap rests on 12 confident test links, which is promising, not proven; and two unknown words aren't compared with each other, so `customer-handling` vs `customer-management` still earn nothing.
- **Scaling path:** the same three stages with ESCO's 13,000+ skills as the index (vectors in Postgres with `pgvector`), an embedding model fine-tuned on ESCO's own synonym pairs, and every review decision becoming a new labelled example.

**D-55. Unknown words are handled by a learning loop: real ESCO labels, the rules, the optional models, and a person's decision, which the system keeps.**
Until now the taxonomy had ESCO's *shape* but almost none of its content: 51 main names, 2 synonyms and 1 misspelling. An earlier README line said every concept had synonyms; that was wrong, and it is corrected.

- **Real ESCO labels, extracted, not the full dataset.** This is a prototype, so only the ESCO records it maps to are kept, in `seed/esco_snapshot.json` (46 KB, CC BY 4.0, (c) European Union):
  - 32 of our 51 concepts were mapped by reviewing ESCO's search results, definitions and labels; the top search hit was often wrong (`deduction` → "specialised astrology software", `negotiation` → "perform political negotiation");
  - 19 have no ESCO equivalent: personality words ESCO doesn't model (`blunt`, `reckless`…), and skills ESCO only has in sector versions (`negotiation` for land, insurance or politics);
  - `python -m recruiter_bot.linking.esco_import` adds the labels to `seed/taxonomy.json`. It's deterministic, and a second run adds nothing. Labels that aren't true synonyms were left out, each with its reason (`show positive attitude` is optimism, not enthusiasm; `lead` alone is ambiguous), and a label two concepts would claim is left out of both;
  - **the result: from 3 synonyms and misspellings to 236.** ESCO has almost no misspellings (its hidden labels were empty), so typos still come from the D-41 typo rule.
  - **Seed scores: none changed.** Two records added by hand did: `critical-thinking` now links to deduction ("think critically" is an ESCO synonym of logical reasoning), and the model now links `prototyping` to rapid-prototyping.
- **Why not train a classifier on this data.** A classifier needs a class per concept and retraining whenever concepts change; most concepts have 3–12 ESCO labels, personality words have none; and it always picks *some* class, while "I don't know" is the case that matters. Production entity linkers keep the knowledge in data and the models frozen. So here, learning means adding a label:

  ```
  unknown word → 1. known label (curated, ESCO, approved)  → full credit
               → 2. rules: negation, word roots, typos      → full credit
               → 3. optional models (D-54)                  → ¼ credit, or the review queue
               → 4. a person: approve / reject              → approved: full credit from now on
  ```
- **The learning loop (two endpoints):**
  - `POST /taxonomy/suggestions/{type}/{term}/approve` with `{"concept": "<slug>"}`, or no body to accept the model's best concept. The word becomes a synonym (credit 1.0) for every record, now and later, and survives every reseed.
  - `POST /taxonomy/suggestions/{type}/{term}/reject`: the word loses any suggested credit and is never suggested again.
  - Both refresh every affected match in the same transaction.
  - They refuse a word nobody uses (404), a word that is already a label (409), and an unknown concept or type (422).
  - **There's no login,** since authentication is out of scope (D-19); in production these would be for administrators only.
  - **Verified end to end** on a throwaway database through the HTTP API, 11 checks:
    - Pat's `bargaining` went to review, with negotiation as the first suggestion. After one approval, Pat's match rose from 43.3 to 66.7 at once.
    - The next candidate using `bargaining` got full credit immediately.
    - The approval survived a reseed.
    - A rejected guess lost its ¼ and stayed rejected after a reseed.
- **Measured on independent data** (`python -m recruiter_bot.linking.evaluate_esco`): 20% of the imported ESCO synonyms (48), chosen by hash, are hidden from the system, plus 164 look-alike ESCO concepts that ESCO defines as different (such as "negotiate land access"). Neither list was written by us, and the D-45 thresholds were fixed before this test existed.

  | | Result (95% interval) |
  |---|---|
  | Automatic credit right | 24 of 37 = 65% (49–78%) |
  | … by the word-root rule | 9 of 10 = 90% (60–98%) |
  | … by the model | 15 of 27 = **56%** (37–72%) |
  | Hidden synonyms sent to review | 24, with the right concept **first in all 24** |
  | Look-alikes wrongly credited | 13 of 164 = 8% (5–13%) |
  | Look-alikes sent to review | 136 of 164 |

  - **This corrects D-54's "11 of 12".** That figure came from words we labelled, scored leniently after seeing the results. Scored strictly by ESCO's definitions, the model's automatic guesses are right about half the time.
  - **The errors are narrower or related ESCO concepts, never opposites:** `show empathy` → empathy, `woodworking tools` → woodworking, `crisis intervention` → crisis-management. That is the kind of error the ¼ cap (half of a curated "related" link) is sized for.
  - **The review queue is the strong part:** each synonym the model was unsure about had the right answer first, so one approval teaches the system. Its cost is volume: most look-alikes land in review too, so a reviewer sees noise.
  - **Not done here:** recalibrating the thresholds on ESCO data, which needs a separate calibration split. Whether the model should give automatic credit at all at 56% is an open decision; review-only (credit 0 until approved) is the safer setting.
- **Scaling up:** load ESCO's full CSV with the same importer; store vectors in Postgres with `pgvector`; fine-tune the embedding model offline on ESCO's synonym pairs plus every approval; recalibrate the thresholds on each release, on a held-out ESCO split, using this same script.

**D-56. Each job says whether its minimum experience is required or preferred; below it, a match is never "strong".**
Before, the minimum was fully soft: a candidate with every skill and **0 of 8 required years** scored 80.0, a **strong match**. The score was right by the formula, but the label claimed a fit the job's own requirement says is missing.

- **Production practice:** ATS platforms (Greenhouse, Workday, Lever) separate *required* from *preferred* qualifications, and the job owner chooses. A required one is a knockout, a preferred one only lowers the ranking, and either way the gap is shown, not hidden. The system shouldn't guess a hiring policy.
- **So, per job, `experience_requirement`:**

  | Setting | Below the minimum |
  |---|---|
  | `preferred` (the default) | The score drops in proportion, as before, and the tier is **at most `possible_match`** |
  | `required` | **No match**, like a job with no skill in common (D-12) |

  It's set on POST and PATCH, shown in `GET /jobs`, and can't be cleared.
- **Why `preferred` is the default:** the seed data doesn't say, and the brief asks for experience *fit*, not a filter. The gentler reading excludes no one, and it matches the ambiguity decision that the minimum is soft (D-13). The score formula is unchanged, so the sensitivity analysis (D-48) and the shared score in both directions (D-15) still hold.
- **The gap is always visible:** every match entry has `meets_minimum_experience` (true or false) next to the experience evidence ("8 years, below the 10-year minimum"), so a client can show a warning badge without reading text.
- **Ranks follow the tiers:** a capped candidate keeps its score, so a 96 below the minimum could outscore a strong 85. Each list now shows strong matches first, then possible ones, each in its own order, so rank 1, 2, 3 runs down the page.
- **Effect on the current data: none.** No candidate was "strong" while below a job's minimum; 0 of 38 pairs changed tier and no score changed. `ALGORITHM_VERSION` is 5.
- **Verified** through the live API, 8 checks:
  - Sherlock (8 years) for a new job asking 10 scored 96.0 and was labelled `possible_match`, with `meets_minimum_experience: false`;
  - set to `required`, he was no longer a match; set back to `preferred`, he returned;
  - his strong matches for other jobs were unaffected;
  - an unknown setting, or a null one in PATCH, returns 422.
- **Not done:** a tolerance band ("within a year of the minimum counts"). That's a per-job policy for the job owner, and it can be added the same way.
- **Revised: `required` is now the default for every job** (`ALGORITHM_VERSION` 6).
  - **Why:** a stated minimum is treated as a must, so nothing is assumed to be negotiable. `preferred` stays available for a job owner who chooses it later. This replaces D-13's "the minimum is soft" reading for listing purposes; extra years still earn nothing extra.
  - **Effect:** 2 of 38 matches disappeared, both near misses (Steeven, 0 of 3 years; Elle for Incident Commander, 3 of 4). No other score or tier changed.
  - **A consequence to know:** every listed match now meets the minimum, so its experience part is always full: 20 points for everyone. Experience decides *who is listed*, not the order among them; skills (70%) and culture (10%) do the ranking. For a `preferred` job, experience still ranks in proportion.

---

## Problems faced and how they were solved

Each of these was found by checking results against real or held-out data, not by an existing test failing. The first is written out in full; the others are in the table below it.

### The best skill pairing took minutes for realistic jobs (D-52)

- **The problem:** matching pairs each candidate skill with at most one requirement, so one `persuasion` can't count toward both `sales` and `negotiation`. The pairing with the most credit in total has to be found. The first version tried every combination.
- **Why it stayed hidden:** the seed jobs list 2–3 skills and the taxonomy has 11 relations, so almost nothing earns credit. Every test and every live check ran in microseconds.
- **How it was found:** while asking "is the overlap robust?", the matcher was timed on synthetic jobs instead of assumed to scale.

  | Required skills | Candidate skills | Time |
  |---|---|---|
  | 6 | 25 | 0.12 s |
  | 8 | 25 | 5 s |
  | 10 | 25 | 109 s |
  | 12 | 25 | did not finish |
- **Why it was serious:** matches are computed at write time, inside a transaction that holds the ingest lock. One job with ten skills would freeze every other write for minutes, and real postings list 8–20 skills.
- **Options weighed:**
  - **Greedy** (take the best credit first): fast, but wrong, because it can block a better total.
  - **`scipy`'s solver:** right, but a large dependency for about 70 lines, and its tie handling can't be controlled.
  - **The Hungarian algorithm, written out:** exact, polynomial time, and the ties can be controlled. Chosen.
- **The fix:** `matching/assignment.py` solves the pairing as a maximum-weight assignment. The tie rule that the old search followed by accident is now an explicit rule, encoded in the weights.
- **The proof:** the old search was loaded from git and compared with the new one.
  - 272 real candidate-and-job pairs, and 20,000 random cases full of ties: identical total credit, pairing, matched and missing terms.
  - All 37 stored matches were refreshed, and none changed.
  - 10 skills went from 109 s to 0.3 ms, and 40 skills take under 4 ms.
- **A false start worth recording:** the first tie scheme gave the same total credit but a different pairing in 629 of 6,000 tie cases. Comparing the pairing, not just the total, caught it, and it was replaced before anything was kept.
- **The lesson:** a claim about an algorithm has to be measured at realistic sizes. The seed data could never have shown this.

### Other problems found by checking, and how each was solved

| Problem | How it was found | Fix | Decision |
|---|---|---|---|
| Re-running the seed pushed "2 weeks" a day further each time, so Hermione never became available | Comparing each candidate's `created_at` with the stored `available_from` | The seed only inserts new records, and PATCH edits survive | D-05, D-39 |
| A typo rule linked `product-management` to `project-management`, two different jobs | Reading the linker's output on the real vocabulary | Typo distance is judged per word, not over the whole key | D-41 |
| The same rule linked `apathetic` to `empathetic`, opposites | Running the rules over the 116-word evaluation set | A typo must keep its first letter | D-41 |
| The int8 embedding model gave a phrase a different vector depending on which phrases shared its batch (a 0.012 difference, enough to flip a threshold) | A determinism check on the model wrapper | One input per model run | D-42 |
| Model-based linking looked perfect on calibration (7 right, 0 wrong) and reached only 67% precision on the untouched test set, against a 98% target | Judging the chosen thresholds once on held-out words | Automatic linking switched off; the experiment kept out of the submission | D-45 |
| The model's measured accuracy (11 of 12) came from words we labelled ourselves, scored leniently after seeing the results | Re-testing on ESCO's own labels, which nobody here wrote | Report the independent number, 56% strict for the model's automatic guesses, and keep its credit capped | D-55 |
| A candidate with every skill and 0 of 8 required years was labelled a strong match | Probing the scorer's edge cases the way an interviewer would | A per-job `required` / `preferred` setting; below the minimum a match is at most possible, or no match when required | D-56 |
| The sensitivity report counted a tie for first place as a changed winner, and reported a misleading 77% | Re-reading the report after the tie-break rule changed | A change counts only when someone scores strictly higher | D-48 |

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

Authentication, a UI (the brief says no frontend is needed), ML or LLM scoring (models only suggest capped credit for unknown words, D-54), résumé parsing, matching on compensation, location or work authorization, pipeline stages, and a tool-level skill taxonomy.

Résumé parsing is out of scope because the brief supplies structured records, not because production can skip it: real candidates arrive as documents. It would be a separate stage that produces the same structured record the seed files use, so nothing after ingestion changes.

## Open questions

1. Is there a Part 2? The brief we have is labeled "Part 1".
2. What is the expected time budget?
