-- Names and titles stop being unique (D-53): two people can share a name, and two companies can post the same title.
--
-- candidates: identity is the optional email, unique when present (NULLs never clash).
-- jobs:       identity is the optional company together with the title, unique when the company is present.
-- both:       source_key, always filled, is the internal key the writers and the seed use to recognise a record:
--             'seed:<slug>' for seed records, 'api:<random id>' for records added through the API.

ALTER TABLE candidates
    DROP CONSTRAINT candidates_slug_uq,
    ADD COLUMN email      TEXT,
    ADD COLUMN source_key TEXT;

-- Every existing row came from the seed or from the API under the old one-name rule, so its slug was unique.
UPDATE candidates SET source_key = 'seed:' || slug;

ALTER TABLE candidates
    ALTER COLUMN source_key SET NOT NULL,
    ADD CONSTRAINT candidates_source_key_uq UNIQUE (source_key),
    ADD CONSTRAINT candidates_email_uq      UNIQUE (email),
    ADD CONSTRAINT candidates_email_ck      CHECK (email = lower(btrim(email)) AND email LIKE '%_@_%');

ALTER TABLE jobs
    DROP CONSTRAINT jobs_slug_uq,
    ADD COLUMN company    TEXT,
    ADD COLUMN source_key TEXT;

UPDATE jobs SET source_key = 'seed:' || slug;

ALTER TABLE jobs
    ALTER COLUMN source_key SET NOT NULL,
    ADD CONSTRAINT jobs_source_key_uq UNIQUE (source_key),
    ADD CONSTRAINT jobs_company_ck    CHECK (btrim(company) <> '');

-- The composite key: one title per company, ignoring the company's letter case.
CREATE UNIQUE INDEX jobs_company_title_uq ON jobs (lower(company), slug);
