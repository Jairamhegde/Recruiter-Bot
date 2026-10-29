# Demo: matching, with evidence

One job and eight candidates. Each candidate shows one rule of the matching algorithm.

## Run it

1. Start from a fresh database, so the ids below match:
   ```bash
   docker compose down -v
   docker compose up --build
   ```
2. Open http://127.0.0.1:8000/docs.
3. **POST /jobs** with:
   ```json
   {"title":"Partnerships Lead","required_skills":["Sales","Negotiation","Research"],"min_experience_years":4,"culture_keywords":["persistent","calm-under-pressure"],"tagline":"Close the deal, then read the fine print."}
   ```
4. **POST /candidates** once for each:
   ```json
   {"name":"Asha","skills":["Sales","Negotiation","Research"],"experience_years":6,"availability":"Immediate","traits":["Persistent"]}
   {"name":"Ben","skills":["Selling Products","Negotiation","Conduct Scholarly Research"],"experience_years":5,"availability":"2 weeks","traits":["Tenacious","Resilience"]}
   {"name":"Cara","skills":["Persuasion","Research"],"experience_years":5,"availability":"Immediate"}
   {"name":"Dev","skills":["Sales","Negotiation","Research"],"experience_years":2,"availability":"Immediate","traits":["Persistent"]}
   {"name":"Esha","skills":["Sales","Negotiation","Research"],"experience_years":12,"availability":"Not looking","traits":["Persistent","Calm under pressure"]}
   {"name":"Farah","skills":["Sales","Research"],"experience_years":5,"availability":"Immediate"}
   {"name":"Gopal","skills":["Sales","Research"],"experience_years":5,"availability":"1 month"}
   {"name":"Hana","skills":["Sales","Negotiation","Research"],"experience_years":3,"availability":"Immediate","traits":["Persistent"]}
   ```

## Best candidates for the job: `GET /jobs/7/matches`

| Candidate | Score | Where | What it shows |
|---|---|---|---|
| Ben | 97.5 | strong | **Synonyms:** no exact words, yet first. `selling-products` = sales, `tenacious` = persistent, `resilience` ≈ calm-under-pressure (½). |
| Asha | 95.0 | strong | Exact words, but only half the culture fit |
| Hana | 90.0 | possible | **1-year grace:** every skill, but 3 of 4 required years. Scored in proportion, capped at possible, and the reason says `(1y short)` |
| Farah | 66.7 | possible | **Tie-break:** same score as Gopal, but starts now |
| Dwight S. | 66.7 | possible | A seed candidate, matched to a job added later |
| Gopal | 66.7 | possible | Starts in a month, so after Farah |
| Cara | 55.0 | possible | **One skill, one requirement:** `persuasion` relates to sales and negotiation, but counts once (1.5/3, not 2/3) |
| Elle W. | 50.0 | possible | A seed candidate like Cara, but 1 year short: the same skills score 5 points less |
| Esha | 100.0 | `proactive_offers` | **Not looking**, but better than everyone who is: worth approaching |
| Dev | — | not listed | **Experience gate:** every skill, but 2 of 4 required years, more than the 1-year grace |

Every `reason` names its links, e.g. `sales = selling-products`, `sales ≈ persuasion ½`.

## Best jobs for a candidate: `GET /candidates/17/matches` (Ben)

| Rank | Job | Score | Top applicant |
|---|---|---|---|
| 1 | Partnerships Lead | 97.5 | yes |
| 2 | Sales Engineer | 71.7 | yes |
| 3 | Developer Relations Lead | 55.0 | no |

Look for:
- **The same score both ways:** 97.5 from the job's side and from Ben's.
- **Synonyms work on seed jobs too:** `sales = selling-products` and `persistent = tenacious` on Sales Engineer.
- **`top_applicant`** says where Ben leads (yes or no), without revealing other candidates' scores.
- **Incident Commander isn't listed:** Ben would be a near miss there (about 46), and near misses appear only when nothing reaches 50.
