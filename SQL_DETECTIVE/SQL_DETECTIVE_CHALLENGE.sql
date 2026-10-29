

DROP TABLE IF EXISTS interviews;
DROP TABLE IF EXISTS applicants;
DROP TABLE IF EXISTS job_postings;
DROP TABLE IF EXISTS recruiters;



CREATE TABLE recruiters (
    id      INT PRIMARY KEY,
    name    VARCHAR(100) NOT NULL,
    region  VARCHAR(20)             -- 'APAC', 'NA', 'EMEA'
);

CREATE TABLE job_postings (
    id            INT PRIMARY KEY,
    title         VARCHAR(100) NOT NULL,
    recruiter_id  INT,
    department    VARCHAR(50),
    posted_date   DATE,
    status        VARCHAR(20),      -- 'open', 'closed', 'on_hold'
    FOREIGN KEY (recruiter_id) REFERENCES recruiters (id)
);

CREATE TABLE applicants (
    id            INT PRIMARY KEY,
    name          VARCHAR(100) NOT NULL,
    email         VARCHAR(150),
    source        VARCHAR(30),      -- 'LinkedIn', 'Referral', 'Job Board', NULL
    applied_date  DATE
);

CREATE TABLE interviews (
    id               INT PRIMARY KEY,
    applicant_id     INT,
    job_posting_id   INT,
    stage            VARCHAR(20),   -- 'Screen', 'Technical', 'Final'
    scheduled_date   DATE,
    outcome          VARCHAR(20),   -- 'passed', 'failed', 'no_show', NULL (pending)
    FOREIGN KEY (applicant_id)   REFERENCES applicants (id),
    FOREIGN KEY (job_posting_id) REFERENCES job_postings (id)
);



INSERT INTO recruiters (id, name, region) VALUES
    (1, 'Priya Shah',      'APAC'),
    (2, 'Daniel Ortiz',    'NA'),
    (3, 'Fatima Al-Sayed', 'EMEA'),
    (4, 'Wei Zhang',       'APAC'),
    (5, 'Grace Okafor',    'EMEA');

INSERT INTO job_postings (id, title, recruiter_id, department, posted_date, status) VALUES
    (1, 'Backend Engineer I',  1, 'Engineering',    '2026-01-05', 'open'),
    (2, 'Backend Engineer I',  2, 'Engineering',    '2026-01-10', 'open'),
    (3, 'Data Analyst',        3, 'Data',           '2026-01-08', 'closed'),
    (4, 'Backend Engineer II', 1, 'Engineering',    '2026-02-01', 'open'),
    (5, 'DevOps Engineer',     4, 'Infrastructure', '2026-01-20', 'open'),
    (6, 'Data Analyst',        5, 'Data',           '2026-02-05', 'on_hold'),
    (7, 'Backend Engineer I',  2, 'Engineering',    '2026-02-15', 'closed');

INSERT INTO applicants (id, name, email, source, applied_date) VALUES
    (1,  'Ananya Rao',     'ananya.rao@mail.com',     'LinkedIn',  '2026-01-06'),
    (2,  'Ananya Rao',     'Ananya.Rao@mail.com',     'Referral',  '2026-02-04'),
    (3,  'Ben Turner',     'ben.turner@mail.com',     'Job Board', '2026-01-07'),
    (4,  'Chloe Martin',   'chloe.martin@mail.com',   NULL,        '2026-01-09'),
    (5,  'Devansh Patel',  'devansh.patel@mail.com',  'LinkedIn',  '2026-01-11'),
    (6,  'Elena Popescu',  'elena.popescu@mail.com',  'Referral',  '2026-01-12'),
    (7,  'Farid Haidari',  'farid.haidari@mail.com',  'Job Board', '2026-01-13'),
    (8,  'Grace Lin',      'grace.lin@mail.com',      'LinkedIn',  '2026-01-15'),
    (9,  'Hassan Malik',   'hassan.malik@mail.com',   NULL,        '2026-01-16'),
    (10, 'Isla Fraser',    'isla.fraser@mail.com',    'Referral',  '2026-01-18'),
    (11, 'Jonas Weber',    'jonas.weber@mail.com',    'Job Board', '2026-02-10');

INSERT INTO interviews (id, applicant_id, job_posting_id, stage, scheduled_date, outcome) VALUES
    (1,  1,  1, 'Screen',    '2026-01-10', 'passed'),
    (2,  1,  1, 'Technical', '2026-01-15', 'passed'),
    (3,  1,  1, 'Final',     '2026-01-22', 'passed'),
    (4,  2,  4, 'Screen',    '2026-02-05', 'passed'),
    (5,  3,  1, 'Screen',    '2026-01-11', 'passed'),
    (6,  3,  1, 'Technical', '2026-01-16', 'failed'),
    (7,  3,  3, 'Final',     '2026-01-28', 'passed'),
    (8,  4,  1, 'Screen',    '2026-01-12', 'passed'),
    (9,  4,  1, 'Final',     '2026-01-24', 'failed'),
    (10, 5,  2, 'Screen',    '2026-01-14', 'passed'),
    (11, 5,  2, 'Technical', '2026-01-19', 'passed'),
    (12, 5,  2, 'Final',     '2026-01-25', 'passed'),
    (13, 6,  2, 'Screen',    '2026-01-15', 'passed'),
    (14, 6,  2, 'Final',     '2026-01-26', 'failed'),
    (15, 7,  2, 'Screen',    '2026-01-16', 'no_show'),
    (16, 8,  4, 'Screen',    '2026-02-03', 'passed'),
    (17, 8,  4, 'Technical', '2026-02-08', 'passed'),
    (18, 8,  4, 'Final',     '2026-02-12', 'passed'),
    (19, 9,  4, 'Screen',    '2026-02-04', 'passed'),
    (20, 9,  4, 'Final',     '2026-02-14', 'passed'),
    (21, 10, 5, 'Screen',    '2026-01-22', 'passed'),
    (22, 10, 5, 'Technical', '2026-01-28', NULL),
    (23, 11, 7, 'Final',     '2026-02-20', 'passed'),
    (24, 6,  7, 'Final',     '2026-02-21', 'failed');

    



-- List all currently open job postings, along with the name of the recruiter who owns each 
-- one. 
select j.id,j.title,r.name as recruiter
from job_postings j
left join recruiters r on j.recruiter_id = r.id
WHERE j.status = 'open';


-- 2. For each job posting, how many applicants reached the Final interview stage? 
select j.id as job_postings_id, j.title as job_title, count(distinct i.applicant_id) as final_stage_applicants
from job_postings j
left join interviews i on j.id = i.job_posting_id and i.stage = 'Final'
group by j.id,j.title
order by final_stage_applicants desc;


--Find every person who effectively applied to more than one job posting.
-- assumed that Anany.Rao@... and ananya.rao@.. both are same, because gmail is not case sennsitive,it lowers each cahrector
-- so it may be a typo of the applicant. if both are different, then anany roa's visibilty will change 
-- in the query.

with applicants_temp as (
select lower(a.email) as email, count(DISTINCT i.job_posting_id) as effective_applications
from interviews i
join applicants a on i.applicant_id = a.id
group by lower(a.email)
having count(DISTINCT i.job_posting_id) > 1
)
select temp.email, min(a.name) as name, string_agg(a.id::text, ', ' order by a.id) as applicant_ids, temp.effective_applications
from applicants a
join applicants_temp temp  on lower(a.email) = temp.email
group by temp.email, temp.effective_applications
order by effective_applications desc;


-- For each recruiter, compute their Final-stage conversion rate (passed ÷ total Final-stage 
--interviews), but only include recruiters with at least 3 Final-stage interviews.

with recruitor_details as (
    select r.id,count(*) filter(where i.outcome = 'passed') as passsed_count,count(*) as total_interviews
    from interviews i
    join job_postings j on i.job_posting_id = j.id
    join recruiters r on j.recruiter_id = r.id
    where i.stage = 'Final'
    group by r.id
    having count(*) >= 3
)
select r.id, r.name , round(rd.passsed_count::numeric/ rd.total_interviews,2) as conversion_rate
from recruiters r
join recruitor_details rd on r.id = rd.id
order by conversion_rate desc;



