# Entity-Relationship Diagram

The schema in [`migrations/001_init.sql`](../migrations/001_init.sql), in third normal form (3NF). The diagram renders on GitHub.

```mermaid
erDiagram
    SKILLS {
        bigint      skill_id     PK
        text        slug         UK "normalized, e.g. systems-design"
        text        compact_key  UK "generated: slug without hyphens"
        timestamptz created_at
    }
    TRAITS {
        bigint      trait_id     PK
        text        slug         UK "shared by traits and culture keywords"
        text        compact_key  UK "generated"
        timestamptz created_at
    }
    CANDIDATES {
        bigint      candidate_id          PK
        text        slug                  UK
        text        full_name
        smallint    experience_years         "0-70"
        boolean     open_to_opportunities
        date        available_from           "NULL when not looking"
        text        quirk                    "display only"
        timestamptz created_at
        timestamptz updated_at
    }
    CANDIDATE_SKILLS {
        bigint candidate_id PK,FK
        bigint skill_id     PK,FK
    }
    CANDIDATE_TRAITS {
        bigint candidate_id PK,FK
        bigint trait_id     PK,FK
    }
    JOBS {
        bigint      job_id               PK
        text        slug                 UK
        text        title
        smallint    min_experience_years    "0-70"
        text        tagline                 "display only"
        timestamptz created_at
        timestamptz updated_at
    }
    JOB_SKILLS {
        bigint job_id   PK,FK
        bigint skill_id PK,FK
    }
    JOB_CULTURE_TRAITS {
        bigint job_id   PK,FK
        bigint trait_id PK,FK
    }
    MATCHES {
        bigint      job_id            PK,FK
        bigint      candidate_id      PK,FK
        numeric     skill_score          "0-1"
        numeric     experience_score     "0-1"
        numeric     culture_score        "0-1"
        numeric     score                "0-100, derived"
        text        reason               "derived"
        text        algorithm_version
        timestamptz computed_at
    }
    INGESTION_EVENTS {
        bigint      event_id    PK
        text        entity_type    "candidate | job"
        text        source         "seed | api"
        text        entity_slug
        jsonb       payload        "raw input as received"
        text        status         "accepted | rejected"
        text        error
        timestamptz received_at
    }

    CANDIDATES ||--o{ CANDIDATE_SKILLS   : has
    SKILLS     ||--o{ CANDIDATE_SKILLS   : "held by"
    CANDIDATES ||--o{ CANDIDATE_TRAITS   : has
    TRAITS     ||--o{ CANDIDATE_TRAITS   : "describes"

    JOBS       ||--|{ JOB_SKILLS         : requires
    SKILLS     ||--o{ JOB_SKILLS         : "required by"
    JOBS       ||--o{ JOB_CULTURE_TRAITS : "looks for"
    TRAITS     ||--o{ JOB_CULTURE_TRAITS : "wanted by"

    JOBS       ||--o{ MATCHES            : "ranked in"
    CANDIDATES ||--o{ MATCHES            : "ranked in"
```

## Reading the diagram

| Symbol | Meaning |
|---|---|
| `\|\|--o{` | one to zero-or-many |
| `\|\|--\|{` | one to one-or-many (a job has at least one required skill, enforced by the ingest code) |
| PK / FK / UK | primary key / foreign key / unique key |

## Normal form, table by table

| Table | Key | Form | Why |
|---|---|---|---|
| `skills`, `traits` | surrogate id; `slug` and `compact_key` are also unique | 3NF | `compact_key` depends on `slug`, which is itself a key, so it doesn't break 3NF. It's generated, so it can't drift. |
| `candidates`, `jobs` | surrogate id; `slug` is also unique | 3NF | Every column describes the candidate or job, and nothing else |
| `candidate_skills`, `candidate_traits`, `job_skills`, `job_culture_traits` | composite key | 3NF | Link tables with no other columns |
| `matches` | `(job_id, candidate_id)` | **Not 3NF, deliberately** | `score` and `reason` are derived from other tables. It's a cache of computed results, rebuilt on ingest, and `algorithm_version` records which formula produced each row. |
| `ingestion_events` | `event_id` | Log, outside the model | The raw JSON payload is kept exactly as received; nothing reads it for matching |

## Rules that live in the database

- **Availability is consistent:** `open_to_opportunities = false` requires `available_from IS NULL`, and `true` requires a date.
- **Slugs are well-formed:** lowercase words joined by single hyphens, enforced by `CHECK`.
- **No duplicate skills in different spellings:** `compact_key` is unique, so `team-building` and `teambuilding` can't both exist.
- **Skills in use can't be deleted:** link tables use `ON DELETE RESTRICT` on `skill_id` and `trait_id`. Deleting a candidate or job removes their links (`CASCADE`).
- **`updated_at` is always current:** set by a trigger, not by application code.
