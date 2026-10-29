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


-- skills: every skill term in use, one row per normalized spelling
CREATE TABLE skills (
    skill_id     BIGINT       GENERATED ALWAYS AS IDENTITY,
    slug         TEXT         NOT NULL,
    compact_key  TEXT         GENERATED ALWAYS AS (replace(slug, '-', '')) STORED,
    root_key     TEXT,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT skills_pk             PRIMARY KEY (skill_id),
    CONSTRAINT skills_slug_uq        UNIQUE (slug),
    CONSTRAINT skills_compact_key_uq UNIQUE (compact_key),
    CONSTRAINT skills_slug_format_ck CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$')
);

CREATE INDEX skills_root_key_idx ON skills (root_key);


-- traits: every personality trait and culture keyword in use
CREATE TABLE traits (
    trait_id     BIGINT       GENERATED ALWAYS AS IDENTITY,
    slug         TEXT         NOT NULL,
    compact_key  TEXT         GENERATED ALWAYS AS (replace(slug, '-', '')) STORED,
    root_key     TEXT,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT traits_pk             PRIMARY KEY (trait_id),
    CONSTRAINT traits_slug_uq        UNIQUE (slug),
    CONSTRAINT traits_compact_key_uq UNIQUE (compact_key),
    CONSTRAINT traits_slug_format_ck CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$')
);

CREATE INDEX traits_root_key_idx ON traits (root_key);


-- candidates: one row per person; the optional email is their identity
CREATE TABLE candidates (
    candidate_id           BIGINT       GENERATED ALWAYS AS IDENTITY,
    source_key             TEXT         NOT NULL,
    slug                   TEXT         NOT NULL,
    full_name              TEXT         NOT NULL,
    email                  TEXT,
    experience_years       SMALLINT     NOT NULL,
    open_to_opportunities  BOOLEAN      NOT NULL,
    available_from         DATE,
    quirk                  TEXT,
    created_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT candidates_pk              PRIMARY KEY (candidate_id),
    CONSTRAINT candidates_source_key_uq   UNIQUE (source_key),
    CONSTRAINT candidates_email_uq        UNIQUE (email),
    CONSTRAINT candidates_slug_format_ck  CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    CONSTRAINT candidates_full_name_ck    CHECK (btrim(full_name) <> ''),
    CONSTRAINT candidates_email_ck        CHECK (email = lower(btrim(email)) AND email LIKE '%_@_%'),
    CONSTRAINT candidates_experience_ck   CHECK (experience_years BETWEEN 0 AND 70),
    CONSTRAINT candidates_availability_ck CHECK (
        (open_to_opportunities AND available_from IS NOT NULL)
        OR (NOT open_to_opportunities AND available_from IS NULL)
    )
);

CREATE TRIGGER candidates_set_updated_at
    BEFORE UPDATE ON candidates
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- candidate_skills: the skills each candidate has
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


-- candidate_traits: the traits each candidate has
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


-- candidate_job_preferences: roles a candidate wants; stored, not scored
CREATE TABLE candidate_job_preferences (
    candidate_id  BIGINT  NOT NULL,
    preference    TEXT    NOT NULL,

    CONSTRAINT candidate_job_preferences_pk           PRIMARY KEY (candidate_id, preference),
    CONSTRAINT candidate_job_preferences_candidate_fk FOREIGN KEY (candidate_id)
                                                      REFERENCES candidates (candidate_id) ON DELETE CASCADE,
    CONSTRAINT candidate_job_preferences_format_ck    CHECK (preference ~ '^[a-z0-9]+(-[a-z0-9]+)*$')
);


-- jobs: one row per opening; company plus title is its identity
CREATE TABLE jobs (
    job_id                  BIGINT       GENERATED ALWAYS AS IDENTITY,
    source_key              TEXT         NOT NULL,
    slug                    TEXT         NOT NULL,
    title                   TEXT         NOT NULL,
    company                 TEXT,
    min_experience_years    SMALLINT     NOT NULL,
    experience_requirement  TEXT         NOT NULL DEFAULT 'required',
    tagline                 TEXT,
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT jobs_pk                        PRIMARY KEY (job_id),
    CONSTRAINT jobs_source_key_uq             UNIQUE (source_key),
    CONSTRAINT jobs_slug_format_ck            CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    CONSTRAINT jobs_title_ck                  CHECK (btrim(title) <> ''),
    CONSTRAINT jobs_company_ck                CHECK (btrim(company) <> ''),
    CONSTRAINT jobs_min_experience_ck         CHECK (min_experience_years BETWEEN 0 AND 70),
    CONSTRAINT jobs_experience_requirement_ck CHECK (experience_requirement IN ('required', 'preferred'))
);

CREATE UNIQUE INDEX jobs_company_title_uq ON jobs (lower(company), slug);

CREATE TRIGGER jobs_set_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- job_skills: the skills each job requires
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


-- job_culture_traits: the culture keywords each job looks for
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


-- matches: the stored score, reason and evidence for every candidate-job pair
CREATE TABLE matches (
    job_id             BIGINT        NOT NULL,
    candidate_id       BIGINT        NOT NULL,
    skill_score        NUMERIC(4,3)  NOT NULL,
    experience_score   NUMERIC(4,3)  NOT NULL,
    culture_score      NUMERIC(4,3),
    score              NUMERIC(4,1)  NOT NULL,
    reason             TEXT          NOT NULL,
    matched_skills     TEXT[]        NOT NULL DEFAULT '{}',
    missing_skills     TEXT[]        NOT NULL DEFAULT '{}',
    matched_culture    TEXT[]        NOT NULL DEFAULT '{}',
    missing_culture    TEXT[]        NOT NULL DEFAULT '{}',
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


-- ingestion_events: every record received, accepted or rejected with its reason
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


-- concepts: ESCO-shaped skill and trait concepts
CREATE TABLE concepts (
    concept_id       BIGINT       GENERATED ALWAYS AS IDENTITY,
    concept_type     TEXT         NOT NULL,
    slug             TEXT         NOT NULL,
    description      TEXT,
    esco_uri         TEXT,
    onet_element_id  TEXT,
    source           TEXT         NOT NULL DEFAULT 'curated',

    CONSTRAINT concepts_pk             PRIMARY KEY (concept_id),
    CONSTRAINT concepts_slug_uq        UNIQUE (concept_type, slug),
    CONSTRAINT concepts_id_type_uq     UNIQUE (concept_id, concept_type),
    CONSTRAINT concepts_type_ck        CHECK (concept_type IN ('skill', 'trait')),
    CONSTRAINT concepts_slug_format_ck CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    CONSTRAINT concepts_source_ck      CHECK (source IN ('curated', 'auto'))
);


-- concept_labels: the words that name each concept; a word belongs to one concept per type
CREATE TABLE concept_labels (
    concept_id    BIGINT  NOT NULL,
    concept_type  TEXT    NOT NULL,
    label         TEXT    NOT NULL,
    compact_key   TEXT    GENERATED ALWAYS AS (replace(label, '-', '')) STORED,
    root_key      TEXT,
    label_type    TEXT    NOT NULL,
    source        TEXT    NOT NULL DEFAULT 'curated',
    method        TEXT,
    evidence      TEXT,

    CONSTRAINT concept_labels_pk           PRIMARY KEY (concept_type, compact_key),
    CONSTRAINT concept_labels_concept_fk   FOREIGN KEY (concept_id, concept_type)
                                           REFERENCES concepts (concept_id, concept_type) ON DELETE CASCADE,
    CONSTRAINT concept_labels_type_ck      CHECK (label_type IN ('preferred', 'alternative', 'hidden')),
    CONSTRAINT concept_labels_format_ck    CHECK (label ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    CONSTRAINT concept_labels_source_ck    CHECK (source IN ('curated', 'auto')),
    CONSTRAINT concept_labels_method_ck    CHECK (
        (source = 'curated' AND method IS NULL)
        OR (source = 'auto' AND method IN ('root_key', 'typo', 'group'))
    )
);

CREATE INDEX concept_labels_concept_idx  ON concept_labels (concept_id);
CREATE INDEX concept_labels_root_key_idx ON concept_labels (concept_type, root_key);

CREATE UNIQUE INDEX concept_labels_one_preferred_uq ON concept_labels (concept_id) WHERE label_type = 'preferred';


-- concept_relations: related or reviewed-unrelated concept pairs, stored both ways
CREATE TABLE concept_relations (
    from_concept_id  BIGINT        NOT NULL,
    to_concept_id    BIGINT        NOT NULL,
    concept_type     TEXT          NOT NULL,
    relation         TEXT          NOT NULL,
    credit           NUMERIC(3,2)  NOT NULL,

    CONSTRAINT concept_relations_pk          PRIMARY KEY (from_concept_id, to_concept_id),
    CONSTRAINT concept_relations_from_fk     FOREIGN KEY (from_concept_id, concept_type)
                                             REFERENCES concepts (concept_id, concept_type) ON DELETE CASCADE,
    CONSTRAINT concept_relations_to_fk       FOREIGN KEY (to_concept_id, concept_type)
                                             REFERENCES concepts (concept_id, concept_type) ON DELETE CASCADE,
    CONSTRAINT concept_relations_not_self_ck CHECK (from_concept_id <> to_concept_id),
    CONSTRAINT concept_relations_relation_ck CHECK (relation IN ('related', 'unrelated')),
    CONSTRAINT concept_relations_credit_ck   CHECK (credit BETWEEN 0 AND 1)
);

CREATE INDEX concept_relations_to_idx ON concept_relations (to_concept_id);


-- term_suggestions: model suggestions and reviewer decisions for unknown words
CREATE TABLE term_suggestions (
    concept_type   TEXT         NOT NULL,
    term           TEXT         NOT NULL,
    outcome        TEXT         NOT NULL,
    concept_slug   TEXT,
    suggestions    TEXT[]       NOT NULL DEFAULT '{}',
    evidence       TEXT         NOT NULL,
    model_version  TEXT         NOT NULL,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    reviewed_at    TIMESTAMPTZ,

    CONSTRAINT term_suggestions_pk          PRIMARY KEY (concept_type, term),
    CONSTRAINT term_suggestions_type_ck     CHECK (concept_type IN ('skill', 'trait')),
    CONSTRAINT term_suggestions_outcome_ck  CHECK (outcome IN ('linked', 'review', 'approved', 'rejected')),
    CONSTRAINT term_suggestions_concept_ck  CHECK ((outcome IN ('linked', 'approved')) = (concept_slug IS NOT NULL)),
    CONSTRAINT term_suggestions_reviewed_ck CHECK ((outcome IN ('approved', 'rejected')) = (reviewed_at IS NOT NULL))
);
