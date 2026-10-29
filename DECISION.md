# Decision log

One line per decision: what we chose, what it replaced, and why. The code refers to these numbers (D-xx).

## 1. Reading the data

- **D-01** Broken words such as `pattern-recog nition` are fixed by hand in the seed, because they're PDF line-break artifacts, not real skills.
- **D-02** Every term is normalized (lowercase, hyphenated), because `stakeholder management` has to match `stakeholder-management`.
- **D-03** Ingestion only cleans terms; synonyms live in matching (later the taxonomy, D-30), so changing a synonym never needs a re-ingest.
- **D-04** Identity was the name slug → replaced by D-53, because names aren't unique.
- **D-05** Availability is stored as `open_to_opportunities` plus a real start date, so "2 weeks" stays correct over time.
- **D-06** Quirks and taglines are shown, never scored: they're free-text jokes, and their structured form (traits, culture keywords) is already scored.
- **D-07** Experience means total career years, because the data has no years per skill.

## 2. Requirements

- **D-08** A job's skills count as coverage, not all-or-nothing, because no candidate has all three Engineering Manager skills.
- **D-09** Candidate preferences weren't modelled at first → collected later (D-47), because the data had none.
- **D-47** Job preferences are stored but not scored, because they can't be backfilled later. The job title isn't scored either: candidates have no title to compare it with.
- **D-10** Candidates who aren't looking are kept, not hidden → built as proactive offers (D-49), because the brief's Michael Scott is "Not looking".

## 3. Scoring

- **D-11** Each factor is scored separately, then weighted (first 60 skills / 20 experience / 10 availability / 10 culture), so each part can be tested on its own.
- **D-28** Engine v1 used 80 skills / 20 experience, the two factors the brief requires → replaced by D-32.
- **D-32** One pure scorer for both directions, with credit passed in: **70 skills / 20 experience / 10 culture**. Availability moved to tie-breaking, and one-sided signals stay out of the shared score.
- **D-12** No skill overlap means no match; otherwise experience alone could score 40.
- **D-13** Extra years earn nothing extra, because 15 years isn't a better fit than 8 for a job asking for 3.
- **D-14** Exact skill names only → replaced by the taxonomy (D-29), because related skills deserve partial credit.
- **D-15** One score per pair, shared by both endpoints, so they can never disagree.
- **D-16** Ties break by score, then earliest start, then a neutral hash. It used to fall back to skill score, then name: alphabetical order always favours the same people, and years would favour older people.
- **D-17** 50 counts as a match. Near misses (at most 3) are shown only when nothing reaches 50, because an empty list gives a recruiter nothing.
- **D-18** The reason is built from the score breakdown, so it can never contradict the score.
- **D-34** Tiers: strong ≥ 70, possible ≥ 50, near miss < 50, because a recruiter acts on a label, not a raw number.
- **D-48** The weights were checked by a sensitivity analysis: no ±0.10 change flips a job's winner. With no outcome data, robustness is the best evidence available.
- **D-52** The best skill pairing is found by the Hungarian algorithm (it used to try every combination), because 10 skills took 109 s. Now it takes 0.3 ms, with identical results.
- **D-56** Minimum experience is set per job: `required` (the default; below it means no match) or `preferred` (below it means at most possible). A candidate with every skill and 0 of 8 years was labelled "strong".

## 4. Storage and API

- **D-19** Raw, hand-written SQL only, with numbered migration files, as the brief requires.
- **D-20** Skills sit in normalized link tables, so overlap is computed with joins.
- **D-21** Matches are stored, not computed on read: reads stay simple and every score can be audited.
- **D-22** The seed loads on startup, and the POST endpoints reuse the same code, so there's one path for all input.
- **D-23** PostgreSQL in Docker Compose, for real constraints and a one-command start.
- **D-24** Python, psycopg 3 and pydantic, because none of them generate SQL.
- **D-25** Ingestion is extract → batch → one transaction, and bad records are rejected with a reason, so one bad row doesn't block the rest.
- **D-26** Lookups use a compact key (the slug without hyphens), which catches `team-building` vs `teambuilding`. Fuzzy matching was rejected because it linked the wrong skills.
- **D-27** A single similarity hook → replaced by D-32's credit source.
- **D-33** FastAPI with sync handlers: validation and `/docs` come free, and async adds nothing at this size.
- **D-35** `POST /candidates` returns the new candidate's matches, with 409 on a clash, so nobody is overwritten silently.
- **D-36** `GET /candidates` and `GET /jobs` list ids, because ids aren't predictable.
- **D-37** Matches are refreshed in the same transaction as each write, and versioned, so they're never stale or mixed.
- **D-38** `PATCH` makes partial updates, so edits go through the API, not the seed.
- **D-39** The seed only inserts new records (it used to upsert), because re-seeding overwrote edits and pushed Hermione's start date out by a day each run.
- **D-40** `POST /jobs` mirrors `POST /candidates`.
- **D-46** One command runs migrations, then the seed, then the API in Docker. The 12 migrations were merged into one file before release, because several undid earlier ones.
- **D-49** The recruiter's view has `matches` (open candidates) and `proactive_offers` (not looking, but better than every open candidate), because "who can I hire?" and "who should I approach?" are different questions.
- **D-50** Every match has a rank and evidence (what matched, what's missing); the full points appear only with `?explain=true`, because a recruiter acts on what's missing, not on 46.7 points.
- **D-51** A candidate's jobs are ordered by score, then top applicant, then newest posting, then hash. They used to be ordered by preference and share of rivals beaten; now the order uses only what the candidate sees.
- **D-53** Identity is an optional email for candidates, and company plus title for jobs (it used to be the name), because two real people can share a name.

## 5. Words the taxonomy doesn't know

- **D-29** An ESCO-shaped taxonomy, not embeddings: same concept 1.0, related 0.5, because embeddings score opposites as similar.
- **D-30** The taxonomy loads from `seed/taxonomy.json`, validated and all-or-nothing, because a typo in configuration would silently change scores.
- **D-31** Unknown words first earned nothing, only hints, because linking had to be measured before it could be trusted.
- **D-41** Rules come first: negation, word roots, per-word typos and grouping, because a wrong link is worse than a missing one.
- **D-42** Two small local ONNX models, judged on 116 hand-labelled words: no GPU, no API key, and measured rather than assumed.
- **D-43** Embeddings propose the 10 closest concepts; descriptions written as short sentences found the right concept 95% of the time.
- **D-44** An NLI model checks both directions, which catches opposites that similarity misses.
- **D-45** Automatic linking was switched off: 67% precision on held-out words, against a 98% target.
- **D-54** The models came back with capped ¼ "suggested" credit, off by default, to match their measured reliability. A guess never creates a match on its own.
- **D-55** Real ESCO labels (from 3 synonyms to 236) plus approve and reject endpoints: a person decides once, and the system keeps it. On independent ESCO data, the model's automatic guesses were right 56% of the time.

## Out of scope

Authentication, a UI, ML or LLM scoring, résumé parsing, and matching on salary, location or work authorization.
