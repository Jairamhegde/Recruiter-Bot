-- Deterministic linking of unknown words (D-41): root keys for indexed lookups, and an audit trail.


-- Root keys on the vocabulary, so grouping unknown words is an index lookup.
ALTER TABLE skills ADD COLUMN root_key TEXT;
ALTER TABLE traits ADD COLUMN root_key TEXT;
CREATE INDEX skills_root_key_idx ON skills (root_key);
CREATE INDEX traits_root_key_idx ON traits (root_key);


-- Concepts created by grouping are marked, so a review can tell them from curated ones.
ALTER TABLE concepts
    ADD COLUMN source TEXT NOT NULL DEFAULT 'curated',
    ADD CONSTRAINT concepts_source_ck CHECK (source IN ('curated', 'auto'));


-- Labels: their root key, and where an automatic one came from.
ALTER TABLE concept_labels
    ADD COLUMN root_key TEXT,
    ADD COLUMN source   TEXT NOT NULL DEFAULT 'curated',
    ADD COLUMN method   TEXT,
    ADD COLUMN evidence TEXT,
    ADD CONSTRAINT concept_labels_source_ck CHECK (source IN ('curated', 'auto')),
    ADD CONSTRAINT concept_labels_method_ck CHECK (
        (source = 'curated' AND method IS NULL)
        OR (source = 'auto' AND method IN ('root_key', 'typo', 'group'))
    );

CREATE INDEX concept_labels_root_key_idx ON concept_labels (concept_type, root_key);
