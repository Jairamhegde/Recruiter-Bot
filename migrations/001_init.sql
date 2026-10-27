-- Trigger function: keeps updated_at current
CREATE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;


-- Table: skills
CREATE TABLE skills (
    skill_id     BIGINT       GENERATED ALWAYS AS IDENTITY,
    slug         TEXT         NOT NULL,
    compact_key  TEXT         GENERATED ALWAYS AS (replace(slug, '-', '')) STORED,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT skills_pk             PRIMARY KEY (skill_id),
    CONSTRAINT skills_slug_uq        UNIQUE (slug),
    CONSTRAINT skills_compact_key_uq UNIQUE (compact_key),
    CONSTRAINT skills_slug_format_ck CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$')
);


-- Table: traits
CREATE TABLE traits (
    trait_id     BIGINT       GENERATED ALWAYS AS IDENTITY,
    slug         TEXT         NOT NULL,
    compact_key  TEXT         GENERATED ALWAYS AS (replace(slug, '-', '')) STORED,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT traits_pk             PRIMARY KEY (trait_id),
    CONSTRAINT traits_slug_uq        UNIQUE (slug),
    CONSTRAINT traits_compact_key_uq UNIQUE (compact_key),
    CONSTRAINT traits_slug_format_ck CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$')
);


-- Table: candidates
CREATE TABLE candidates (
    candidate_id           BIGINT       GENERATED ALWAYS AS IDENTITY,
    slug                   TEXT         NOT NULL,
    full_name              TEXT         NOT NULL,
    experience_years       SMALLINT     NOT NULL,
    open_to_opportunities  BOOLEAN      NOT NULL,
    available_from         DATE,
    quirk                  TEXT,
    created_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT candidates_pk              PRIMARY KEY (candidate_id),
    CONSTRAINT candidates_slug_uq         UNIQUE (slug),
    CONSTRAINT candidates_slug_format_ck  CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    CONSTRAINT candidates_full_name_ck    CHECK (btrim(full_name) <> ''),
    CONSTRAINT candidates_experience_ck   CHECK (experience_years BETWEEN 0 AND 70),
    CONSTRAINT candidates_availability_ck CHECK (
        (open_to_opportunities AND available_from IS NOT NULL)
        OR (NOT open_to_opportunities AND available_from IS NULL)
    )
);

CREATE TRIGGER candidates_set_updated_at
    BEFORE UPDATE ON candidates
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- Table: candidate_skills
CREATE TABLE candidate_skills (
    candidate_id  BIGINT  NOT NULL,
    skill_id      BIGINT  NOT NULL,

    CONSTRAINT candidate_skills_pk           PRIMARY KEY (candidate_id, skill_id),
    CONSTRAINT candidate_skills_candidate_fk FOREIGN KEY (candidate_id)
                                             REFERENCES candidates (candidate_id) ON DELETE CASCADE,
    CONSTRAINT candidate_skills_skill_fk     FOREIGN KEY (skill_id)
                                             REFERENCES skills (skill_id) ON DELETE RESTRICT
);

CREATE INDEX candidate_skills_skill_idx ON candidate_skills (skill_id);


-- Table: candidate_traits
CREATE TABLE candidate_traits (
    candidate_id  BIGINT  NOT NULL,
    trait_id      BIGINT  NOT NULL,

    CONSTRAINT candidate_traits_pk           PRIMARY KEY (candidate_id, trait_id),
    CONSTRAINT candidate_traits_candidate_fk FOREIGN KEY (candidate_id)
                                             REFERENCES candidates (candidate_id) ON DELETE CASCADE,
    CONSTRAINT candidate_traits_trait_fk     FOREIGN KEY (trait_id)
                                             REFERENCES traits (trait_id) ON DELETE RESTRICT
);

CREATE INDEX candidate_traits_trait_idx ON candidate_traits (trait_id);


-- Table: jobs
CREATE TABLE jobs (
    job_id                BIGINT       GENERATED ALWAYS AS IDENTITY,
    slug                  TEXT         NOT NULL,
    title                 TEXT         NOT NULL,
    min_experience_years  SMALLINT     NOT NULL,
    tagline               TEXT,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT jobs_pk                PRIMARY KEY (job_id),
    CONSTRAINT jobs_slug_uq           UNIQUE (slug),
    CONSTRAINT jobs_slug_format_ck    CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    CONSTRAINT jobs_title_ck          CHECK (btrim(title) <> ''),
    CONSTRAINT jobs_min_experience_ck CHECK (min_experience_years BETWEEN 0 AND 70)
);

CREATE TRIGGER jobs_set_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- Table: job_skills
CREATE TABLE job_skills (
    job_id    BIGINT  NOT NULL,
    skill_id  BIGINT  NOT NULL,

    CONSTRAINT job_skills_pk       PRIMARY KEY (job_id, skill_id),
    CONSTRAINT job_skills_job_fk   FOREIGN KEY (job_id)
                                   REFERENCES jobs (job_id) ON DELETE CASCADE,
    CONSTRAINT job_skills_skill_fk FOREIGN KEY (skill_id)
                                   REFERENCES skills (skill_id) ON DELETE RESTRICT
);

CREATE INDEX job_skills_skill_idx ON job_skills (skill_id);


-- Table: job_culture_traits
CREATE TABLE job_culture_traits (
    job_id    BIGINT  NOT NULL,
    trait_id  BIGINT  NOT NULL,

    CONSTRAINT job_culture_traits_pk       PRIMARY KEY (job_id, trait_id),
    CONSTRAINT job_culture_traits_job_fk   FOREIGN KEY (job_id)
                                           REFERENCES jobs (job_id) ON DELETE CASCADE,
    CONSTRAINT job_culture_traits_trait_fk FOREIGN KEY (trait_id)
                                           REFERENCES traits (trait_id) ON DELETE RESTRICT
);

CREATE INDEX job_culture_traits_trait_idx ON job_culture_traits (trait_id);


-- Table: matches
CREATE TABLE matches (
    job_id             BIGINT        NOT NULL,
    candidate_id       BIGINT        NOT NULL,
    skill_score        NUMERIC(4,3)  NOT NULL,
    experience_score   NUMERIC(4,3)  NOT NULL,
    culture_score      NUMERIC(4,3)  NOT NULL,
    score              NUMERIC(4,1)  NOT NULL,
    reason             TEXT          NOT NULL,
    algorithm_version  TEXT          NOT NULL,
    computed_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),

    CONSTRAINT matches_pk                  PRIMARY KEY (job_id, candidate_id),
    CONSTRAINT matches_job_fk              FOREIGN KEY (job_id)
                                           REFERENCES jobs (job_id) ON DELETE CASCADE,
    CONSTRAINT matches_candidate_fk        FOREIGN KEY (candidate_id)
                                           REFERENCES candidates (candidate_id) ON DELETE CASCADE,
    CONSTRAINT matches_skill_score_ck      CHECK (skill_score      BETWEEN 0 AND 1),
    CONSTRAINT matches_experience_score_ck CHECK (experience_score BETWEEN 0 AND 1),
    CONSTRAINT matches_culture_score_ck    CHECK (culture_score    BETWEEN 0 AND 1),
    CONSTRAINT matches_score_ck            CHECK (score            BETWEEN 0 AND 100)
);

CREATE INDEX matches_job_rank_idx       ON matches (job_id, score DESC);
CREATE INDEX matches_candidate_rank_idx ON matches (candidate_id, score DESC);


-- Table: ingestion_events
CREATE TABLE ingestion_events (
    event_id     BIGINT       GENERATED ALWAYS AS IDENTITY,
    entity_type  TEXT         NOT NULL,
    source       TEXT         NOT NULL,
    entity_slug  TEXT,
    payload      JSONB        NOT NULL,
    status       TEXT         NOT NULL,
    error        TEXT,
    received_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT ingestion_events_pk             PRIMARY KEY (event_id),
    CONSTRAINT ingestion_events_entity_type_ck CHECK (entity_type IN ('candidate', 'job')),
    CONSTRAINT ingestion_events_source_ck      CHECK (source IN ('seed', 'api')),
    CONSTRAINT ingestion_events_status_ck      CHECK (status IN ('accepted', 'rejected')),
    CONSTRAINT ingestion_events_error_ck       CHECK (
        (status = 'accepted' AND error IS NULL)
        OR (status = 'rejected' AND error IS NOT NULL)
    )
);

CREATE INDEX ingestion_events_received_idx ON ingestion_events (received_at DESC);
