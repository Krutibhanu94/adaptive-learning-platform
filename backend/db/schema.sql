CREATE TABLE IF NOT EXISTS Students (
    student_id SERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    student_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS Skills (
    skill_id SERIAL PRIMARY KEY,
    skill_name TEXT NOT NULL,
    skill_description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS Problems (
    problem_id SERIAL PRIMARY KEY,
    tier INT NOT NULL,
    problem_name TEXT NOT NULL,
    problem_description TEXT NOT NULL,
    test_cases JSONB NOT NULL,
    skill_id INT REFERENCES Skills(skill_id)
);

CREATE TABLE IF NOT EXISTS Student_Skill_State (
    PRIMARY KEY (student_id, skill_id),
    student_id INT REFERENCES Students(student_id),
    skill_id INT REFERENCES Skills(skill_id),
    current_tier INT NOT NULL,
    mastery_score FLOAT NOT NULL,
    dependency_score FLOAT NOT NULL,
    hint_trend FLOAT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS Interaction_Log (
    log_id SERIAL PRIMARY KEY,
    student_id INT REFERENCES Students(student_id),
    problem_id INT REFERENCES Problems(problem_id),
    skill_id INT REFERENCES Skills(skill_id),
    reasoning_state TEXT NOT NULL,
    correctness_result TEXT NOT NULL,
    non_progress_flag BOOLEAN NOT NULL,
    turn_number INT NOT NULL,
    hints_used_this_turn INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    mastery_score FLOAT NOT NULL,
    dependency_score FLOAT NOT NULL,
    current_tier INT NOT NULL,
    turn_summary TEXT NOT NULL
);