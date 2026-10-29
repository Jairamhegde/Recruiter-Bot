# Recruiter Bot

Ranks candidates for a job, and jobs for a candidate. Every match has a score, a tier and a reason that says exactly **what matched and what is missing**. Built with Python, FastAPI and PostgreSQL, using **raw, hand-written SQL only** (psycopg 3, no ORM or query builder).

**New here? Start with [how it works, in one picture](docs/ER_DIAGRAM_AND_ARCHITECTURE.md).**

## Run it locally

You need only **Docker Desktop**, running.

```bash
git clone https://github.com/Jairamhegde/Recruiter-Bot.git
cd Recruiter-Bot
docker compose up --build
```

When the terminal shows `Recruiter Bot is ready: open http://127.0.0.1:8000/docs in your browser`, open that address to try every endpoint. Don't use the `http://0.0.0.0:8000` line Uvicorn prints after it: that address only works inside the container. On startup the app creates the schema, loads the 15 candidates and 6 jobs, and computes every match.

```bash
curl http://127.0.0.1:8000/jobs/6/matches           # ranked candidates for a job
curl http://127.0.0.1:8000/candidates/7/matches     # ranked jobs for a candidate
curl "http://127.0.0.1:8000/jobs/6/matches?explain=true"   # plus the score arithmetic
```

**See it work, with evidence:** [docs/DEMO.md](docs/DEMO.md) has one job and eight sample candidates, each showing one matching rule (synonyms, one skill per requirement, the experience gate and its 1-year grace, proactive offers, tie-breaks), how to run them, and what to look for in the results.

On Windows, type `curl.exe`. To reset the data, run `docker compose down -v`. If port 8000 is taken, run `API_PORT=8001 docker compose up --build`.

**Ingestion:** the seed loads on startup, and `POST /candidates` and `POST /jobs` use the same code. `PATCH` endpoints edit a record. Every write refreshes its matches in the same transaction. The full API is in [docs/API.md](docs/API.md).

## Part 2: SQL Detective

The answers are in [`SQL_DETECTIVE/SQL_DETECTIVE_CHALLENGE.sql`](SQL_DETECTIVE/SQL_DETECTIVE_CHALLENGE.sql): the brief's schema and data loaded as-is, then one query per question. Run the whole file and print every answer with:

```bash
docker compose run --rm sql-detective
```

It starts only the database if it isn't running, and stops at the first error. The file creates its own `sql_detective` schema and rebuilds its tables on every run, so it never touches the app's data and can be run any number of times.

## Code map

| File | What it does |
|---|---|
| [`migrations/001_init.sql`](migrations/001_init.sql) | The schema: hand-written DDL |
| [`recruiter_bot/ingest.py`](recruiter_bot/ingest.py) | Validates and normalizes input, then stores or updates it |
| [`recruiter_bot/taxonomy.py`](recruiter_bot/taxonomy.py) | Loads the taxonomy, maps every word to its concept, and says how much one word earns toward another |
| [`recruiter_bot/matching/scorer.py`](recruiter_bot/matching/scorer.py) | **The matching algorithm:** one candidate, one job, one score. Pure, no database. |
| [`recruiter_bot/matching/assignment.py`](recruiter_bot/matching/assignment.py) | The Hungarian algorithm: the best one-to-one pairing of a candidate's skills to a job's |
| [`recruiter_bot/matching/store.py`](recruiter_bot/matching/store.py) | Recomputes, stores and reads matches |
| [`recruiter_bot/matching/views.py`](recruiter_bot/matching/views.py) | Tiers, proactive offers, ordering and evidence |
| [`recruiter_bot/api/`](recruiter_bot/api) | The HTTP endpoints |
| [`recruiter_bot/seed.py`](recruiter_bot/seed.py), [`migrate.py`](recruiter_bot/migrate.py) | Startup: apply the schema, load `seed/*.json`, compute matches |

---

## How matching works

### 1. Every word is mapped to its meaning first, then compared by meaning

Skills, traits and culture keywords are normalized (`Stakeholder Management` → `stakeholder-management`), then mapped to a **concept**: the base meaning a word names. The concepts live in one taxonomy, [`seed/taxonomy.json`](seed/taxonomy.json), shaped like [ESCO](https://esco.ec.europa.eu), the EU's skills classification, and the W3C SKOS model it uses:

- **`concepts`**: one row per base meaning, e.g. the trait `resilience`.
- **`concept_labels`**: every word for it, including its own name: `resilience`, `resilient`, `cope-with-pressures`. A word can mean only one concept, even spelled with or without hyphens; the database enforces it.
- **`concept_relations`**: concepts that are close but not the same, e.g. `resilience` ≈ `stress-tolerance`. Stored in both directions.

Every stored skill and trait word keeps the concept it means (`skills.concept_id`, `traits.concept_id`). It's looked up once, when the word is first stored, and again whenever the taxonomy is reloaded. Matching then compares concepts, so synonyms match whichever side uses which word:

| Candidate word vs job word | Credit | Example |
|---|---|---|
| Same word, or same concept | 1.0 | `tenacious` = `persistent`; `resilience` = `cope-with-pressures` |
| Related concepts | 0.5 | `persuasion` ≈ `negotiation` |
| Anything else, including a word with no concept | 0 | |

The taxonomy is kept deliberately small (17 concepts) to show how it works: these are the concepts that change a score in the seed data. Growing it means adding concepts and labels to the file; no code changes.

**Each candidate skill covers at most one requirement,** so one `persuasion` can't count for both `sales` and `negotiation`. Finding the pairing that earns the most credit is the classic **assignment problem**, solved exactly by the **Hungarian algorithm** in O(n³). A first brute-force version took 109 seconds at 10 skills; this takes under a millisecond at 50. A test checks it against brute force on 500 random cases.

### 2. Three factors, one score

```
score = 100 × (0.7 × skills + 0.2 × experience + 0.1 × culture)
```

- **skills** = credit earned ÷ skills the job lists. This is coverage, not all-or-nothing: 2 of 3 earns ⅔.
- **experience** = 1 when years ≥ the minimum, and years ÷ minimum below it (3 of 4 years earns 0.75). Extra years earn nothing extra, and being over-qualified is never penalized.
- **culture** = credit earned ÷ culture keywords the job lists, matched against the candidate's traits.

**Why 70 / 20 / 10:** skills and experience are the two factors the brief requires. Skills carry most of the weight because they're what the job actually needs done. Experience earns its 20 points in full at the minimum and in proportion just below it; it doesn't separate people above the minimum, by design, because extra years aren't extra fit. Culture is a soft signal, worth only enough to separate otherwise equal candidates. Availability isn't in the score at all; it breaks ties instead.

**Two gates come before the score:**
- **No skill overlap means no match.** Otherwise experience and culture alone could score 30.
- **More than 1 year below the job's minimum experience means no match.** Up to 1 year short still counts, so a minimum isn't a cliff where 3 years is nothing and 4 is everything. That candidate's score drops in proportion, the match is at most "possible", and the reason says so: `3y vs 4y min (1y short)`. A job can relax the rule entirely with `experience_requirement: "preferred"`: then any shortfall is scored in proportion, still capped at "possible".

**Worked example:** Sherlock for Backend Detective = 100 × (0.7 × 3/3 + 0.2 × 1 + 0.1 × 1/2) = **95.0**.

### 3. Tiers and the recruiter's view

`strong_match` ≥ 70, `possible_match` ≥ 50, `near_miss` < 50. **Near misses appear only when nobody reaches 50** (at most 3), so they explain a gap instead of cluttering real matches.

A job's response has two sections:
- **`matches`:** candidates who are open to opportunities.
- **`proactive_offers`:** candidates who are *not* looking but fit better than every open candidate. That's exactly when an approach is worth the effort.

`GET /jobs/6/matches` (Sales Engineer), shortened:

```json
"possible_match":   [{ "rank": 1, "candidate_name": "Dwight S.", "score": 66.7,
                       "reason": "2/3 skills (negotiation, sales) · missing public-speaking · 9y vs 3y min · culture 0/2" }],
"proactive_offers": [{ "rank": 1, "candidate_name": "Michael S.", "score": 71.7, "tier": "strong_match",
                       "reason": "2/3 skills (public-speaking, sales) · missing negotiation · 11y vs 3y min · culture 1/2 (enthusiastic)" }]
```

Every entry also has an `evidence` block listing matched and missing skills and culture. `?explain=true` adds the points per factor, which add up to the score.

**Quirks and taglines are shown, never scored.** They're free text, and mostly jokes ("Says nothing. Everyone panics."). Their structured form, traits and culture keywords, is already scored. So the recruiter sees the candidate's `quirk`, and the candidate sees the job's `tagline`.

### 4. Ordering and ties

**Candidates for a job:**
1. Tier: strong before possible, so a candidate below the minimum experience never outranks a strong match.
2. Total score.
3. Earliest available date. A date in the past counts as today.
4. A neutral hash of the job and candidate ids. The order is the same every time and favours no one; names are never used.

**Jobs for a candidate:**
1. Tier: a job the candidate fully qualifies for ranks above one they're a year short for, even if that one scores higher.
2. Score.
3. `top_applicant`: jobs where no competing open candidate scores higher come first, because that's where the candidate's chance is best. It's shown as a yes or no, never as a count, so other people's scores stay private.
4. Most recent posting, since older ads are more likely to be filled already.
5. The neutral hash.

**One score serves both directions:** a pair always has the same score in the recruiter's view and in the candidate's.

---

## Decisions and trade-offs

The key choices are below. **Every decision, with what it replaced and why, is in [docs/DECISION.md](docs/DECISION.md).**

**Coverage over all-or-nothing skills.** Jobs don't mark any skill as optional, so every listed skill counts equally. But no candidate has all three Engineering Manager skills, so a strict rule would leave that job empty. Coverage ranks Miranda (2 of 3) and Ted sensibly instead.

**A taxonomy, not machine learning, decides skill overlap.** A score built from explicit concepts can be explained: the reason names the source of every partial credit (`sales ≈ persuasion ½`), and a recruiter can check it. I tried embedding models for unknown words and measured them: they placed opposites close together (`calm` nearer `anxious` than `level headed`) and couldn't tell "same" from "related". A wrong link is silent and changes every score that uses the word, so I left models out.

**"Not looking" doesn't mean "don't contact".** The brief says Michael Scott is applying for Sales Engineer, but his data says "Not looking". Hiding him would lose the best fit, and listing him as available would mislead. So he appears under `proactive_offers`.

**Experience is a gate with a 1-year grace, not a tie-breaker.** A stated minimum is treated as a requirement: before the gate, a candidate with every skill and 0 of 8 years was labelled a strong match, because 20 points can't outweigh 70. But a hard cutoff is a cliff: 3 years for a 4-year job would vanish while 4 years earns full marks, and recruiters often consider someone a year short. So up to 1 year short is shown, scored in proportion, capped at "possible" and flagged; further below is no match. Above the minimum, more years earn nothing: 15 years isn't a better fit than 8 for a job asking for 3. Preferring more years would also track age, which is a discrimination risk.

**Stored, not computed on read.** Matches are stored and refreshed in the same transaction as every write, so reads are one query and never stale. The cost is that a new job is scored against every candidate on write, which is fine at this size; at scale I'd only rescore candidates that share a skill with it.

**Job titles aren't scored,** because candidates have no title or desired role to compare them with, and a title's meaning already comes through its required skills.

**Limitations.** Six jobs and no outcome data: there is nothing to learn weights from, so the weights are a reasoned choice, not a measured one. Names aren't unique, so the same person posted twice through the API is stored twice. Words the taxonomy doesn't know only match when spelled the same.

**Kept out on purpose.** An earlier version had local ML models for unknown words, a reviewer approval queue, a weight-sensitivity report and an ingestion log. They're beyond what the brief asks, so they live on the [`extended`](../../tree/extended) branch, not here.

---

## Tests

`tests/test_matching.py` has 28 tests:
- **Scoring, ordering and input rules (12, no database needed):** the 70/20/10 formula; full marks for over-qualified candidates; proportional experience credit; 1 year short of a required minimum is at most a possible match and flagged, more than 1 year short is no match; no skill overlap means no match; half credit for related skills, named in the reason; one skill can't cover two requirements; the exact 50 and 70 tier boundaries; a candidate's tied jobs ordered by top applicant, then newest posting; PATCH refuses typos and cleared required fields; the Hungarian pairing always earns the brute-force maximum, on 500 random cases.
- **End to end (16, against a throwaway database built from the real migration and seed):** ranking in both directions; the same score both ways; stored matches equal a fresh calculation; ties go to whoever can start first; proactive offers appear only when deserved; near misses appear only when nothing better exists; taxonomy synonyms and related words; PATCH changes only what was sent and refreshes the matches; PATCH of a missing record changes nothing; a concept's own name matches its other words in both directions; an unknown word matches only its own spelling; every known seed word is linked to its concept; the database refuses a spelling that would mean two concepts; running the seed again adds nothing.

```bash
docker compose up -d db
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt -r requirements-dev.txt   # macOS/Linux: .venv/bin/python
.venv/Scripts/python -m pytest -q
```

## Use of AI tools

I used Claude (Anthropic) as an assistant for:
- **Exploring ideas:** examining my own design ideas from more angles before settling on one.
- **Implementation:** turning my designs into code, and refactoring it. Every change was reviewed by me.
- **Tests and debugging:** writing tests, and tracking down bugs.
- **Documentation and reference:** drafting docs, and checking details of psycopg 3, FastAPI and PostgreSQL.

---

**More detail:** [Architecture and ER diagrams](docs/ER_DIAGRAM_AND_ARCHITECTURE.md) ([conceptual](docs/er_diagram_chen.png), [tables](docs/er_diagram.png)) · [API reference](docs/API.md) · [Design decisions](docs/DECISION.md) · [SQL Detective answers](SQL_DETECTIVE/SQL_DETECTIVE_CHALLENGE.sql)
