-- Runs in its own schema, so it never touches the app's tables in public.
CREATE SCHEMA IF NOT EXISTS sql_detective;
SET search_path TO sql_detective;

DROP TABLE IF EXISTS interviews;
DROP TABLE IF EXISTS applicants;
DROP TABLE IF EXISTS job_postings;
DROP TABLE IF EXISTS recruiters;


-- Schema and seed data exactly as given in the brief (loaded as-is, not redesigned).

CREATE TABLE recruiters (
    id INT PRIMARY KEY,
    name VARCHAR(100),
    region VARCHAR(50)
);

CREATE TABLE job_postings (
    id INT PRIMARY KEY,
    title VARCHAR(100),
    recruiter_id INT,
    department VARCHAR(50),
    opened_date DATE,
    status VARCHAR(20) -- 'open', 'closed', 'on_hold'
);

CREATE TABLE applicants (
    id INT PRIMARY KEY,
    full_name VARCHAR(100),
    email VARCHAR(100),
    source VARCHAR(50), -- nullable
    applied_date DATE
);

CREATE TABLE interviews (
    id INT PRIMARY KEY,
    applicant_id INT,
    job_posting_id INT,
    stage VARCHAR(20),      -- 'Screen', 'Technical', 'Final'
    scheduled_date DATE,
    outcome VARCHAR(20)     -- 'passed', 'failed', 'no_show', NULL (pending)
);

INSERT INTO recruiters VALUES
(1, 'Priya Shah', 'APAC'),
(2, 'Daniel Ortiz', 'NA'),
(3, 'Fatima Al-Sayed', 'EMEA'),
(4, 'Wei Zhang', 'APAC'),
(5, 'Grace Okafor', 'EMEA');

INSERT INTO job_postings VALUES
(1, 'Backend Engineer I', 1, 'Engineering', '2026-01-05', 'open'),
(2, 'Backend Engineer I', 2, 'Engineering', '2026-01-10', 'open'),
(3, 'Data Analyst', 3, 'Data', '2026-01-08', 'closed'),
(4, 'Backend Engineer II', 1, 'Engineering', '2026-02-01', 'open'),
(5, 'DevOps Engineer', 4, 'Infrastructure', '2026-01-20', 'open'),
(6, 'Data Analyst', 5, 'Data', '2026-02-05', 'on_hold'),
(7, 'Backend Engineer I', 2, 'Engineering', '2026-02-15', 'closed');

INSERT INTO applicants VALUES
(1, 'Ananya Rao', 'ananya.rao@mail.com', 'LinkedIn', '2026-01-06'),
(2, 'Ananya Rao', 'Ananya.Rao@mail.com', 'Referral', '2026-02-04'),
(3, 'Ben Turner', 'ben.turner@mail.com', 'Job Board', '2026-01-07'),
(4, 'Chloe Martin', 'chloe.martin@mail.com', NULL, '2026-01-09'),
(5, 'Devansh Patel', 'devansh.patel@mail.com', 'LinkedIn', '2026-01-11'),
(6, 'Elena Popescu', 'elena.popescu@mail.com', 'Referral', '2026-01-12'),
(7, 'Farid Haidari', 'farid.haidari@mail.com', 'Job Board', '2026-01-13'),
(8, 'Grace Lin', 'grace.lin@mail.com', 'LinkedIn', '2026-01-15'),
(9, 'Hassan Malik', 'hassan.malik@mail.com', NULL, '2026-01-16'),
(10, 'Isla Fraser', 'isla.fraser@mail.com', 'Referral', '2026-01-18'),
(11, 'Jonas Weber', 'jonas.weber@mail.com', 'Job Board', '2026-02-10');

INSERT INTO interviews VALUES
(1, 1, 1, 'Screen', '2026-01-10', 'passed'),
(2, 1, 1, 'Technical', '2026-01-15', 'passed'),
(3, 1, 1, 'Final', '2026-01-22', 'passed'),
(4, 2, 4, 'Screen', '2026-02-05', 'passed'),
(5, 3, 1, 'Screen', '2026-01-11', 'passed'),
(6, 3, 1, 'Technical', '2026-01-16', 'failed'),
(7, 3, 3, 'Final', '2026-01-28', 'passed'),
(8, 4, 1, 'Screen', '2026-01-12', 'passed'),
(9, 4, 1, 'Final', '2026-01-24', 'failed'),
(10, 5, 2, 'Screen', '2026-01-14', 'passed'),
(11, 5, 2, 'Technical', '2026-01-19', 'passed'),
(12, 5, 2, 'Final', '2026-01-25', 'passed'),
(13, 6, 2, 'Screen', '2026-01-15', 'passed'),
(14, 6, 2, 'Final', '2026-01-26', 'failed'),
(15, 7, 2, 'Screen', '2026-01-16', 'no_show'),
(16, 8, 4, 'Screen', '2026-02-03', 'passed'),
(17, 8, 4, 'Technical', '2026-02-08', 'passed'),
(18, 8, 4, 'Final', '2026-02-12', 'passed'),
(19, 9, 4, 'Screen', '2026-02-04', 'passed'),
(20, 9, 4, 'Final', '2026-02-14', 'passed'),
(21, 10, 5, 'Screen', '2026-01-22', 'passed'),
(22, 10, 5, 'Technical', '2026-01-28', NULL),
(23, 11, 7, 'Final', '2026-02-20', 'passed'),
(24, 6, 7, 'Final', '2026-02-21', 'failed');




-- 1. List all currently open job postings, along with the name of the recruiter who owns each one.
-- Left join, so an open posting still shows up if its recruiter is missing.
select j.id, j.title, r.name as recruiter
from job_postings j
left join recruiters r on j.recruiter_id = r.id
where j.status = 'open';


-- 2. For each job posting, how many applicants reached the Final interview stage?
select j.id as job_posting_id, j.title as job_title, count(distinct i.applicant_id) as final_stage_applicants
from job_postings j
left join interviews i on j.id = i.job_posting_id and i.stage = 'Final'
group by j.id, j.title
order by final_stage_applicants desc;


-- 3. Find every person who effectively applied to more than one job posting.
-- Applicants 1 and 2 are both 'Ananya Rao' and differ only in the email's letter case
-- (ananya.rao@ vs Ananya.Rao@), so they are treated as one person.
-- Strictly, the part of an email before the @ may be case-sensitive, but mail providers
-- treat it as case-insensitive in practice, and the matching name backs this up.
-- The applicants table has no job column, so a "job applied to" is a posting the person interviewed for.
with applicants_temp as (
    select lower(trim(a.email)) as email, count(distinct i.job_posting_id) as effective_applications
    from interviews i
    join applicants a on i.applicant_id = a.id
    group by lower(trim(a.email))
    having count(distinct i.job_posting_id) > 1
)
select temp.email, min(a.full_name) as full_name, string_agg(a.id::text, ', ' order by a.id) as applicant_ids, temp.effective_applications
from applicants a
join applicants_temp temp on lower(trim(a.email)) = temp.email
group by temp.email, temp.effective_applications
order by effective_applications desc;


-- 4. For each recruiter, compute their Final-stage conversion rate (passed ÷ total Final-stage
--    interviews), but only include recruiters with at least 3 Final-stage interviews.
-- A pending (NULL) outcome counts in the total but not as passed.
with recruiter_details as (
    select r.id, count(*) filter (where i.outcome = 'passed') as passed_count, count(*) as total_interviews
    from interviews i
    join job_postings j on i.job_posting_id = j.id
    join recruiters r on j.recruiter_id = r.id
    where i.stage = 'Final'
    group by r.id
    having count(*) >= 3
)
select r.id, r.name, round(rd.passed_count::numeric / rd.total_interviews, 2) as conversion_rate
from recruiters r
join recruiter_details rd on r.id = rd.id
order by conversion_rate desc;


-- 5. (Bonus) Using a window function, find the recruiter with the most successful placements
--    (passed at Final stage) per department.
-- TODO: my own answer goes here.
