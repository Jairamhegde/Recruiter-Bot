# Recruiter Bot API

The base URL is `http://127.0.0.1:8000`. You can try every endpoint interactively at `/docs` (Swagger).

All bodies are JSON. On Windows, use `curl.exe` instead of `curl`.

| Method | Path | What it does |
|---|---|---|
| GET | [`/jobs`](#get-jobs) | Lists every job, with its id |
| GET | [`/jobs/{job_id}/matches`](#get-jobsjob_idmatches) | Ranks the candidates for a job (the recruiter's view) |
| POST | [`/jobs`](#post-jobs) | Adds a job and returns its matches |
| PATCH | [`/jobs/{job_id}`](#patch-jobsjob_id) | Changes some fields of a job and returns its refreshed matches |
| GET | [`/candidates`](#get-candidates) | Lists every candidate, with their id |
| GET | [`/candidates/{candidate_id}/matches`](#get-candidatescandidate_idmatches) | Ranks the jobs for a candidate (the candidate's view) |
| POST | [`/candidates`](#post-candidates) | Adds a candidate and returns their matches |
| PATCH | [`/candidates/{candidate_id}`](#patch-candidatescandidate_id) | Changes some fields of a candidate and returns their refreshed matches |
| GET | [`/taxonomy/suggestions`](#get-taxonomysuggestions) | Shows what the model stage linked, the words waiting for review, and every decision |
| POST | [`/taxonomy/suggestions/{type}/{term}/approve`](#post-taxonomysuggestionstypetermapprove) | A person confirms what an unknown word means |
| POST | [`/taxonomy/suggestions/{type}/{term}/reject`](#post-taxonomysuggestionstypetermreject) | A person rejects the model's guess |

---

## Shared concepts

### The score
Every match has a `score` from 0 to 100:

```
score = 100 × (0.7 × skills + 0.2 × experience + 0.1 × culture)
```

- **skills:** the share of the job's required skills the candidate covers. A synonym earns full credit, a related skill half.
- **experience:** 1 if the candidate meets the job's minimum years, otherwise years ÷ minimum.
- **culture:** the share of the job's culture keywords matched by the candidate's traits.

A candidate with no skill in common with a job is never a match.

A pair always has the same score in both directions.

### Tiers
| Tier | Score |
|---|---|
| `strong_match` | 70 or more |
| `possible_match` | 50 to 69.9 |
| `near_miss` | below 50 |

**Near misses are shown only when nothing reaches 50,** and at most 3. `near_misses_included` says whether they're in the list.

### A match entry
Each entry has:

| Field | Meaning |
|---|---|
| `rank` | Its position in the list, 1 being the best |
| `score` | 0 to 100 |
| `reason` | A short sentence, e.g. `2/3 skills (public-speaking, sales) · missing negotiation · 11y vs 3y min · culture 1/2 (enthusiastic)` |
| `evidence` | What matched and what is missing: `skills` and `culture` have `matched` and `missing` lists; `experience` has one `detail` sentence. `culture` is `null` when the job has no culture keywords. |
| `meets_minimum_experience` | `false` when the candidate has fewer years than the job's minimum. Such a match is at most `possible_match`, or isn't listed at all when the job's minimum is `required` (D-56). |
| `score_breakdown` | **Only with `?explain=true`.** For each factor: `score`, `weight`, `points`, `detail`, `matched`, `missing`. The points add up to the score. |

### Errors
| Status | When |
|---|---|
| `404` | No job or candidate with that id |
| `409` | An email another candidate already uses, or a title the same company already has (letter case is ignored). Names, and titles without a company, may repeat. |
| `422` | Invalid input, e.g. no skills, a negative number of years, `"availability": "someday"`, an unknown field in a PATCH, or `?explain=maybe` |

---

## Jobs

### GET /jobs
Lists every job, sorted by id. Use it to find the id to pass to the other endpoints.

```bash
curl http://127.0.0.1:8000/jobs
```

```json
[
  { "job_id": 1, "title": "Backend Detective", "min_experience_years": 3,
    "required_skills": ["deduction", "forensics", "pattern-recognition"], "culture_keywords": ["analytical", "autonomous"],
    "experience_requirement": "required" }
]
```

### GET /jobs/{job_id}/matches
**The recruiter's view:** the best candidates for one job, in two sections.

- **`matches`:** candidates **open to opportunities**, grouped into tiers.
- **`proactive_offers`:** candidates **not looking** who are a strong or possible match and score higher than every open candidate. These are worth approaching anyway. Each has a `tier` and `"recommended_action": "proactive-offer"`.
- **`proactive_offers_included`:** always present, `true` when the list above is not empty.

**Order within a section:** score, then earliest start date, then a neutral hash of the ids. Names are never used to break ties.

Each candidate entry also shows their `quirk`, which is never scored.

| Query option | Default | Effect |
|---|---|---|
| `explain` | `false` | Adds `score_breakdown` to every entry |

```bash
curl http://127.0.0.1:8000/jobs/6/matches
curl "http://127.0.0.1:8000/jobs/6/matches?explain=true"
```

```json
{
  "job_id": 6,
  "matches": {
    "strong_match": [],
    "possible_match": [
      { "rank": 1, "candidate_id": 15, "candidate_name": "Dwight S.", "score": 66.7,
        "reason": "2/3 skills (negotiation, sales) · missing public-speaking · 9y vs 3y min · culture 0/2",
        "evidence": {
          "skills": { "matched": ["negotiation", "sales"], "missing": ["public-speaking"] },
          "experience": { "detail": "9 years, meets the 3-year minimum" },
          "culture": { "matched": [], "missing": ["enthusiastic", "persistent"] }
        },
        "quirk": "Assistant to the regional backend engineer." }
    ],
    "near_miss": [],
    "near_misses_included": false
  },
  "proactive_offers_included": true,
  "proactive_offers": [
    { "rank": 1, "candidate_name": "Michael S.", "score": 71.7, "tier": "strong_match",
      "recommended_action": "proactive-offer" }
  ]
}
```
(Shortened: every entry has all the fields shown for Dwight.)

### POST /jobs
Adds a job. The response is the same as `GET /jobs/{job_id}/matches` for the new job, with status `201`.

| Field | Required | Type | Notes |
|---|---|---|---|
| `title` | yes | text | Unique within its company (`409` otherwise); may repeat across companies |
| `company` | no | text | The company posting the job; with the title, it identifies the job |
| `required_skills` | yes | list of text | At least one |
| `min_experience_years` | yes | whole number | 0 to 70 |
| `experience_requirement` | no | `"required"` (default) or `"preferred"` | `required`: below the minimum, no match. `preferred`: below it, the score drops and the match is at most `possible_match` (D-56). |
| `culture_keywords` | no | list of text | |
| `tagline` | no | text | Shown to candidates, never scored |

Skills and keywords are normalized, so `"Stakeholder Management"` and `"stakeholder-management"` are the same.

```bash
curl -X POST http://127.0.0.1:8000/jobs -H "Content-Type: application/json" \
  -d '{"title": "Data Detective", "required_skills": ["SQL", "Python"], "min_experience_years": 3, "culture_keywords": ["curious"]}'
```

### PATCH /jobs/{job_id}
Changes only the fields you send; the rest stay as they are. The response is the job's refreshed matches.

- The fields are the same as POST, all optional.
- A list you send **replaces** the stored list.
- `"tagline": null` or `"company": null` clears it. Required fields can't be cleared.
- An unknown field (such as a typo, `"titel"`) returns `422`.

```bash
curl -X PATCH http://127.0.0.1:8000/jobs/6 -H "Content-Type: application/json" -d '{"min_experience_years": 4}'
```

---

## Candidates

### GET /candidates
Lists every candidate, sorted by id, with their skills, traits and job preferences.

```bash
curl http://127.0.0.1:8000/candidates
```

```json
[
  { "candidate_id": 1, "name": "Sherlock H.", "experience_years": 8,
    "skills": ["deduction", "forensics", "pattern-recognition"], "traits": ["analytical", "blunt"], "job_preferences": [] }
]
```

### GET /candidates/{candidate_id}/matches
**The candidate's view:** the best jobs for one candidate, grouped into tiers.

**Order:**
1. Score.
2. Jobs where the candidate is `top_applicant`: no competing open candidate (scoring 50 or more for that job) scores higher.
3. The newest posting.
4. A neutral hash of the ids.

Each job entry also shows:

| Field | Meaning |
|---|---|
| `tagline` | The job's tagline, never scored |
| `top_applicant` | `true` when no competing candidate scores higher. Shown as a yes or no, never a count, to protect other candidates. |
| `matches_preference` | `true` when the job's title is one of the candidate's `job_preferences`. Shown only; it doesn't change the order. |

| Query option | Default | Effect |
|---|---|---|
| `explain` | `false` | Adds `score_breakdown` to every entry |

```bash
curl http://127.0.0.1:8000/candidates/7/matches
curl "http://127.0.0.1:8000/candidates/7/matches?explain=true"
```

```json
{
  "candidate_id": 7,
  "matches": {
    "strong_match": [
      { "rank": 1, "job_id": 3, "job_title": "Developer Relations Lead", "score": 90.0,
        "reason": "...", "evidence": { "...": "..." },
        "tagline": "...", "top_applicant": true, "matches_preference": false }
    ],
    "possible_match": [
      { "rank": 2, "job_id": 6, "job_title": "Sales Engineer", "score": 55.0, "...": "..." }
    ],
    "near_miss": [],
    "near_misses_included": false
  }
}
```

### POST /candidates
Adds a candidate. The response is the same as `GET /candidates/{candidate_id}/matches` for the new candidate, with status `201`.

| Field | Required | Type | Notes |
|---|---|---|---|
| `name` | yes | text | May repeat: people share names |
| `email` | no | text | Identifies the person; unique when present (`409` otherwise), stored in lower case |
| `skills` | yes | list of text | At least one |
| `experience_years` | yes | whole number | Total career years, 0 to 70 |
| `availability` | yes | text | `"Immediate"`, a delay such as `"2 weeks"`, `"10 days"` or `"1 month"`, or `"Not looking"` |
| `traits` | no | list of text | Matched against jobs' culture keywords |
| `quirk` | no | text | Shown to recruiters, never scored |
| `job_preferences` | no | list of text | Job titles the candidate wants; used to order their jobs |

A delay is turned into a start date when the candidate is added, and it never moves after that.

```bash
curl -X POST http://127.0.0.1:8000/candidates -H "Content-Type: application/json" \
  -d '{"name": "Jordan", "skills": ["Crisis Management", "Strategy", "Persuasion"], "experience_years": 6, "availability": "2 weeks", "traits": ["Calm", "Decisive"]}'
```

### PATCH /candidates/{candidate_id}
Changes only the fields you send. The response is the candidate's refreshed matches.

- The fields are the same as POST, all optional.
- A list you send **replaces** the stored list.
- `"quirk": null`, `"email": null` or `"job_preferences": null` clears it. Required fields can't be cleared.
- An unknown field returns `422`.

```bash
curl -X PATCH http://127.0.0.1:8000/candidates/7 -H "Content-Type: application/json" \
  -d '{"job_preferences": ["Sales Engineer"]}'
```

---

## Taxonomy

### GET /taxonomy/suggestions
What the optional model stage concluded about words the rules couldn't place (D-54).

| Field | Meaning |
|---|---|
| `model_linking` | `"on"`, `"off"` (`MODEL_LINKING=off`) or `"unavailable"` (libraries or model files missing) |
| `reason` | Why, when it isn't on |
| `linked` | Words that earn capped "suggested" credit (0.25) toward a concept, with the model scores behind each |
| `review` | Words waiting for a person: up to 3 suggested concepts, best first |
| `approved` | Words a person confirmed: full synonym credit |
| `rejected` | Words a person rejected: no credit, never suggested again |

A word moves from `review` to full credit when a person approves it (below), or when it's added to `seed/taxonomy.json`.

```bash
curl http://127.0.0.1:8000/taxonomy/suggestions
```

```json
{
  "model_linking": "on",
  "reason": "",
  "linked": [],
  "review": [
    { "concept_type": "trait", "term": "fast-paced", "suggestions": ["enthusiasm", "intensity", "recklessness"],
      "evidence": "best enthusiasm via 'energetic': mutual entailment 0.99, similarity 0.85" }
  ]
}
```

### POST /taxonomy/suggestions/{type}/{term}/approve
A person confirms what an unknown word means (D-55). `type` is `skill` or `trait`.
- **From that moment,** the word earns full synonym credit for every record that uses it, and for every later one. Affected matches are refreshed straight away.
- **The approval survives reseeds.**

| Body field | Required | Meaning |
|---|---|---|
| `concept` | no | The concept slug the word means. Leave the body out to accept the model's own best concept. |

```bash
curl -X POST http://127.0.0.1:8000/taxonomy/suggestions/skill/bargaining/approve \
  -H "Content-Type: application/json" -d '{"concept": "negotiation"}'
```

```json
{ "concept_type": "skill", "term": "bargaining", "outcome": "approved", "concept": "negotiation",
  "evidence": "approved by a person; the model had said review" }
```

Errors:
- `404`: no candidate or job uses the word;
- `409`: it's already a taxonomy label;
- `422`: an unknown concept or type, or no concept given when the model had none.

No login: this would be for administrators only in production.

### POST /taxonomy/suggestions/{type}/{term}/reject
A person says the model's guess is wrong. The word loses any suggested credit, is never suggested again, and affected matches are refreshed straight away. The errors are the same as for approve.

```bash
curl -X POST http://127.0.0.1:8000/taxonomy/suggestions/skill/crisis-handling/reject
```
