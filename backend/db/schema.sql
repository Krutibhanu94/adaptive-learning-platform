-- DROP TABLE IF EXISTS interaction_log CASCADE;
-- DROP TABLE IF EXISTS problem_attempts CASCADE;
-- DROP TABLE IF EXISTS student_skill_state CASCADE;
-- DROP TABLE IF EXISTS problems CASCADE;
-- DROP TABLE IF EXISTS topics CASCADE;
-- DROP TABLE IF EXISTS students CASCADE;
-- DROP TYPE IF EXISTS reasoning_state_enum CASCADE;
-- DROP TYPE IF EXISTS submit_result_enum CASCADE;

CREATE TABLE IF NOT EXISTS Students (
    student_id SERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    student_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS Topics (
    topic_id SERIAL PRIMARY KEY,
    topic_name TEXT NOT NULL UNIQUE,
    topic_description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS Problems (
    problem_id SERIAL PRIMARY KEY,
    tier INT NOT NULL,
    problem_name TEXT NOT NULL,
    problem_description TEXT NOT NULL,
    test_cases JSONB NOT NULL,
    starter_code TEXT,
    entry_point TEXT,
    -- Imports and helper class/function definitions (List/Optional typing imports,
    -- ListNode/TreeNode, inf = float('inf'), etc.) that starter_code and test_cases
    -- assume are already in scope -- sourced from the dataset's own "prompt" field.
    -- Needed for the correctness checker's harness to actually run problems that use
    -- these structures; without it, e.g. any linked-list/tree problem fails outright.
    test_harness_prelude TEXT,
    -- The dataset's own correctness-check function (a `check(candidate)` with a
    -- sequence of asserts), sourced from its "test" field. This is the actual
    -- correctness mechanism the checker runs -- test_cases (the input/output pairs
    -- above) turned out insufficient on their own: they don't know to wrap arguments
    -- like linked lists via the prelude's list_node()/is_same_list() helpers, which
    -- check(candidate) already does correctly per-problem. test_cases is kept for its
    -- own separate purpose -- showing example cases to students in the test-output
    -- panel -- not for checking correctness.
    test_harness TEXT,
    topic_id INT REFERENCES Topics(topic_id)
);

CREATE TYPE reasoning_state_enum AS ENUM ('genuine', 'bypass', 'none');

CREATE TYPE submit_result_enum AS ENUM ('pass', 'fail', 'partial', 'no_submission');

-- One row per "Problem Attempt" (opening a problem starts a new attempt).
-- tier/hint_cap are a snapshot of Student_Skill_State taken when the attempt
-- opens; hint-cap tapering trends are computed by comparing this snapshot
-- across successive attempt rows for the same student/topic/tier.
CREATE TABLE IF NOT EXISTS Problem_Attempts (
    attempt_id SERIAL PRIMARY KEY,
    student_id INT REFERENCES Students(student_id),
    problem_id INT REFERENCES Problems(problem_id),
    topic_id INT REFERENCES Topics(topic_id),
    tier INT NOT NULL,
    hint_cap INT NOT NULL,
    hints_used INT NOT NULL DEFAULT 0,
    -- Sticky flags: once true, they stay true for the rest of the attempt.
    -- engagement_occurred gates Submit (at least one genuine probe/evaluate
    -- exchange, regardless of its genuine/bypass classification).
    engagement_occurred BOOLEAN NOT NULL DEFAULT FALSE,
    struggle_detected BOOLEAN NOT NULL DEFAULT FALSE,
    escalated BOOLEAN NOT NULL DEFAULT FALSE,
    escalation_reason TEXT,
    -- The canonical "has this attempt concluded" check is
    -- `result != 'no_submission'`, not `submitted_at IS NOT NULL` — result
    -- is strictly more informative (it also says what happened). submitted_at
    -- is kept purely as a timestamp (ordering/duration auditing): it can't be
    -- derived from Interaction_Log, since the "all tests pass, engagement
    -- already occurred -> straight to Submit" path can conclude an attempt
    -- without writing a new Interaction_Log row.
    result submit_result_enum NOT NULL DEFAULT 'no_submission',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    submitted_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS Student_Skill_State (
    student_id INT REFERENCES Students(student_id),
    topic_id INT REFERENCES Topics(topic_id),
    PRIMARY KEY (student_id, topic_id),
    current_tier INT NOT NULL,
    mastery_score FLOAT NOT NULL,
    dependency_score FLOAT NOT NULL,
    -- Replaces the old rolling hint_trend average. Resets to a starting
    -- value on entering a new tier; tapers toward zero as decide observes
    -- genuine improvement across successive same-tier attempts.
    hint_cap INT NOT NULL DEFAULT 3,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS Interaction_Log (
    log_id SERIAL PRIMARY KEY,
    attempt_id INT REFERENCES Problem_Attempts(attempt_id),
    reasoning_state reasoning_state_enum NOT NULL,
    -- The test-check outcome (if any) associated with this specific turn —
    -- e.g. a Run Test click that grounded this turn's probe. 'no_submission'
    -- is the sentinel for ordinary conversational turns. This is distinct
    -- from Problem_Attempts.result, which is the single final outcome set
    -- once, when Submit closes the attempt.
    submit_result submit_result_enum NOT NULL,
    non_progress_flag BOOLEAN NOT NULL,
    turn_number INT NOT NULL,
    hints_used_this_turn INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    mastery_score FLOAT NOT NULL,
    dependency_score FLOAT NOT NULL,
    current_tier INT NOT NULL,
    turn_summary TEXT NOT NULL,
    -- Nullable: most turns under the conditionally-routed design (a probe,
    -- a check-in, a hint) have no test run associated with them at all.
    run_test_result JSONB,
    student_id INT REFERENCES Students(student_id),
    problem_id INT REFERENCES Problems(problem_id),
    topic_id INT REFERENCES Topics(topic_id)
);

-- Supports decide's per-attempt aggregates (e.g. bypass_count), which query
-- Interaction_Log scoped to a single attempt rather than the last N rows
-- across all attempts.
CREATE INDEX IF NOT EXISTS idx_interaction_log_attempt_id ON Interaction_Log(attempt_id);
