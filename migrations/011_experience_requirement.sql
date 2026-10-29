-- Whether a job's minimum experience is a hard requirement or a preference (D-56).
--
-- preferred: below the minimum, the score drops in proportion and the match is at most a possible_match.
-- required:  below the minimum, there is no match at all, like a missing skill set (D-12).
-- The job owner decides; the seed data doesn't say, so every job starts as preferred.

ALTER TABLE jobs
    ADD COLUMN experience_requirement TEXT NOT NULL DEFAULT 'preferred',
    ADD CONSTRAINT jobs_experience_requirement_ck CHECK (experience_requirement IN ('required', 'preferred'));
