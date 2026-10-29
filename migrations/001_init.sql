-- concepts: the base meanings that skill and trait words name
CREATE TABLE concepts (
    concept_id    BIGINT  GENERATED ALWAYS AS IDENTITY,
    concept_type  TEXT    NOT NULL,
    slug          TEXT    NOT NULL,
    description   TEXT,
    esco_uri      TEXT,

    CONSTRAINT concepts_pk             PRIMARY KEY (concept_id),
    CONSTRAINT concepts_slug_uq        UNIQUE (concept_type, slug),
    CONSTRAINT concepts_id_type_uq     UNIQUE (concept_id, concept_type),
    CONSTRAINT concepts_type_ck        CHECK (concept_type IN ('skill', 'trait')),
    CONSTRAINT concepts_slug_format_ck CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$')
);


-- concept_labels: every word that names a concept, including the concept's own name
CREATE TABLE concept_labels (
    concept_id    BIGINT  NOT NULL,
    concept_type  TEXT    NOT NULL,
    label         TEXT    NOT NULL,
    compact_label TEXT    GENERATED ALWAYS AS (replace(label, '-', '')) STORED,

    CONSTRAINT concept_labels_pk         PRIMARY KEY (concept_type, label),
    CONSTRAINT concept_labels_compact_uq UNIQUE (concept_type, compact_label),
    CONSTRAINT concept_labels_concept_fk FOREIGN KEY (concept_id, concept_type)
                                         REFERENCES concepts (concept_id, concept_type) ON DELETE CASCADE,
    CONSTRAINT concept_labels_format_ck  CHECK (label ~ '^[a-z0-9]+(-[a-z0-9]+)*$')
);

CREATE INDEX concept_labels_concept_idx ON concept_labels (concept_id);


-- concept_relations: pairs of related concepts and the partial credit they earn
CREATE TABLE concept_relations (
    from_concept_id  BIGINT        NOT NULL,
    to_concept_id    BIGINT        NOT NULL,
    concept_type     TEXT          NOT NULL,
    credit           NUMERIC(3,2)  NOT NULL,

    CONSTRAINT concept_relations_pk          PRIMARY KEY (from_concept_id, to_concept_id),
    CONSTRAINT concept_relations_from_fk     FOREIGN KEY (from_concept_id, concept_type)
                                             REFERENCES concepts (concept_id, concept_type) ON DELETE CASCADE,
    CONSTRAINT concept_relations_to_fk       FOREIGN KEY (to_concept_id, concept_type)
                                             REFERENCES concepts (concept_id, concept_type) ON DELETE CASCADE,
    CONSTRAINT concept_relations_not_self_ck CHECK (from_concept_id <> to_concept_id),
    CONSTRAINT concept_relations_credit_ck   CHECK (credit > 0 AND credit <= 1)
);

CREATE INDEX concept_relations_to_idx ON concept_relations (to_concept_id);


-- skills: every skill word in use, and the concept it means
CREATE TABLE skills (
    skill_id      BIGINT  GENERATED ALWAYS AS IDENTITY,
    slug          TEXT    NOT NULL,
    concept_id    BIGINT,
    concept_type  TEXT    NOT NULL DEFAULT 'skill',

    CONSTRAINT skills_pk             PRIMARY KEY (skill_id),
    CONSTRAINT skills_slug_uq        UNIQUE (slug),
    CONSTRAINT skills_slug_format_ck CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    CONSTRAINT skills_type_ck        CHECK (concept_type = 'skill'),
    CONSTRAINT skills_concept_fk     FOREIGN KEY (concept_id, concept_type)
                                     REFERENCES concepts (concept_id, concept_type) ON DELETE SET NULL (concept_id)
);

CREATE INDEX skills_concept_idx ON skills (concept_id);


-- traits: every trait and culture keyword in use, and the concept it means
CREATE TABLE traits (
    trait_id      BIGINT  GENERATED ALWAYS AS IDENTITY,
    slug          TEXT    NOT NULL,
    concept_id    BIGINT,
    concept_type  TEXT    NOT NULL DEFAULT 'trait',

    CONSTRAINT traits_pk             PRIMARY KEY (trait_id),
    CONSTRAINT traits_slug_uq        UNIQUE (slug),
    CONSTRAINT traits_slug_format_ck CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    CONSTRAINT traits_type_ck        CHECK (concept_type = 'trait'),
    CONSTRAINT traits_concept_fk     FOREIGN KEY (concept_id, concept_type)
                                     REFERENCES concepts (concept_id, concept_type) ON DELETE SET NULL (concept_id)
);

CREATE INDEX traits_concept_idx ON traits (concept_id);


-- candidates: one row per candidate profile
CREATE TABLE candidates (
    candidate_id           BIGINT       GENERATED ALWAYS AS IDENTITY,
    full_name              TEXT         NOT NULL,
    experience_years       SMALLINT     NOT NULL,
    open_to_opportunities  BOOLEAN      NOT NULL,
    available_from         DATE,
    quirk                  TEXT,
    created_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT candidates_pk              PRIMARY KEY (candidate_id),
    CONSTRAINT candidates_full_name_ck    CHECK (btrim(full_name) <> ''),
    CONSTRAINT candidates_experience_ck   CHECK (experience_years BETWEEN 0 AND 70),
    CONSTRAINT candidates_availability_ck CHECK (
        (open_to_opportunities AND available_from IS NOT NULL)
        OR (NOT open_to_opportunities AND available_from IS NULL)
    )
);


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


-- jobs: one row per job opening
CREATE TABLE jobs (
    job_id                  BIGINT       GENERATED ALWAYS AS IDENTITY,
    title                   TEXT         NOT NULL,
    min_experience_years    SMALLINT     NOT NULL,
    experience_requirement  TEXT         NOT NULL DEFAULT 'required',
    tagline                 TEXT,
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT jobs_pk                        PRIMARY KEY (job_id),
    CONSTRAINT jobs_title_ck                  CHECK (btrim(title) <> ''),
    CONSTRAINT jobs_min_experience_ck         CHECK (min_experience_years BETWEEN 0 AND 70),
    CONSTRAINT jobs_experience_requirement_ck CHECK (experience_requirement IN ('required', 'preferred'))
);


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


-- matches: the score, reason and evidence for every qualifying candidate-job pair
CREATE TABLE matches (
    job_id            BIGINT        NOT NULL,
    candidate_id      BIGINT        NOT NULL,
    skill_score       NUMERIC(4,3)  NOT NULL,
    experience_score  NUMERIC(4,3)  NOT NULL,
    culture_score     NUMERIC(4,3),
    score             NUMERIC(4,1)  NOT NULL,
    reason            TEXT          NOT NULL,
    matched_skills    TEXT[]        NOT NULL DEFAULT '{}',
    missing_skills    TEXT[]        NOT NULL DEFAULT '{}',
    matched_culture   TEXT[]        NOT NULL DEFAULT '{}',
    missing_culture   TEXT[]        NOT NULL DEFAULT '{}',
    computed_at       TIMESTAMPTZ   NOT NULL DEFAULT now(),

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


-- seed_runs: the seed files already loaded, so a restart never loads them twice
CREATE TABLE seed_runs (
    filename   TEXT         NOT NULL,
    loaded_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT seed_runs_pk PRIMARY KEY (filename)
);
