-- Stored matches (D-37): everything the API returns, so reads never recompute.


-- A job with no culture keywords has no culture score (D-32).
ALTER TABLE matches ALTER COLUMN culture_score DROP NOT NULL;

ALTER TABLE matches
    ADD COLUMN matched_skills TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN missing_skills TEXT[] NOT NULL DEFAULT '{}';
