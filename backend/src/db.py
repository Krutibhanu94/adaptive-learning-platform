from config import engine
from sqlalchemy import text
from dataclasses import dataclass
from enum import Enum
import json

class ReasoningState(Enum):
    GENUINE = "genuine"
    BYPASS = "bypass"
    NONE = "none"

class SubmitResult(Enum):
    PASS = "pass"
    FAIL = "fail"
    PARTIAL = "partial"
    NO_SUBMISSION = "no_submission"

@dataclass
class ProblemInsert:
    problem_name: str
    problem_description: str
    test_cases: list
    tier: int
    topic_id: int
    starter_code: str
    entry_point: str
    test_harness_prelude: str
    test_harness: str

@dataclass
class StudentSkillStateUpdate:
    student_id: int
    topic_id: int
    current_tier: int
    mastery_score: float
    dependency_score: float
    hint_cap: int
    updated_at: str

@dataclass
class InteractionLogEntry:
    student_id: int
    problem_id: int
    topic_id: int
    attempt_id: int
    reasoning_state: ReasoningState
    submit_result: SubmitResult
    non_progress_flag: bool
    turn_number: int
    hints_used_this_turn: int
    mastery_score: float
    dependency_score: float
    current_tier: int
    turn_summary: str
    run_test_result: dict | None
    log_id: int | None = None
    created_at: str | None = None

@dataclass
class ProblemAttemptInsert:
    student_id: int
    problem_id: int
    topic_id: int
    tier: int
    hint_cap: int

@dataclass
class ProblemAttemptUpdate:
    attempt_id: int
    result: SubmitResult
    escalated: bool = False
    escalation_reason: str | None = None

def get_student(student_id: int):
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM students WHERE student_id = :student_id"), {"student_id": student_id})
        student = result.fetchone()
        return dict(student._mapping) if student else None

def insert_student(student_name: str, username: str):
    with engine.connect() as conn:
        result = conn.execute(
            text("INSERT INTO students (username, student_name) VALUES (:student_name, :username) ON CONFLICT (username) DO NOTHING"),
            {"username": username, "student_name": student_name}
        )
        conn.commit()

def get_topics():
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM topics"))
        topics = result.fetchall()
        return [dict(topic._mapping) for topic in topics]

def insert_topic(topic_name: str, topic_description: str):
    with engine.connect() as conn:
        result = conn.execute(
            text("INSERT INTO topics (topic_name, topic_description) VALUES (:topic_name, :topic_description) ON CONFLICT (topic_name) DO NOTHING"),
            {"topic_name": topic_name, "topic_description": topic_description}
        )
        conn.commit()

def get_problem(problem_id: int):
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM problems WHERE problem_id = :problem_id"), {"problem_id": problem_id})
        problem = result.fetchone()
        return [dict(problem._mapping)] if problem else None

def insert_problem(problem_data: ProblemInsert):
    with engine.connect() as conn:
        conn.execute(
            text("""
            INSERT INTO problems (problem_name, problem_description, test_cases, tier, topic_id, starter_code, entry_point, test_harness_prelude, test_harness)
            VALUES (:problem_name, :problem_description, :test_cases, :tier, :topic_id, :starter_code, :entry_point, :test_harness_prelude, :test_harness)
            """),
            {
                "problem_name": problem_data.problem_name,
                "problem_description": problem_data.problem_description,
                "test_cases": problem_data.test_cases,
                "tier": problem_data.tier,
                "topic_id": problem_data.topic_id,
                "starter_code": problem_data.starter_code,
                "entry_point": problem_data.entry_point,
                "test_harness_prelude": problem_data.test_harness_prelude,
                "test_harness": problem_data.test_harness
            }
        )
        conn.commit()

def get_next_problem(student_id: int, topic_id: int, tier: int | None):
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT * FROM problems
                WHERE topic_id = :topic_id
                  AND tier = :tier
                  AND problem_id NOT IN (
                      SELECT problem_id FROM problem_attempts
                      WHERE student_id = :student_id
                        AND topic_id = :topic_id
                        AND result = :submit_result
                  )
                LIMIT 1
            """),
            {"student_id": student_id, "topic_id": topic_id, "tier": tier, "submit_result": SubmitResult.PASS.value}
        )
        next_problem = result.fetchone()
        return dict(next_problem._mapping) if next_problem else None

def get_topic_progress(student_id: int, topic_id: int):
    with engine.connect() as conn:
        result = conn.execute(
            text("""
            SELECT DISTINCT ON (p.problem_id) p.problem_id, p.problem_name,
                pa.result AS submit_result,
                COALESCE(pa.submitted_at, pa.started_at) AS created_at
            FROM problem_attempts pa
            JOIN problems p ON pa.problem_id = p.problem_id
            WHERE pa.student_id = :student_id
              AND pa.topic_id = :topic_id
            ORDER BY p.problem_id, pa.started_at DESC
            """),
            {"student_id": student_id, "topic_id": topic_id}
        )
        progress = result.fetchall()
        return [dict(entry._mapping) for entry in progress]

def insert_attempt(attempt: ProblemAttemptInsert):
    with engine.connect() as conn:
        result = conn.execute(
            text("""
            INSERT INTO problem_attempts (student_id, problem_id, topic_id, tier, hint_cap)
            VALUES (:student_id, :problem_id, :topic_id, :tier, :hint_cap)
            RETURNING attempt_id
            """),
            {
                "student_id": attempt.student_id,
                "problem_id": attempt.problem_id,
                "topic_id": attempt.topic_id,
                "tier": attempt.tier,
                "hint_cap": attempt.hint_cap
            }
        )
        attempt_id = result.fetchone()[0]
        conn.commit()
        return attempt_id

def get_attempt(attempt_id: int):
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT * FROM problem_attempts WHERE attempt_id = :attempt_id"),
            {"attempt_id": attempt_id}
        )
        attempt = result.fetchone()
        return dict(attempt._mapping) if attempt else None

def get_open_attempt(student_id: int, problem_id: int):
    with engine.connect() as conn:
        result = conn.execute(
            text("""
            SELECT * FROM problem_attempts
            WHERE student_id = :student_id
              AND problem_id = :problem_id
              AND result = :no_submission
            ORDER BY started_at DESC
            LIMIT 1
            """),
            {"student_id": student_id, "problem_id": problem_id, "no_submission": SubmitResult.NO_SUBMISSION.value}
        )
        attempt = result.fetchone()
        return dict(attempt._mapping) if attempt else None

def get_open_attempt_for_topic(student_id: int, topic_id: int):
    with engine.connect() as conn:
        result = conn.execute(
            text("""
            SELECT * FROM problem_attempts
            WHERE student_id = :student_id
              AND topic_id = :topic_id
              AND result = :no_submission
            ORDER BY started_at DESC
            LIMIT 1
            """),
            {"student_id": student_id, "topic_id": topic_id, "no_submission": SubmitResult.NO_SUBMISSION.value}
        )
        attempt = result.fetchone()
        return dict(attempt._mapping) if attempt else None

def get_attempts_for_tier(student_id: int, topic_id: int, tier: int, limit: int = 5):
    with engine.connect() as conn:
        result = conn.execute(
            text("""
            SELECT * FROM problem_attempts
            WHERE student_id = :student_id
              AND topic_id = :topic_id
              AND tier = :tier
              AND result != :no_submission
            ORDER BY submitted_at DESC
            LIMIT :limit
            """),
            {
                "student_id": student_id,
                "topic_id": topic_id,
                "tier": tier,
                "no_submission": SubmitResult.NO_SUBMISSION.value,
                "limit": limit
            }
        )
        attempts = result.fetchall()
        return [dict(attempt._mapping) for attempt in attempts]

def mark_attempt_engaged(attempt_id: int):
    with engine.connect() as conn:
        conn.execute(
            text("UPDATE problem_attempts SET engagement_occurred = TRUE WHERE attempt_id = :attempt_id"),
            {"attempt_id": attempt_id}
        )
        conn.commit()

def mark_attempt_struggle(attempt_id: int):
    with engine.connect() as conn:
        conn.execute(
            text("UPDATE problem_attempts SET struggle_detected = TRUE WHERE attempt_id = :attempt_id"),
            {"attempt_id": attempt_id}
        )
        conn.commit()

def increment_attempt_hints(attempt_id: int):
    with engine.connect() as conn:
        result = conn.execute(
            text("""
            UPDATE problem_attempts
            SET hints_used = hints_used + 1
            WHERE attempt_id = :attempt_id
            RETURNING hints_used
            """),
            {"attempt_id": attempt_id}
        )
        hints_used = result.fetchone()[0]
        conn.commit()
        return hints_used

def conclude_attempt(update: ProblemAttemptUpdate):
    with engine.connect() as conn:
        conn.execute(
            text("""
            UPDATE problem_attempts
            SET result = :result,
                escalated = :escalated,
                escalation_reason = :escalation_reason,
                submitted_at = CURRENT_TIMESTAMP
            WHERE attempt_id = :attempt_id
            """),
            {
                "attempt_id": update.attempt_id,
                "result": update.result.value,
                "escalated": update.escalated,
                "escalation_reason": update.escalation_reason
            }
        )
        conn.commit()

def count_bypass_for_attempt(attempt_id: int):
    with engine.connect() as conn:
        result = conn.execute(
            text("""
            SELECT COUNT(*) FROM interaction_log
            WHERE attempt_id = :attempt_id
              AND reasoning_state = :bypass
            """),
            {"attempt_id": attempt_id, "bypass": ReasoningState.BYPASS.value}
        )
        count = result.fetchone()
        return count[0] if count else 0

def count_turns_for_attempt(attempt_id: int):
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT COUNT(*) FROM interaction_log WHERE attempt_id = :attempt_id"),
            {"attempt_id": attempt_id}
        )
        count = result.fetchone()
        return count[0] if count else 0

def get_student_skill_state(student_id: int, topic_id: int):
    with engine.connect() as conn:
        result = conn.execute(
            text("""
            SELECT * FROM student_skill_state
            WHERE student_id = :student_id
              AND topic_id = :topic_id
            """),
            {"student_id": student_id, "topic_id": topic_id}
        )
        skill_state = result.fetchone()
        return dict(skill_state._mapping) if skill_state else None

def update_student_skill_state(update: StudentSkillStateUpdate):
    with engine.connect() as conn:
        conn.execute(
            text("""
            INSERT INTO student_skill_state (
                student_id, topic_id, current_tier, mastery_score,
                dependency_score, hint_cap, updated_at
            ) VALUES (
                :student_id, :topic_id, :current_tier, :mastery_score,
                :dependency_score, :hint_cap, :updated_at
            )
            ON CONFLICT (student_id, topic_id) DO UPDATE SET
                current_tier = EXCLUDED.current_tier,
                mastery_score = EXCLUDED.mastery_score,
                dependency_score = EXCLUDED.dependency_score,
                hint_cap = EXCLUDED.hint_cap,
                updated_at = EXCLUDED.updated_at
            """),
            {
                "student_id": update.student_id,
                "topic_id": update.topic_id,
                "current_tier": update.current_tier,
                "mastery_score": update.mastery_score,
                "dependency_score": update.dependency_score,
                "hint_cap": update.hint_cap,
                "updated_at": update.updated_at
            }
        )
        conn.commit()

def log_interaction(entry: InteractionLogEntry):
    with engine.connect() as conn:
        conn.execute(
            text("""
            INSERT INTO interaction_log (
                student_id, problem_id, topic_id, attempt_id, reasoning_state,
                submit_result, non_progress_flag, turn_number,
                hints_used_this_turn, mastery_score, dependency_score,
                current_tier, turn_summary, run_test_result, created_at
            ) VALUES (
                :student_id, :problem_id, :topic_id, :attempt_id, :reasoning_state,
                :submit_result, :non_progress_flag, :turn_number,
                :hints_used_this_turn, :mastery_score, :dependency_score,
                :current_tier, :turn_summary, :run_test_result, :created_at
            )
            """),
            {
                "student_id": entry.student_id,
                "problem_id": entry.problem_id,
                "topic_id": entry.topic_id,
                "attempt_id": entry.attempt_id,
                "reasoning_state": entry.reasoning_state.value,
                "submit_result": entry.submit_result.value,
                "non_progress_flag": entry.non_progress_flag,
                "turn_number": entry.turn_number,
                "hints_used_this_turn": entry.hints_used_this_turn,
                "mastery_score": entry.mastery_score,
                "dependency_score": entry.dependency_score,
                "current_tier": entry.current_tier,
                "turn_summary": entry.turn_summary,
                "run_test_result": json.dumps(entry.run_test_result) if entry.run_test_result is not None else None,
                "created_at": entry.created_at
            }
        )
        conn.commit()

def check_db_connection():
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version();"))
            return result.fetchone()[0] == 1
    except Exception as e:
        print(f"Database connection error: {e}")
        return False
