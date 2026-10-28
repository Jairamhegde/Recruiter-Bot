-- Candidate job preferences (D-47): stored now, not yet used in matching.
-- One row per preference, like skills and traits (D-20), so a future matching step can join on it.


-- Table: candidate_job_preferences
CREATE TABLE candidate_job_preferences (
    candidate_id  BIGINT  NOT NULL,
    preference    TEXT    NOT NULL,

    CONSTRAINT candidate_job_preferences_pk           PRIMARY KEY (candidate_id, preference),
    CONSTRAINT candidate_job_preferences_candidate_fk FOREIGN KEY (candidate_id)
                                                      REFERENCES candidates (candidate_id) ON DELETE CASCADE,
    CONSTRAINT candidate_job_preferences_format_ck    CHECK (preference ~ '^[a-z0-9]+(-[a-z0-9]+)*$')
);
