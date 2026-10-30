# Decision log

One line per decision: what was chosen, and why. Where an earlier version did it differently, that's said too.

## 1. Reading the data

- Broken words such as `pattern-recog nition` are fixed by hand in the seed, because they're PDF line-break artifacts, not real skills.
- Every term is normalized (lowercase, hyphenated), because `Stakeholder Management` has to match `stakeholder-management`.
- Availability is stored as `open_to_opportunities` plus a real start date, so "2 weeks" stays correct over time.
- Experience means total career years, because the data has no years per skill.
- Quirks and taglines are shown, never scored: they're free-text jokes, and their structured form (traits, culture keywords) is already scored.

## 2. Identity

- A record's identity is its surrogate id (`candidate_id`, `job_id`). Nothing is identified by name: two people can share a name, and both are stored.
- No combination of the brief's fields identifies a person (name, skills and years can all repeat), so a composite natural key would be just as fragile as a name. A real identity needs a real identifier, such as an email or an ID from an applicant-tracking system; the brief's data has none, so none is invented.
- Re-running the seed must not duplicate records. Each seed file is therefore loaded once, like a migration, and recorded in `seed_runs`. An earlier version keyed each seed record by its name instead, which dropped the second of two same-named people and needed meaningless filler keys for API records.
- The same person posted twice through the API is stored twice. That's a known limitation until there's a real identifier.

## 3. Matching

- One pure scorer for both directions: **70 skills / 20 experience / 10 culture**. Skills and experience are the two factors the brief requires; culture separates otherwise equal candidates. Availability breaks ties instead of being scored.
- A job's skills count as coverage, not all-or-nothing, because no candidate has all three Engineering Manager skills.
- No skill overlap means no match; otherwise experience alone could score 20.
- More than 1 year below a required minimum of experience means no match. Up to 1 year short is scored in proportion, capped at a possible match, and flagged in the reason (`1y short`). An earlier version excluded anyone below the minimum, which made it a cliff (3 of 4 years scored nothing, 4 of 4 full marks) and left the 20% experience weight unable to change any match. No gate at all was worse: 20 points can't outweigh 70, so every skill and 0 of 8 years was a strong match. Above the minimum, extra years earn nothing: 15 years isn't a better fit than 8 for a job asking for 3, and rewarding years would mostly reward age. A job can mark its minimum `preferred`, which scores any shortfall proportionally instead of excluding.
- Each candidate skill covers at most one requirement, so one `persuasion` can't count for both `sales` and `negotiation`. The best pairing is the assignment problem, solved by the Hungarian algorithm in O(n³). A first brute-force version took 109 s at 10 skills; Hungarian takes 0.23 ms at 50. A test checks it against brute force on 500 random cases.
- The score is shared by both endpoints, so the recruiter's and the candidate's views can never disagree.
- The reason is built from the score's own parts, so it can never contradict the score.
- Tiers: strong ≥ 70, possible ≥ 50, near miss < 50, because a recruiter acts on a label, not a raw number. Near misses (at most 3) are shown only when nothing reaches 50.
- Candidates who aren't looking are kept, as proactive offers when they beat every open candidate, because the brief's Michael Scott is "Not looking".
- Ties break by earliest start, then a neutral hash of the ids. Names are never used: alphabetical order always favours the same people.
- Both views put strong matches before possible ones, so a match capped for missing experience never outranks one that fully qualifies. Within a tier, a candidate's jobs are ordered by score, then where they're the top applicant, then the newest posting. `top_applicant` is a yes or no, so other candidates' scores stay private.
- Job titles aren't scored: candidates have no title to compare them with, and a title's meaning already comes through its skills.

## 4. Meaning of words (taxonomy)

- Words are compared by meaning through a small taxonomy shaped like ESCO and the W3C SKOS model: concepts, the labels that name them, and related concepts. Same word or concept earns 1.0, related concepts 0.5.
- Each skill and trait word stores the concept it means (`skills.concept_id`, `traits.concept_id`), looked up once when the word is stored and again on every taxonomy reload, in the same transaction. The concept sits on the word, not on each candidate's link row, because a word's meaning doesn't depend on who uses it.
- A concept's own name is one of its labels, so `resilience` matches `cope-with-pressures`.
- One meaning per spelling, hyphens ignored, is a database constraint (a generated, unique `compact_label`), so `team-building` and `teambuilding` can't name two concepts.
- The taxonomy holds the 17 concepts that change a seed score. It grows by editing `seed/taxonomy.json`; no code changes.
- A word the taxonomy doesn't know matches only its own spelling. A wrong link would change every score that uses the word without anyone noticing, so no meaning is guessed.
- Local language models for unknown words were built and measured: they were right only 56–67% of the time. They're kept on the `extended` branch, not here.

## 5. Storage and API

- PostgreSQL with raw, hand-written SQL only (psycopg 3), as the brief requires. Python and pydantic, because neither generates SQL.
- Skills and traits sit in normalized link tables, so overlap is computed with joins.
- Matches are stored, not computed on read, and refreshed in the same transaction as every write, so reads are one query and never stale.
- The seed and the POST endpoints share one code path. Input is validated by the pydantic models before any write; a bad seed record is reported and skipped.
- PATCH changes only the fields sent, with one fixed UPDATE per table (no SQL built at run time), and refreshes that record's matches.
- `GET /candidates` and `GET /jobs` list ids, because ids aren't predictable.
- Every match has evidence (what matched, what's missing); the score arithmetic appears only with `?explain=true`.
- One command starts everything in Docker: migrations, then the seed, then the API. `docker compose run --rm sql-detective` runs Part 2.
- A demo page at `/ui` (an extension: the brief asks for no frontend). One static file in `frontend/`, served by the same API, so it needs no CORS, no build step and no extra container. It only calls the public endpoints (including the `GET /jobs` and `GET /candidates` lists) and does no scoring of its own, so it can't disagree with the API.

## Out of scope

Authentication, a full UI (beyond the demo page), résumé parsing, and matching on salary, location or work authorization.
