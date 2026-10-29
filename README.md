# Recruiter Bot

Ranks candidates for a job, and jobs for a candidate. Every match has a score, a tier and a reason that says exactly **what matched and what is missing**. Built with Python, FastAPI and PostgreSQL, using **raw, hand-written SQL only** (psycopg 3, no ORM or query builder).

## Run it locally

You need only **Docker Desktop**, running.

```bash
git clone <repository-url>
cd RecruitorBot
docker compose up --build
```

When the terminal shows `Uvicorn running on http://0.0.0.0:8000`, open **http://127.0.0.1:8000/docs** to try every endpoint in the browser. On startup the app creates the schema, loads the 15 candidates and 6 jobs, and computes every match.

```bash
curl http://127.0.0.1:8000/jobs/6/matches           # ranked candidates for a job
curl http://127.0.0.1:8000/candidates/7/matches     # ranked jobs for a candidate
curl "http://127.0.0.1:8000/jobs/6/matches?explain=true"   # plus the score arithmetic
```

On Windows, type `curl.exe`. To reset the data, run `docker compose down -v`. If port 8000 is taken, run `API_PORT=8001 docker compose up --build`.

**Ingestion:** the seed loads on startup, and `POST /candidates` and `POST /jobs` use the same code. `PATCH` endpoints edit a record. Every write refreshes its matches in the same transaction.

---

## How matching works

### 1. Every term is compared through a taxonomy, not by spelling

Skills, traits and culture keywords are normalized (`Stakeholder Management` → `stakeholder-management`), then matched through a 51-concept taxonomy shaped like [ESCO](https://esco.ec.europa.eu), the EU's skills classification. 32 of the concepts carry real ESCO synonyms.

| Candidate term vs job term | Credit | Example |
|---|---|---|
| Same word or same concept | 1.0 | `tenacious` = `persistent` |
| Related concept | 0.5 | `persuasion` ≈ `negotiation` |
| Suggested by the optional model | 0.25 | `crisis-handling` ≈ `crisis-management` |
| Anything else | 0 | |

**Each candidate skill covers at most one requirement,** so one `persuasion` can't count for both `sales` and `negotiation`. The best pairing is found exactly by the **Hungarian algorithm**. A first brute-force version took 109 seconds at 10 skills.

### 2. Three factors, one score

```
score = 100 × (0.7 × skills + 0.2 × experience + 0.1 × culture)
```

- **skills** = credit earned ÷ skills the job lists. This is coverage, not all-or-nothing: 2 of 3 earns ⅔.
- **experience** = 1 when years ≥ the minimum. Being over-qualified is never penalized.
- **culture** = credit earned ÷ culture keywords the job lists, matched against the candidate's traits.

**Why 70 / 20 / 10:** skills and experience are the two factors the brief requires. Skills carry most of the weight because they're what the job actually needs done. Experience is mostly a gate (below), so its 20 points rarely separate people. Culture is a soft signal, worth only enough to separate otherwise equal candidates. Availability isn't in the score at all; it breaks ties instead. A sensitivity check backs the split: moving any one weight by ±0.10 never changes a job's winner (see the trade-offs below).

**Two gates come before the score:** no skill overlap means no match, and less than the job's minimum experience means no match. A job owner can relax the second rule by setting `experience_requirement: "preferred"`. Below the minimum, the score then drops in proportion and the match can be at most "possible".

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

**Quirks and taglines are shown, never scored.** They're free text, and mostly jokes ("Says nothing. Everyone panics."). Their structured form, traits and culture keywords, is already scored. So they're kept as details in the response: the candidate's `quirk` in the recruiter's view, and the job's `tagline` in the candidate's view.

### 4. Ordering and ties

**Candidates for a job:**
1. Total score.
2. Earliest available date. A date in the past counts as today.
3. A neutral hash of the job and candidate ids. The order is the same every time and favours no one; names are never used.

**Jobs for a candidate:**
1. Score.
2. `top_applicant`: jobs where no competing open candidate scores higher come first, because that's where the candidate's chance is best. It's shown as a yes or no, never as a count, so other people's scores stay private.
3. Most recent posting, since older ads are more likely to be filled already.
4. The neutral hash.

**One score serves both directions:** a pair always has the same score in the recruiter's view and in the candidate's.

### 5. Words the taxonomy doesn't know

1. **Deterministic rules first:** negation (`not organized` is never linked), word roots (`managing-products` = product-management), typos and grouping. They favour precision, for example rejecting `product-management` → project-management.
2. **Optional local models: experimental, and off by default** (turn on with `WITH_MODELS=true docker compose up --build`). An embedding model proposes the 10 closest concepts, and an NLI model checks each one in both directions. A confident result earns only the capped 0.25 and is labelled `(suggested ¼)` in the reason. A plausible one goes to a **review queue**. A suggestion can never create a match on its own.

   **The models aren't accurate enough yet to be trusted.** On ESCO's own labels, their automatic guesses were right 15 of 27 times (56%). On a held-out test, precision was 67% against a target of 98%. Their typical mistake is linking a related word as a synonym (`caring` → empathy). That's why the rules decide, and the models only suggest.

   **For production, the plan is to:**
   - build a labelled set of several hundred words from ESCO's alternative labels and from reviewers' decisions;
   - fine-tune the embedding model on ESCO's synonym pairs, so it can tell "same" from "related";
   - index ESCO's 13,000+ skills in Postgres with `pgvector`;
   - give automatic credit only once precision reaches 98% on fresh test data.
3. **A person decides once, and the system keeps it.** `POST /taxonomy/suggestions/{type}/{term}/approve` makes the word a full synonym for everyone from then on, and `/reject` removes a wrong guess for good.

---

## Decisions and trade-offs

**Coverage over all-or-nothing skills.** Jobs don't mark any skill as optional, so every listed skill counts equally. But no candidate has all three Engineering Manager skills, so a strict rule would leave that job empty. Coverage ranks Miranda (2 of 3) and Ted sensibly instead.

**Skills dominate, and the weights were checked.** With no hiring outcomes to learn weights from, a sensitivity analysis (`python -m recruiter_bot.sensitivity.report`) re-ranked every job under other weightings. Moving any single weight by ±0.05 or ±0.10 never changes a job's winner. Across 31 plausible weightings, 5 of the 6 winners are never beaten. The one exception needs culture weighted above a third of skills. Culture's real role is separating otherwise equal candidates.

**Why skill overlap isn't decided by ML.** Using a model's similarity score directly as skill credit was considered and rejected, for four measured reasons:
- **It confuses opposites with synonyms.** The embedding model puts `calm` closer to `anxious` than to `level headed` (0.79 vs 0.64), and gives `pessimistic` vs optimism a similarity of 0.85–0.90.
- **It can't tell "same" from "related".** To the NLI model, `coaching` and `mentorship` imply each other as strongly as `bargaining` and `negotiation`. Used directly, a merely related skill would earn full credit.
- **It isn't accurate enough.** On held-out words, its links were 67% precise against a 98% target, and on ESCO's own labels it was right 56% of the time.
- **A wrong link is silent and spreads.** It changes every score that uses the word, and nobody can see why. A score built from concepts can be explained: the reason names the source of every partial credit (`sales ≈ persuasion ½`), and a recruiter can check it.

So credit comes from explicit concepts and rules, and the model can only add a small, capped, labelled suggestion, or send the word to a person for review.

**"Not looking" doesn't mean "don't contact".** The brief says Michael Scott is applying for Sales Engineer, but his data says "Not looking". Hiding him would lose the best fit, and listing him as available would mislead. So he appears under `proactive_offers`.

**Experience is a gate, not a tie-breaker.** A stated minimum is treated as a requirement. Before this rule, a candidate with every skill and 0 of 8 years was labelled a strong match. Above the minimum, more years earn nothing: 15 years isn't a better fit than 8 for a job asking for 3. Preferring more years would also track age, which is a discrimination risk.

**Stored, not computed on read.** Matches are stored and refreshed in the same transaction as every write, so reads are fast and never stale.

**Job titles aren't scored,** because candidates have no title or desired role to compare them with, and a title's meaning already comes through its required skills.

**Limitations.** Six jobs and no outcome data: the analysis shows the ranking is robust, not that it's correct. Names aren't unique, so a candidate's identity is an optional email; while it's missing, a person posted twice can't be detected. Comparing two unknown words with each other isn't built yet.

---

## Tests

`tests/test_matching.py` has 17 tests:
- **Scoring and ordering (8, no database needed):** the 70/20/10 formula; full marks for over-qualified candidates; proportional experience credit; no skill overlap means no match; half credit for related skills, named in the reason; one skill can't cover two requirements; the exact 50 and 70 tier boundaries; a candidate's tied jobs ordered by top applicant, then newest posting.
- **End to end (9, against a throwaway database built from the real migrations and seed):** ranking in both directions; the same score both ways; stored matches equal a fresh calculation; ties go to whoever can start first; proactive offers appear only when deserved; near misses appear only when nothing better exists; taxonomy synonyms and related words.

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

**More detail:** [API reference](docs/API.md) · [Design decisions (D-01 to D-56)](DECISION.md) · [Database schema and ER diagram](docs/ER_DIAGRAM.md) ([image](docs/er_diagram.png), [editable draw.io](docs/er_diagram.drawio))
