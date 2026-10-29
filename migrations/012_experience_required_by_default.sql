-- Minimum experience is a must for every job (D-56, revised): nothing is assumed to be negotiable.
-- 'preferred' stays available for a job owner who wants it later; it is no longer the default.

ALTER TABLE jobs ALTER COLUMN experience_requirement SET DEFAULT 'required';

UPDATE jobs SET experience_requirement = 'required' WHERE experience_requirement <> 'required';
