-- A person's decision on a word (D-55): the learning loop.
--
-- approved: the word means concept_slug; it earns full synonym credit from now on and survives every reseed.
-- rejected: the word is not that concept; the model stage never suggests it again.
-- linked and review stay the model's own conclusions, which every seed run recomputes (D-54).

ALTER TABLE term_suggestions
    DROP CONSTRAINT term_suggestions_outcome_ck,
    DROP CONSTRAINT term_suggestions_linked_ck,
    ADD COLUMN reviewed_at TIMESTAMPTZ,
    ADD CONSTRAINT term_suggestions_outcome_ck CHECK (outcome IN ('linked', 'review', 'approved', 'rejected')),
    ADD CONSTRAINT term_suggestions_concept_ck CHECK ((outcome IN ('linked', 'approved')) = (concept_slug IS NOT NULL)),
    ADD CONSTRAINT term_suggestions_reviewed_ck CHECK ((outcome IN ('approved', 'rejected')) = (reviewed_at IS NOT NULL));
