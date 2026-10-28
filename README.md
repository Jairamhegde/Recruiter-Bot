# Recruiter Bot

A backend that ingests candidate profiles and job openings and ranks the best matches in both directions, each with a score and a reason you can check by hand.

Python 3.11+, PostgreSQL 16, psycopg 3 with hand-written SQL only, and FastAPI. Every decision below is logged with its reasoning in [DECISION.md](DECISION.md) (`D-xx` numbers refer to it).

---

## Assumptions and ambiguity

The brief leaves gaps on purpose. Each was resolved explicitly, and the choice is written down.

| Ambiguity | Decision |
|---|---|
| `pattern-recog nition`, `public-speaki ng` in the source | PDF line-break artifacts, corrected in the seed (D-01) |
| `stakeholder management` vs `stakeholder-management` | All terms are normalized: lowercase, hyphenated (D-02) |
| Does "required skills" mean all of them? | No: it's coverage. Nobody has all three skills for Engineering Manager, so all-or-nothing would leave that job empty (D-08) |
| What does "experience" measure? | Total career years; the data gives no years per skill (D-07). Exceeding the minimum isn't penalized (D-13) |
| **Michael Scott is "applying" in the brief, but "Not looking" in the data** | "Not looking" means not actively looking, not "do not contact". Passive candidates stay in the results; availability never lowers the fit score and only breaks ties (D-10, D-16) |
| "2 weeks" from when? | Stored as a date, counted from the first load, and never recalculated on a re-seed (D-05, D-39) |
| `loyalty`, `optimism`, `precision`… listed as skills | They describe personality, so the taxonomy has no skill concepts for them, and the seed run reports them (D-30) |
| `fast-paced` as a culture keyword | It describes the job, not a person, so it only matches exactly (D-29) |
| Quirks and taglines | Free text, so not scored (D-06) |
| Candidate preferences | The data has none, so they aren't modeled (D-09) |
| Identity of a record | No email in the data, so the normalized name is the key. A duplicate name returns 409, never an overwrite (D-04, D-35) |
| A word the taxonomy doesn't know | No credit and no penalty; each seed run lists it, with review hints (D-31) |

---

## Trade-offs

| Decision | Gain | Cost |
|---|---|---|
| Curated taxonomy, not runtime embeddings (D-29) | Deterministic, explainable, no opposites scored as matches | Synonyms nobody has curated get no credit |
| Pure scoring function with injected credit (D-32) | Both directions agree; testable without a database | Direction-specific signals have to live in the rankers |
| Exact one-to-one assignment (D-32) | No double-counting of one skill | More code than a simple overlap count |
| Weights 70 / 20 / 10 (D-32) | The two required factors dominate; culture only refines | The weights are judgment calls, not learned from hiring outcomes |
| Availability outside the score (D-16) | The best fit stays first; stored scores don't go stale as dates pass | Availability only matters when scores tie |
| Matches stored and refreshed in the same transaction as each write, with a version check (D-37) | Reads are one indexed query and can't serve stale scores | Every write recomputes against the whole other side, fine at this size, a background job at scale |
| Seed inserts new records only (D-39) | API edits survive, availability dates don't drift | Editing an existing record in the seed file has no effect after the first load |

---

## API

| Method | Path | What it does |
|---|---|---|
| `GET` | `/jobs` | Every job with its id |
| `GET` | `/jobs/{id}/matches` | **Ranked candidates for a job** (required by the brief) |
| `POST` | `/jobs` | Store a new job; returns its matches |
| `PATCH` | `/jobs/{id}` | Change some of a job's fields; returns its refreshed matches |
| `GET` | `/candidates` | Every candidate with its id |
| `GET` | `/candidates/{id}/matches` | **Ranked jobs for a candidate** (required by the brief) |
| `POST` | `/candidates` | Store a new candidate; returns their matches |
| `PATCH` | `/candidates/{id}` | Change some of a candidate's fields; returns their refreshed matches |

Ids follow insertion order, so look them up with `GET /jobs` or `GET /candidates` first.

### Ranked candidates for a job

```bash
curl http://127.0.0.1:8000/jobs/5/matches
```

```json
{
  "job_id": 5,
  "matches": {
    "strong_match": [
      { "candidate_id": 12, "candidate_name": "Olivia P.", "score": 95.0,
        "skill_score": 1.0, "experience_score": 1.0, "culture_score": 0.5,
        "matched_skills": ["crisis-management", "negotiation", "strategy"], "missing_skills": [],
        "reason": "3/3 skills (crisis-management, negotiation, strategy) · 13y vs 4y min · culture 1/2 (decisive)" },
      { "candidate_id": 10, "candidate_name": "Katniss E.", "score": 74.2,
        "reason": "2/3 skills (crisis-management, strategy) · missing negotiation · 5y vs 4y min · culture 1.5/2 (calm-under-pressure ≈ resilient ½, decisive)" }
    ],
    "possible_match": [],
    "near_miss": [
      { "candidate_name": "Miranda P.", "score": 48.3,
        "reason": "1/3 skills (negotiation) · missing crisis-management, strategy · 18y vs 4y min · culture 1/2 (decisive)" }
    ]
  }
}
```
*(Shortened: every entry carries the full set of fields shown for Olivia.)*

### Ranked jobs for a candidate

```bash
curl http://127.0.0.1:8000/candidates/7/matches
```
Elle W. gets Developer Relations Lead (90.0, `strong_match`), Sales Engineer (55.0, `possible_match`) and Incident Commander (26.7, `near_miss`), in the same shape.

### Add or change a record

```bash
curl -X POST http://127.0.0.1:8000/candidates -H "Content-Type: application/json" \
  -d '{"name": "Jordan", "skills": ["Crisis Management", "Strategy", "Persuasion"],
       "experience_years": 6, "availability": "2 weeks", "traits": ["Calm", "Decisive"]}'

curl -X PATCH http://127.0.0.1:8000/jobs/6 -H "Content-Type: application/json" \
  -d '{"min_experience_years": 4}'
```

| Status | When |
|---|---|
| `201` / `200` | Created / updated; the body is the record's matches |
| `404` | Unknown id |
| `409` | The name or title already belongs to another record |
| `422` | Invalid input, such as no skills or `"availability": "someday"` |

---

## How matching works

### 1. Skill credit, from an ESCO-shaped taxonomy (D-29, D-30)

Exact string matching misses synonyms, and embeddings rate opposites as similar (`chaotic` vs `organized`). So skills and traits are matched through a small taxonomy in the shape of [ESCO](https://esco.ec.europa.eu): each concept has a preferred label, alternative labels (synonyms) and hidden labels (misspellings). It is filled with our own data: 51 concepts and 11 curated relations, in [`seed/taxonomy.json`](seed/taxonomy.json).

| Candidate term vs job term | Credit | Example |
|---|---|---|
| Same term | 1.0 | `sales` / `sales` |
| Same concept (synonym) | 1.0 | `tenacious` / `persistent` |
| Related concept | 0.5 | `persuasion` / `negotiation` |
| Reviewed as unrelated | 0 | `project-management` / `crisis-management` |
| Anything else | 0 | |

### 2. Coverage, one-to-one (D-32)

For each part, skills and culture:

```
coverage = credit earned ÷ number of terms the job lists
```

Each candidate term covers at most one requirement, so one `persuasion` can't earn half of both `sales` and `negotiation`. The best assignment is found exactly, not greedily. Extra skills the candidate has neither help nor hurt.

### 3. The score (D-32)

```
skills     S = skill coverage                          (0–1)
experience E = 1 if years ≥ minimum, else years ÷ minimum
culture    T = coverage of the job's culture keywords by the candidate's traits

score = round(100 × (0.7·S + 0.2·E + 0.1·T), 1)
```

- **Worked example:** Sherlock for Backend Detective: 100 × (0.7·1 + 0.2·1 + 0.1·0.5) = **95.0**.
- **A job with no culture keywords** leaves T out and rescales: `(0.7·S + 0.2·E) ÷ 0.9`.
- **No skill credit, no match** (D-12): experience and culture alone can't put a candidate on the list.

### 4. Tiers and order (D-34, D-16)

| Tier | Score |
|---|---|
| `strong_match` | ≥ 70 |
| `possible_match` | 50 to < 70 |
| `near_miss` | < 50, with some skill credit |

Within the list: score, then skill score, then (for a job's candidates) availability, so that among equal fits the one who can start soonest comes first, then name.

### 5. One score, both directions (D-15, D-32)

`score_match(candidate, job, credit)` is a pure function with no database and no notion of direction. Both endpoints read the same stored row, so a pair can never get two different scores. The credit source is passed in, so replacing the taxonomy (with real ESCO data, say) changes the source and not the scorer.

---

## Known limitations

Stated plainly, so a reviewer doesn't have to find them:

- **There's no migration runner yet,** and Docker Compose starts only the database. Migrations are applied with the one-time command in Quick start.
- **Synonyms outside the taxonomy get no credit:** `customer-handling` doesn't match `customer-management`. The planned fix is local-model linking with negation checks, after the MVP (D-31).
- **Quirks and taglines aren't returned in responses yet.**
- **Not built yet:** `?min_score=`, the three-near-miss limit (D-17) and `?include_passive=` (D-10).
- **`show_matches` and the tests compute matches directly** and break ties by name; the API also uses availability.
- **The database tests use the development database,** so records added through the API can affect them.
- **[docs/ER_DIAGRAM.md](docs/ER_DIAGRAM.md)** covers the first migration only.

---

## Quick start

```bash
# 1. Database (Postgres on 127.0.0.1:5433)
docker compose up -d db

# 2. Dependencies
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt -r requirements-dev.txt   # on macOS/Linux: .venv/bin/python

# 3. Schema: apply the migrations once, in order, to the empty database
for f in migrations/*.sql; do docker compose exec -T db psql -v ON_ERROR_STOP=1 -U recruiter -d recruiter_bot < "$f"; done

# 4. Seed data: 15 candidates, 6 jobs, the taxonomy, and all matches
.venv/Scripts/python -m recruiter_bot.seed

# 5. API, with interactive docs at http://127.0.0.1:8000/docs
.venv/Scripts/python -m uvicorn recruiter_bot.api.main:app --reload
```

The connection defaults to `postgresql://recruiter:recruiter@127.0.0.1:5433/recruiter_bot`; set `DATABASE_URL` to override it.

---

## Tests

```bash
.venv/Scripts/python -m pytest -q
```

They cover normalization, ingestion validation, the taxonomy, credit and coverage, the score formula, and pinned rankings for all six jobs. The database tests skip when Postgres isn't running.

For a single ranking in the terminal:

```bash
.venv/Scripts/python -m recruiter_bot.show_matches job 1
```

---

## Layout

```
migrations/        hand-written DDL, applied in order
seed/              candidates, jobs and the taxonomy (JSON)
recruiter_bot/
  ingest/          validation, normalization, inserts, taxonomy loading
  matching/        credit, coverage, scoring, ranking, stored matches
  api/             FastAPI routes and response models
  seed.py          python -m recruiter_bot.seed
tests/
DECISION.md        every decision, with its reasoning
```
