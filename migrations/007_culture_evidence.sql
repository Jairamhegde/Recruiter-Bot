-- Evidence for every match (D-50): which culture keywords a candidate matched or missed,
-- stored like matched_skills and missing_skills so the API never has to parse the reason text.

ALTER TABLE matches
    ADD COLUMN matched_culture TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN missing_culture TEXT[] NOT NULL DEFAULT '{}';
