# Recruiter Bot

A small backend that loads candidates and job openings, then ranks the best matches both ways: the best candidates for a job, and the best jobs for a candidate. Every match has a score and a short reason. Every design decision is written down, with its reasoning, in [DECISION.md](DECISION.md); `D-xx` numbers below point to it.

---

## Run it

You only need **Docker Desktop**. Nothing else has to be installed.

1. **Install Docker Desktop** from https://www.docker.com/products/docker-desktop/ and start it. Wait until it says it's running.
2. **Get the project.** Either run `git clone <repository-url>`, or download it as a ZIP and unzip it.
3. **Open a terminal in the project folder:**
   - **Windows:** open the folder in File Explorer, click the address bar, type `cmd`, and press Enter.
   - **Mac:** right-click the folder in Finder and choose "New Terminal at Folder".
4. **Start everything:**
   ```bash
   docker compose up --build
   ```
   The first time takes a few minutes. It's ready when you see `Uvicorn running on http://0.0.0.0:8000`.
5. **Open http://127.0.0.1:8000/docs in your browser.** It's an interactive page where you can try every endpoint: click one, then "Try it out", then "Execute".

**To stop it,** press `Ctrl + C` in the terminal. **To start again with fresh data,** run `docker compose down -v`, then step 4. This deletes everything that was added.

**If port 8000 is already in use,** pick another one:

| System | Command |
|---|---|
| Mac / Linux | `API_PORT=8001 docker compose up --build` |
| Windows (cmd) | `set API_PORT=8001 && docker compose up --build` |
| Windows (PowerShell) | `$env:API_PORT=8001; docker compose up --build` |

Then use `8001` instead of `8000` in the addresses below.

---

## Try it

**On Windows, type `curl.exe` instead of `curl`.** For sending data (the `POST` and `PATCH` examples), the `/docs` page is easier than the terminal.

```bash
# Every job and candidate, with their ids
curl http://127.0.0.1:8000/jobs
curl http://127.0.0.1:8000/candidates

# Ranked candidates for a job (required by the brief)
curl http://127.0.0.1:8000/jobs/6/matches

# Ranked jobs for a candidate (required by the brief)
curl http://127.0.0.1:8000/candidates/7/matches

# Add a candidate: the response is their matching jobs
curl -X POST http://127.0.0.1:8000/candidates -H "Content-Type: application/json" \
  -d '{"name": "Jordan", "skills": ["Crisis Management", "Strategy", "Persuasion"], "experience_years": 6, "availability": "2 weeks", "traits": ["Calm", "Decisive"]}'

# Change one field of a job: the response is its refreshed matches
curl -X PATCH http://127.0.0.1:8000/jobs/6 -H "Content-Type: application/json" -d '{"min_experience_years": 4}'
```

`GET /jobs/6/matches` (Sales Engineer) returns, shortened:

```json
{
  "job_id": 6,
  "matches": {
    "strong_match": [],
    "possible_match": [
      { "candidate_name": "Dwight S.", "score": 66.7,
        "reason": "2/3 skills (negotiation, sales) · missing public-speaking · 9y vs 3y min · culture 0/2",
        "quirk": "Assistant to the regional backend engineer." },
      { "candidate_name": "Elle W.", "score": 55.0,
        "reason": "1.5/3 skills (public-speaking, sales ≈ persuasion ½) · missing negotiation · 3y vs 3y min · culture 0/2" }
    ],
    "near_miss": [],
    "near_misses_included": false
  },
  "proactive_offers": [
    { "candidate_name": "Michael S.", "score": 71.7, "tier": "strong_match", "recommended_action": "proactive-offer",
      "reason": "2/3 skills (public-speaking, sales) · missing negotiation · 11y vs 3y min · culture 1/2 (enthusiastic)" }
  ]
}
```

Errors: `404` for an unknown id, `409` when a name or title already exists, and `422` for invalid input, such as no skills or `"availability": "someday"`.

---

## Ambiguities, and what was assumed

The brief says real requirements are rarely fully specified. Each gap below was resolved explicitly, with evidence from the data, and logged.

| Ambiguity | What was assumed | Evidence |
|---|---|---|
| **Must-have or nice-to-have skills?** Jobs list skills with no priority. | Every listed skill counts equally, but as **coverage**, not all-or-nothing: 2 of 3 skills earns ⅔ of the skill score (D-08). | **No candidate has all three Engineering Manager skills** (team-building, stakeholder-management, leadership). An all-or-nothing rule would leave that job with no candidates at all. With coverage, Miranda (2 of 3) and Ted rank sensibly. |
| **The brief says Michael Scott is "applying" for Sales Engineer; the data says "Not looking".** | "Not looking" means not *actively* looking, not "do not contact". | Michael is the best Sales Engineer fit (71.7). Hiding him loses the best person, and ranking him as available misleads the recruiter. So he appears under `proactive_offers`, which is where a recruiter would act on him (D-49). |
| **"2 weeks" from when?** | Converted to a real date when first loaded, and never recalculated. | Recalculating on each re-seed moved Hermione's start date one day further every run, so it never arrived. That bug was found and fixed (D-05, D-39). |
| **Broken words in the source** (`pattern-recog nition`) | PDF line-break artifacts, corrected. | Every one splits a word mid-word (D-01). |
| **`stakeholder management` vs `stakeholder-management`** | Every term is normalized: lowercase, hyphenated. | The same skill is written both ways in the source (D-02). |
| **Skills that are really personality** (`loyalty`, `optimism`, `precision`) | Listed as skills, but given no skill credit. | They describe a person, not a skill. The seed run reports them so the source can be fixed (D-30). |
| **What "experience" measures** | Total career years. More than the minimum isn't penalized. | The data has no years per skill (D-07, D-13). |
| **Quirks and taglines** | Shown with every match, never scored. | They're mostly jokes ("Says nothing. Everyone panics."), and their structured form (traits and culture keywords) is already scored (D-06). |
| **Job title** | Not scored. | Candidates have no title or desired role to compare it with, and a title's meaning already comes through its required skills (D-47). |
| **Candidate preferences** | None in the data. An optional `job_preferences` field is stored now. | Preferences can't be backfilled later, so they're collected before they're used (D-47). |
| **No email or id in the data** | The normalized name identifies a record; a duplicate name returns `409`, never an overwrite. | Otherwise anyone posting "Sherlock H." could replace his profile (D-04, D-35). |
| **Misspelled or reworded skills** | Typos, word order and word forms are linked by rules (`building-teams` = team-building). Anything else gets no credit, and no penalty. | A wrong link would silently change every score using that word, so the rules favour precision. They reject `product-management` → project-management, for example (D-41). |

---

## How matches are ranked

**For a job, the recruiter sees two sections** (D-49):
1. **`matches`:** candidates open to opportunities, grouped into `strong_match` (70 or more), `possible_match` (50 or more) and `near_miss` (below 50).
2. **`proactive_offers`:** candidates *not* looking who score higher than every open candidate. That's exactly when an offer is worth the effort, as with Tony, Miranda and Michael.

**Near misses only appear when nobody reaches 50,** and at most 3, so they explain what's missing instead of cluttering real matches.

**Order within the list, when scores tie** (D-16):
1. Total score
2. Earliest start date (a date in the past counts as today)
3. A neutral hash of the job and candidate ids: the same order every time, favouring no one

**The name is never used:** alphabetical order would put the same people first on every tie, for every job.

### Why experience is not a tie-breaker
- **It's already in the score:** 20%, and full once the job's minimum is met. Two tied candidates usually both meet it.
- **More years isn't a better fit:** 15 years isn't better than 8 for a job asking for 3.
- **It tracks age.** Preferring more years would favour older candidates, an age-discrimination risk under the US Age Discrimination in Employment Act and EU equal-treatment law.

---

## How skills are matched

**Skills and traits are matched through a small taxonomy in the shape of [ESCO](https://esco.ec.europa.eu)** (D-29), filled with our own data (51 concepts): each concept has a preferred label, synonyms, and hidden labels for misspellings. Embeddings weren't used for matching, because they score opposites as similar (`calm` sits closer to `anxious` than to `level headed`).

| Candidate term vs job term | Credit | Example |
|---|---|---|
| Same word, or same concept | 1.0 | `tenacious` = `persistent` |
| Related concept | 0.5 | `persuasion` ≈ `negotiation` |
| Anything else | 0 | |

**Each candidate skill covers at most one requirement,** so one `persuasion` can't count toward both `sales` and `negotiation`.

## The score

```
score = 100 × (0.7 × skills + 0.2 × experience + 0.1 × culture)
```

- **skills:** credit earned ÷ the number of skills the job lists.
- **experience:** 1 if years ≥ the minimum, otherwise years ÷ minimum.
- **culture:** credit earned ÷ the number of culture keywords the job lists.

- **Worked example:** Sherlock for Backend Detective is 100 × (0.7 × 1 + 0.2 × 1 + 0.1 × 0.5) = **95.0**.
- **No skill credit means no match,** whatever the experience or culture (D-12).
- **One score serves both directions:** a pair always has the same score in the recruiter's view and in the candidate's (D-15, D-32).
- **Matches are stored,** and refreshed in the same transaction as every write, so reads are fast and never stale (D-37).

**Are the weights right?** There are no hiring outcomes to learn them from, so a sensitivity check (`python -m recruiter_bot.sensitivity.report`) re-ranked every job under other weights (D-48):
- **Moving any one weight by ±0.05 or ±0.10 never changes a job's winner.**
- **Across 31 plausible weightings,** 5 of the 6 winners are never beaten.
- **The one exception** needs culture weighted at more than a third of skills.

So skills decide the winner, and culture only separates otherwise equal candidates.

---

## Future work

- **Real ESCO data:** the taxonomy already has ESCO's shape and empty reference slots, so ESCO's 13,000+ skills could be loaded into the same tables.
- **A model for words the rules can't place** (`customer-handling` vs `customer-management`):
  - **The prototype:** local embedding and NLI models, measured against 116 hand-labelled words, reached only **67% precision** on the test set, against a 98% target, so it's not in the project (D-42 to D-45).
  - **The next attempt** needs a model fine-tuned on ESCO synonyms and a larger labelled set.
- **Job preferences carrying real weight:** `job_preferences` is already collected. Next, jobs a candidate prefers would rank higher **in the candidate's own list.** That boosts their ranking without changing the shared fit score, so both directions still agree (D-47).
- **Job start dates:** compare a candidate's availability with when the job needs someone, not only with today.
- **Spreading attention:** the same strong candidates top several jobs. Production platforms balance this with reciprocal or stable matching (the Gale–Shapley algorithm).
- **`?min_score=`** and an option to show near misses on demand.

---

## For developers

```bash
docker compose up -d db                     # Postgres on 127.0.0.1:5433
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt -r requirements-dev.txt   # macOS/Linux: .venv/bin/python
.venv/Scripts/python -m recruiter_bot.migrate
.venv/Scripts/python -m recruiter_bot.seed
.venv/Scripts/python -m uvicorn recruiter_bot.api.main:app --reload
.venv/Scripts/python -m pytest -q
```

Raw, hand-written SQL only: psycopg 3, with no ORM or query builder. The schema is in [`migrations/`](migrations/); the reasoning for every choice is in [DECISION.md](DECISION.md).
