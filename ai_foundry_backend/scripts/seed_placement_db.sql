-- scripts/seed_placement_db.sql
-- Empty test schema for ATOM DATA FOUNDRY (PostgreSQL). Contains no rows: the platform generates the data.
-- Run against a disposable database, e.g.:  psql -U postgres -c "CREATE DATABASE placement_test_db"
--                                            psql -U postgres -d placement_test_db -f scripts/seed_placement_db.sql

CREATE TABLE IF NOT EXISTS universities (
  university_id SERIAL PRIMARY KEY,
  name VARCHAR(120) NOT NULL UNIQUE,
  city VARCHAR(80) NOT NULL,
  country VARCHAR(60) NOT NULL,
  established_year INTEGER NOT NULL CHECK (established_year BETWEEN 1800 AND 2025),
  contact_email VARCHAR(120) NOT NULL
);

CREATE TABLE IF NOT EXISTS departments (
  department_id SERIAL PRIMARY KEY,
  university_id INTEGER NOT NULL REFERENCES universities(university_id),
  name VARCHAR(100) NOT NULL,
  head_name VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS students (
  student_id VARCHAR(12) PRIMARY KEY,
  university_id INTEGER NOT NULL REFERENCES universities(university_id),
  department_id INTEGER NOT NULL REFERENCES departments(department_id),
  full_name VARCHAR(100) NOT NULL,
  email VARCHAR(120) NOT NULL UNIQUE,
  phone VARCHAR(20),
  enrolment_year INTEGER NOT NULL CHECK (enrolment_year >= 2015),
  is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS placement_providers (
  provider_id SERIAL PRIMARY KEY,
  name VARCHAR(120) NOT NULL UNIQUE,
  industry VARCHAR(60) NOT NULL,
  city VARCHAR(80) NOT NULL,
  contact_email VARCHAR(120) NOT NULL,
  phone VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS supervisors (
  supervisor_id VARCHAR(12) PRIMARY KEY,
  provider_id INTEGER NOT NULL REFERENCES placement_providers(provider_id),
  full_name VARCHAR(100) NOT NULL,
  email VARCHAR(120) NOT NULL UNIQUE,
  is_authorized BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS placements (
  placement_id VARCHAR(12) PRIMARY KEY,
  student_id VARCHAR(12) NOT NULL REFERENCES students(student_id),
  provider_id INTEGER NOT NULL REFERENCES placement_providers(provider_id),
  supervisor_id VARCHAR(12) NOT NULL REFERENCES supervisors(supervisor_id),
  role_title VARCHAR(100) NOT NULL,
  start_date DATE NOT NULL,
  end_date DATE,
  status VARCHAR(20) NOT NULL CHECK (status IN ('ACTIVE','COMPLETED','CANCELLED'))
);

CREATE TABLE IF NOT EXISTS timesheets (
  timesheet_id VARCHAR(12) PRIMARY KEY,
  placement_id VARCHAR(12) NOT NULL REFERENCES placements(placement_id),
  student_id VARCHAR(12) NOT NULL REFERENCES students(student_id),
  week_start DATE NOT NULL,
  hours_worked NUMERIC(5,2) NOT NULL CHECK (hours_worked >= 0 AND hours_worked <= 60),
  status VARCHAR(20) NOT NULL CHECK (status IN ('SUBMITTED','PENDING','APPROVED','REJECTED','QUERIED')),
  notes TEXT,
  submitted_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS timesheet_reviews (
  review_id SERIAL PRIMARY KEY,
  timesheet_id VARCHAR(12) NOT NULL REFERENCES timesheets(timesheet_id),
  supervisor_id VARCHAR(12) NOT NULL REFERENCES supervisors(supervisor_id),
  decision VARCHAR(20) NOT NULL CHECK (decision IN ('APPROVED','REJECTED','QUERIED')),
  reviewed_at TIMESTAMP NOT NULL,
  comment TEXT
);
