-- What the optional model stage concluded about words the rules couldn't place (D-54).
--
-- linked: confident enough to earn capped "suggested" credit toward concept_slug, never full synonym credit.
-- review: plausible but not confident; a person decides, using the suggestions (best first).
-- A word with no plausible concept gets no row and stays unknown, as before.

CREATE TABLE term_suggestions (
    concept_type   TEXT         NOT NULL,
    term           TEXT         NOT NULL,  -- the word's slug, as stored in skills or traits
    outcome        TEXT         NOT NULL,
    concept_slug   TEXT,                   -- for linked: the concept it earns suggested credit toward
    suggestions    TEXT[]       NOT NULL DEFAULT '{}',  -- for review: concept slugs, best first
    evidence       TEXT         NOT NULL,  -- the model scores behind the decision, in words
    model_version  TEXT         NOT NULL,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT term_suggestions_pk         PRIMARY KEY (concept_type, term),
    CONSTRAINT term_suggestions_type_ck    CHECK (concept_type IN ('skill', 'trait')),
    CONSTRAINT term_suggestions_outcome_ck CHECK (outcome IN ('linked', 'review')),
    CONSTRAINT term_suggestions_linked_ck  CHECK ((outcome = 'linked') = (concept_slug IS NOT NULL))
);
