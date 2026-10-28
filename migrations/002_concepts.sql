-- Taxonomy (D-29, D-30): ESCO-shaped concepts with preferred, alternative and hidden labels.


-- Table: concepts
CREATE TABLE concepts (
    concept_id       BIGINT       GENERATED ALWAYS AS IDENTITY,
    concept_type     TEXT         NOT NULL,
    slug             TEXT         NOT NULL,
    description      TEXT,
    esco_uri         TEXT,
    onet_element_id  TEXT,

    CONSTRAINT concepts_pk             PRIMARY KEY (concept_id),
    CONSTRAINT concepts_slug_uq        UNIQUE (concept_type, slug),
    -- Lets labels and relations reference (concept_id, concept_type) to stay within one type.
    CONSTRAINT concepts_id_type_uq     UNIQUE (concept_id, concept_type),
    CONSTRAINT concepts_type_ck        CHECK (concept_type IN ('skill', 'trait')),
    CONSTRAINT concepts_slug_format_ck CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$')
);


-- Table: concept_labels
CREATE TABLE concept_labels (
    concept_id    BIGINT  NOT NULL,
    concept_type  TEXT    NOT NULL,
    label         TEXT    NOT NULL,
    compact_key   TEXT    GENERATED ALWAYS AS (replace(label, '-', '')) STORED,
    label_type    TEXT    NOT NULL,

    -- One concept per label within a type, so a word never means two things.
    CONSTRAINT concept_labels_pk           PRIMARY KEY (concept_type, compact_key),
    CONSTRAINT concept_labels_concept_fk   FOREIGN KEY (concept_id, concept_type)
                                           REFERENCES concepts (concept_id, concept_type) ON DELETE CASCADE,
    CONSTRAINT concept_labels_type_ck      CHECK (label_type IN ('preferred', 'alternative', 'hidden')),
    CONSTRAINT concept_labels_format_ck    CHECK (label ~ '^[a-z0-9]+(-[a-z0-9]+)*$')
);

CREATE INDEX concept_labels_concept_idx ON concept_labels (concept_id);

-- Exactly one preferred label per concept; the loader checks that it exists.
CREATE UNIQUE INDEX concept_labels_one_preferred_uq ON concept_labels (concept_id) WHERE label_type = 'preferred';
