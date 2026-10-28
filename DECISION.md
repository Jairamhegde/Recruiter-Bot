# DECISION.md — Recruiter Bot

The assumptions and design decisions behind this project, each with the reason for it.

_Last updated: 2026-10-28_

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
- **One-to-one:** each candidate skill covers at most one requirement, so `persuasion` can't earn half of both `sales` and `negotiation`. The best assignment is found exactly, not greedily.
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
- **Near misses** (below 50) appear only when there is no strong or possible match, as D-17 decided, and then at most 3, best first. They explain what's missing; next to real matches they're noise. A `near_misses_included` flag says whether they're there, and the `near_miss` key is always present, so the shape never changes. This applies to the candidate's view too: Ron, whose best job scores 43.3, sees two near misses, while Elle sees none.
- **Unchanged:** scores, stored matches and the sensitivity results. This only decides which section a match goes into. The candidate's view has no passive split, since the candidate is always the same person.
- **Not built:** `?include_near_misses=true` to see them anyway, and `?min_score=`.

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
