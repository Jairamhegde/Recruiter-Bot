-- Taxonomy relations (D-29, D-30): related or reviewed-unrelated concepts of the same type.
-- One directed row per pair; symmetric relations are stored both ways.


-- Table: concept_relations
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
