# Decision log

One line per decision: what we chose, what it replaced, and why.

## 1. Reading the data

- Broken words such as `pattern-recog nition` are fixed by hand in the seed, because they're PDF line-break artifacts, not real skills.
- Every term is normalized (lowercase, hyphenated), because `stakeholder management` has to match `stakeholder-management`.
- Ingestion only cleans terms; synonyms live in matching (later the taxonomy), so changing a synonym never needs a re-ingest.
- Identity was the name slug → later an optional email, or company plus title, because names aren't unique.
- Availability is stored as `open_to_opportunities` plus a real start date, so "2 weeks" stays correct over time.
- Quirks and taglines are shown, never scored: they're free-text jokes, and their structured form (traits, culture keywords) is already scored.
- Experience means total career years, because the data has no years per skill.

## 2. Requirements

- A job's skills count as coverage, not all-or-nothing, because no candidate has all three Engineering Manager skills.
- Candidate preferences weren't modelled at first → collected later, because the data had none.
- Job preferences are stored but not scored, because they can't be backfilled later. The job title isn't scored either: candidates have no title to compare it with.
- Candidates who aren't looking are kept, not hidden → later built as proactive offers, because the brief's Michael Scott is "Not looking".

## 3. Scoring

- Each factor is scored separately, then weighted (first 60 skills / 20 experience / 10 availability / 10 culture), so each part can be tested on its own.
- Engine v1 used 80 skills / 20 experience, the two factors the brief requires → replaced by the 70/20/10 scorer below.
- One pure scorer for both directions, with credit passed in: **70 skills / 20 experience / 10 culture**. Availability moved to tie-breaking, and one-sided signals stay out of the shared score.
- No skill overlap means no match; otherwise experience alone could score 40.
- Extra years earn nothing extra, because 15 years isn't a better fit than 8 for a job asking for 3.
- Exact skill names only → replaced by the taxonomy, because related skills deserve partial credit.
- One score per pair, shared by both endpoints, so they can never disagree.
- Ties break by score, then earliest start, then a neutral hash. It used to fall back to skill score, then name: alphabetical order always favours the same people, and years would favour older people.
- 50 counts as a match. Near misses (at most 3) are shown only when nothing reaches 50, because an empty list gives a recruiter nothing.
- The reason is built from the score breakdown, so it can never contradict the score.
- Tiers: strong ≥ 70, possible ≥ 50, near miss < 50, because a recruiter acts on a label, not a raw number.
- The weights were checked by a sensitivity analysis: no ±0.10 change flips a job's winner. With no outcome data, robustness is the best evidence available.
- The best skill pairing is found by the Hungarian algorithm (it used to try every combination), because 10 skills took 109 s. Now it takes 0.3 ms, with identical results.
- Minimum experience is set per job: `required` (the default; below it means no match) or `preferred` (below it means at most possible). A candidate with every skill and 0 of 8 years was labelled "strong".

## 4. Storage and API

- Raw, hand-written SQL only, with numbered migration files, as the brief requires.
- Skills sit in normalized link tables, so overlap is computed with joins.
- Matches are stored, not computed on read: reads stay simple and every score can be audited.
- The seed loads on startup, and the POST endpoints reuse the same code, so there's one path for all input.
- PostgreSQL in Docker Compose, for real constraints and a one-command start.
- Python, psycopg 3 and pydantic, because none of them generate SQL.
- Ingestion is extract → batch → one transaction, and bad records are rejected with a reason, so one bad row doesn't block the rest.
- Lookups use a compact key (the slug without hyphens), which catches `team-building` vs `teambuilding`. Fuzzy matching was rejected because it linked the wrong skills.
- A single similarity hook → replaced by a credit source passed into the scorer.
- FastAPI with sync handlers: validation and `/docs` come free, and async adds nothing at this size.
- `POST /candidates` returns the new candidate's matches, with 409 on a clash, so nobody is overwritten silently.
- `GET /candidates` and `GET /jobs` list ids, because ids aren't predictable.
- Matches are refreshed in the same transaction as each write, and versioned, so they're never stale or mixed.
- `PATCH` makes partial updates, so edits go through the API, not the seed.
- The seed only inserts new records (it used to upsert), because re-seeding overwrote edits and pushed Hermione's start date out by a day each run.
- `POST /jobs` mirrors `POST /candidates`.
- One command runs migrations, then the seed, then the API in Docker. The 12 migrations were merged into one file before release, because several undid earlier ones.
- The recruiter's view has `matches` (open candidates) and `proactive_offers` (not looking, but better than every open candidate), because "who can I hire?" and "who should I approach?" are different questions.
- Every match has a rank and evidence (what matched, what's missing); the full points appear only with `?explain=true`, because a recruiter acts on what's missing, not on 46.7 points.
- A candidate's jobs are ordered by score, then top applicant, then newest posting, then hash. They used to be ordered by preference and share of rivals beaten; now the order uses only what the candidate sees.
- Identity is an optional email for candidates, and company plus title for jobs (it used to be the name), because two real people can share a name.

## 5. Words the taxonomy doesn't know

- An ESCO-shaped taxonomy, not embeddings: same concept 1.0, related 0.5, because embeddings score opposites as similar.
- The taxonomy loads from `seed/taxonomy.json`, validated and all-or-nothing, because a typo in configuration would silently change scores.
- Unknown words first earned nothing, only hints, because linking had to be measured before it could be trusted.
- Rules come first: negation, word roots, per-word typos and grouping, because a wrong link is worse than a missing one.
- Two small local ONNX models, judged on 116 hand-labelled words: no GPU, no API key, and measured rather than assumed.
- Embeddings propose the 10 closest concepts; descriptions written as short sentences found the right concept 95% of the time.
- An NLI model checks both directions, which catches opposites that similarity misses.
- Automatic linking was switched off: 67% precision on held-out words, against a 98% target.
- The models came back with capped ¼ "suggested" credit, off by default, to match their measured reliability. A guess never creates a match on its own.
- Real ESCO labels (from 3 synonyms to 236) plus approve and reject endpoints: a person decides once, and the system keeps it. On independent ESCO data, the model's automatic guesses were right 56% of the time.

## Out of scope

Authentication, a UI, ML or LLM scoring, résumé parsing, and matching on salary, location or work authorization.
