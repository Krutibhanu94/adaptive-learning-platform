-- DROP TABLE IF EXISTS interaction_log CASCADE;
-- DROP TABLE IF EXISTS student_skill_state CASCADE;
-- DROP TABLE IF EXISTS problems CASCADE;
-- DROP TABLE IF EXISTS topics CASCADE;
-- DROP TABLE IF EXISTS students CASCADE;
-- DROP TYPE IF EXISTS reasoning_state_enum CASCADE;
-- DROP TYPE IF EXISTS submit_result_enum CASCADE;

CREATE TABLE IF NOT EXISTS Students (
    student_id SERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    student_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS Topics (
    topic_id SERIAL PRIMARY KEY,
    topic_name TEXT NOT NULL,
    topic_description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS Problems (
    problem_id SERIAL PRIMARY KEY,
    tier INT NOT NULL,
    problem_name TEXT NOT NULL,
    problem_description TEXT NOT NULL,
    test_cases JSONB NOT NULL,
    topic_id INT REFERENCES Topics(topic_id)
);

CREATE TABLE IF NOT EXISTS Student_Skill_State (
    student_id INT REFERENCES Students(student_id),
    topic_id INT REFERENCES Topics(topic_id),
    PRIMARY KEY (student_id, topic_id),
    current_tier INT NOT NULL,
    mastery_score FLOAT NOT NULL,
    dependency_score FLOAT NOT NULL,
    hint_trend FLOAT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TYPE reasoning_state_enum AS ENUM ('genuine', 'bypass', 'none');

CREATE TYPE submit_result_enum AS ENUM ('pass', 'fail', 'partial', 'no_submission');

CREATE TABLE IF NOT EXISTS Interaction_Log (
    log_id SERIAL PRIMARY KEY,
    reasoning_state reasoning_state_enum NOT NULL,
    submit_result submit_result_enum NOT NULL,
    non_progress_flag BOOLEAN NOT NULL,
    turn_number INT NOT NULL,
    hints_used_this_turn INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    mastery_score FLOAT NOT NULL,
    dependency_score FLOAT NOT NULL,
    current_tier INT NOT NULL,
    turn_summary TEXT NOT NULL,
    run_test_result JSONB NOT NULL,
    student_id INT REFERENCES Students(student_id),
    problem_id INT REFERENCES Problems(problem_id),
    topic_id INT REFERENCES Topics(topic_id)
);