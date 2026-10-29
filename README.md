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

**Full API reference:** [docs/API.md](docs/API.md) explains every endpoint, its fields, and its errors.

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
      { "rank": 1, "candidate_name": "Dwight S.", "score": 66.7,
        "reason": "2/3 skills (negotiation, sales) · missing public-speaking · 9y vs 3y min · culture 0/2",
        "quirk": "Assistant to the regional backend engineer." },
      { "rank": 2, "candidate_name": "Elle W.", "score": 55.0,
        "reason": "1.5/3 skills (public-speaking, sales ≈ persuasion ½) · missing negotiation · 3y vs 3y min · culture 0/2" }
    ],
    "near_miss": [],
    "near_misses_included": false
  },
  "proactive_offers_included": true,
  "proactive_offers": [
    { "rank": 1, "candidate_name": "Michael S.", "score": 71.7, "tier": "strong_match",
      "recommended_action": "proactive-offer",
      "reason": "2/3 skills (public-speaking, sales) · missing negotiation · 11y vs 3y min · culture 1/2 (enthusiastic)",
      "evidence": {
        "skills":     { "matched": ["public-speaking", "sales"], "missing": ["negotiation"] },
        "experience": { "detail": "11 years, meets the 3-year minimum" },
        "culture":    { "matched": ["enthusiastic"], "missing": ["persistent"] }
      },
      "quirk": "World's best boss, according to a mug he bought himself." }
  ]
}
```

**Every entry carries its evidence:** a `rank`, the `score`, a short `reason`, and an `evidence` block saying **what matched and what is missing** for skills and culture, plus one sentence for experience (D-50). Michael matched public-speaking and sales, and is missing negotiation. The quirk is shown next to it, never scored.

**Want the arithmetic? Add `?explain=true`** to either matches endpoint, for example `curl "http://127.0.0.1:8000/jobs/6/matches?explain=true"`. Each entry then also has a `score_breakdown` with the score, weight and **points** of skills, experience and culture. The points add up to the score: Michael is 46.7 + 20.0 + 5.0 = 71.7. Without the option, this block isn't in the response.

Errors: `404` for an unknown id, `409` when an email is already used, or a company already has a job with that title, and `422` for invalid input, such as no skills or `"availability": "someday"`.

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
| **Is minimum experience a must?** | Yes. Every job's `experience_requirement` is `required` by default: below the minimum, no match. A job owner can set `preferred` instead (below the minimum, the score drops and the match is at most "possible"). Every entry shows `meets_minimum_experience`. | A stated minimum is treated as a requirement, so nothing is assumed negotiable. Before this, a candidate with every skill and 0 of 8 years was labelled a strong match (D-56). |
| **Quirks and taglines** | Shown with every match, never scored. | They're mostly jokes ("Says nothing. Everyone panics."), and their structured form (traits and culture keywords) is already scored (D-06). |
| **Job title** | Not scored. | Candidates have no title or desired role to compare it with, and a title's meaning already comes through its required skills (D-47). |
| **Candidate preferences** | None in the data. An optional `job_preferences` field is stored now. | Preferences can't be backfilled later, so they're collected before they're used (D-47). |
| **No email or id in the data** | Names aren't unique: people share names. A candidate's identity is an optional `email`, unique when present; a job's is its optional `company` plus title. A clash returns `409`, never an overwrite. | Rejecting a second "Alex Kim" would be wrong for real people. While email is missing, a person posted twice can't be detected; that's a limit of the data, and it's stated (D-53). |
| **Misspelled or reworded skills** | Typos, word order and word forms are linked by rules (`building-teams` = team-building). Words the rules can't place go to two small local models, which can add only a capped, labelled "suggested" credit, or send the word for review (D-54). | A wrong link would silently change every score using that word, so the rules favour precision. They reject `product-management` → project-management, for example (D-41). |

---

## How matches are ranked

**For a job, the recruiter sees two sections** (D-49):
1. **`matches`:** candidates open to opportunities, grouped into `strong_match` (70 or more), `possible_match` (50 or more) and `near_miss` (below 50).
2. **`proactive_offers`:** candidates *not* looking who score higher than every open candidate. That's exactly when an offer is worth the effort, as with Tony, Miranda and Michael.

**`proactive_offers_included` is always in the response:** `true` when someone is worth an offer, `false` when nobody who isn't looking beats the best open candidate (as for Backend Detective, Developer Relations and Incident Commander). So an empty `proactive_offers` list is never ambiguous.

**Near misses only appear when nobody reaches 50,** and at most 3, so they explain what's missing instead of cluttering real matches.

**Order within the list, when scores tie** (D-16):
1. Total score
2. Earliest start date (a date in the past counts as today)
3. A neutral hash of the job and candidate ids: the same order every time, favouring no one

**The name is never used:** alphabetical order would put the same people first on every tie, for every job.

**For a candidate, jobs are ordered by** (D-51):
1. **Score:** fit always comes first.
2. **Jobs matching their `job_preferences`.**
3. **Their chance:** the share of competing candidates (open, scoring 50 or more for that job) they beat. Elle beats 88% for Developer Relations.
4. **Newest posting.**
5. **The neutral hash.**

**How standing breaks a tie between two jobs:** the tie is the candidate's own score, but each job has different competitors, so the candidate's position differs.

| | Job A | Job B |
|---|---|---|
| Your score | 70 | 70 (tied) |
| Competing candidates | one at 90 | two at 55 |
| Share you beat | 0% | 100% |

So Job B comes first: the same fit, but a far better chance. Standing uses the **total** score, since it already weighs skills, experience and culture. If the position is the same in both pools too (Ron: 43.3 for both jobs, 0% in each), the newest posting, then the hash, decide.

Each job says `top_applicant: true` when no competing candidate scores higher. The exact share isn't shown, because in a small pool it would reveal other people's scores. Standing is never the first sort: that would steer candidates toward the jobs they fit worst, just because they have fewer rivals.

### Why experience is not a tie-breaker
- **It's already in the score:** 20%, and full once the job's minimum is met. Two tied candidates usually both meet it.
- **More years isn't a better fit:** 15 years isn't better than 8 for a job asking for 3.
- **It tracks age.** Preferring more years would favour older candidates, an age-discrimination risk under the US Age Discrimination in Employment Act and EU equal-treatment law.

---

## How skills are matched

**Skills and traits are matched through a small taxonomy in the shape of [ESCO](https://esco.ec.europa.eu)** (D-29), with 51 concepts. 32 of them carry **real ESCO labels**: 236 synonyms in all, such as `think critically` for deduction and `work autonomously` for independence, taken from the ESCO records in `seed/esco_snapshot.json` (CC BY 4.0, © European Union, D-55). The other 19 have no ESCO equivalent and keep our own labels. Embeddings weren't used for matching, because they score opposites as similar (`calm` sits closer to `anxious` than to `level headed`).

| Candidate term vs job term | Credit | Example |
|---|---|---|
| Same word, or same concept | 1.0 | `tenacious` = `persistent` |
| Related concept | 0.5 | `persuasion` ≈ `negotiation` |
| Suggested by a model (see below) | 0.25 | `crisis-handling` ≈ `crisis-management` |
| Anything else | 0 | |

### Words the taxonomy doesn't know
1. **Rules first** (D-41): negation (`not organized` is never linked), word roots (`managing-products` = product-management), typos, and grouping.
2. **Then, optionally, two small local models** (D-54) for words the rules leave unplaced: an embedding model finds the 10 closest concepts, and an NLI model checks each one in both directions ("does *crisis handling* imply *crisis management*, and the reverse?"). Calibrated thresholds then decide:
   - **confident:** the word earns **0.25**, labelled `(suggested ¼)` in the reason;
   - **plausible:** it goes to a **review queue** for a person;
   - **otherwise:** no credit, as before.
3. **A guess can never create a match on its own,** never chains, and never counts as a synonym. `GET /taxonomy/suggestions` shows every suggested link and the review queue.
4. **A person decides once, and the system keeps it** (D-55):
   - `POST /taxonomy/suggestions/skill/bargaining/approve` with `{"concept": "negotiation"}` makes `bargaining` a full synonym for everyone, from that moment on;
   - `…/reject` removes a wrong guess for good.

   Example: Pat wrote `bargaining` and scored 43.3. After one approval, Pat scored 66.7, and the next candidate with `bargaining` got full credit straight away.

**The models are optional, and off by default.** A plain `docker compose up --build` runs on the rules alone. To add them (about 125 MB, downloaded from pinned Hugging Face commits and checked by hash):

| How you run it | Command |
|---|---|
| Docker (Mac / Linux) | `WITH_MODELS=true docker compose up --build` |
| Docker (Windows PowerShell) | `$env:WITH_MODELS="true"; docker compose up --build` |
| Without Docker | `pip install -r requirements-linking.txt`, then `python -m recruiter_bot.linking.model_files` |

**If the models aren't available, nothing breaks:** missing libraries or files, a failing word, or a failed write all fall back to the rules alone, and `MODEL_LINKING=off` turns the stage off. `GET /taxonomy/suggestions` says which mode is running. On the seed data the models link nothing confidently: unknown seed words go to review, or stay unknown when nothing is plausible (`minimalism`).

**How accurate is it?** Measured on ESCO's own labels, which nobody here wrote (`python -m recruiter_bot.linking.evaluate_esco`, D-55):
- the word-root rule was right 9 of 10 times;
- the model's automatic guesses 15 of 27 (**56%**). Its mistakes were narrower concepts, never opposites (`woodworking tools` → woodworking), which is why a guess earns only ¼;
- every synonym it was unsure about went to review with the right concept first, so one approval fixes it.

**Each candidate skill covers at most one requirement,** so one `persuasion` can't count toward both `sales` and `negotiation`. The best pairing is found exactly with the Hungarian algorithm, in milliseconds even for a 40-skill job (D-52); a first version that tried every combination took 109 seconds at 10 skills.

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
- **A stronger model stage:** fine-tune the embedding model on ESCO's own synonym pairs, index ESCO's skills in Postgres with `pgvector`, and turn every review decision into a new labelled example. Comparing two unknown words with each other (`customer-handling` vs `customer-management`) isn't built yet.
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

**Tests:** `tests/test_matching.py` has 16 tests that prove the main behaviour: the score formula, the gate (no skill overlap, no match), one-to-one skill coverage, related and synonym credit, ranking in both directions, the recruiter's proactive offers, near-miss hiding, and tie order. The first 7 need no database. The rest run against a throwaway database (`recruiter_bot_test`) that `tests/conftest.py` builds from the real migrations and seed data and drops afterwards, so your own data is never touched. They are skipped if Postgres isn't running.

Raw, hand-written SQL only: psycopg 3, with no ORM or query builder. The schema is in [`migrations/`](migrations/); the reasoning for every choice is in [DECISION.md](DECISION.md).
