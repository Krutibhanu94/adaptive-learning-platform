from config import engine
from sqlalchemy import text
from dataclasses import dataclass
from enum import Enum

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

@dataclass
class StudentSkillStateUpdate:
    student_id: int
    topic_id: int
    current_tier: int
    mastery_score: float
    dependency_score: float
    hint_trend: float
    updated_at: str

@dataclass
class InteractionLogEntry:
    student_id: int
    problem_id: int
    topic_id: int
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

def get_student(student_id: int):
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM students WHERE student_id = :student_id"), {"student_id": student_id})
        student = result.fetchone()
        return dict(student._mapping) if student else None

def get_topics():
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM topics"))
        topics = result.fetchall()
        return [dict(topic._mapping) for topic in topics]

def get_problem(problem_id: int):
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM problems WHERE problem_id = :problem_id"), {"problem_id": problem_id})
        problem = result.fetchone()
        return [dict(problem._mapping)] if problem else None

def insert_problem(problem_data: ProblemInsert):
    with engine.connect() as conn:
        conn.execute(
            text("""
            INSERT INTO problems (problem_name, problem_description, test_cases, tier, topic_id)
            VALUES (:problem_name, :problem_description, :test_cases, :tier, :topic_id)
            """),
            {
                "problem_name": problem_data.problem_name,
                "problem_description": problem_data.problem_description,
                "test_cases": problem_data.test_cases,
                "tier": problem_data.tier,
                "topic_id": problem_data.topic_id
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
                      SELECT problem_id FROM interaction_log
                      WHERE student_id = :student_id
                        AND topic_id = :topic_id
                        AND submit_result = :submit_result
                  )
                LIMIT 1
            """),
            {"student_id": student_id, "topic_id": topic_id, "tier": tier, "submit_result": SubmitResult.PASS.value}
        )
        next_problem = result.fetchone()
        return dict(next_problem._mapping) if next_problem else None

def get_submit_result_problems(student_id: int, topic_id: int, submit_result: SubmitResult):
    with engine.connect() as conn:
        result = conn.execute(
            text("""
            SELECT * FROM problems
            WHERE topic_id = :topic_id
              AND problem_id IN (
                  SELECT problem_id FROM interaction_log
                  WHERE student_id = :student_id
                    AND topic_id = :topic_id
                    AND submit_result = :submit_result
                )
            """),
            {"student_id": student_id, "topic_id": topic_id, "submit_result": submit_result.value}
        )
        problems = result.fetchall()
        return [dict(problem._mapping) for problem in problems]

# def get_completed_problems(student_id: int, topic_id: int):
#     with engine.connect() as conn:
#         result = conn.execute(
#             text("""
#             SELECT * FROM problems
#             WHERE topic_id = :topic_id
#               AND problem_id IN (
#                   SELECT problem_id FROM interaction_log
#                   WHERE student_id = :student_id
#                     AND  topic_id = :topic_id
#                     AND submit_result = 'pass'
#                 )
#             """),
#             {"student_id": student_id, "topic_id": topic_id}
#         )
#         completed_problems = result.fetchall()
#         return completed_problems

# def get_failed_problems(student_id: int, topic_id: int):
#     with engine.connect() as conn:
#         result = conn.execute(
#             text("""
#             SELECT * FROM problems
#             WHERE topic_id = :topic_id
#               AND problem_id IN (
#                   SELECT problem_id FROM interaction_log
#                   WHERE student_id = :student_id
#                     AND  topic_id = :topic_id
#                     AND submit_result = 'fail'
#                 )
#             """),
#             {"student_id": student_id, "topic_id": topic_id}
#         )
#         failed_problems = result.fetchall()
#         return failed_problems

# def get_partially_completed_problems(student_id: int, topic_id: int):
#     with engine.connect() as conn:
#         result = conn.execute(
#             text("""
#             SELECT * FROM problems
#             WHERE topic_id = :topic_id
#               AND problem_id IN (
#                   SELECT problem_id FROM interaction_log
#                   WHERE student_id = :student_id
#                     AND  topic_id = :topic_id
#                     AND submit_result = 'partial'
#                 )
#             """),
#             {"student_id": student_id, "topic_id": topic_id}
#         )
#         partially_completed_problems = result.fetchall()
#         return partially_completed_problems

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
                dependency_score, hint_trend, updated_at
            ) VALUES (
                :student_id, :topic_id, :current_tier, :mastery_score,
                :dependency_score, :hint_trend, :updated_at
            )
            ON CONFLICT (student_id, topic_id) DO UPDATE SET
                current_tier = EXCLUDED.current_tier,
                mastery_score = EXCLUDED.mastery_score,
                dependency_score = EXCLUDED.dependency_score,
                hint_trend = EXCLUDED.hint_trend,
                updated_at = EXCLUDED.updated_at
            """),
            {
                "student_id": update.student_id,
                "topic_id": update.topic_id,
                "current_tier": update.current_tier,
                "mastery_score": update.mastery_score,
                "dependency_score": update.dependency_score,
                "hint_trend": update.hint_trend,
                "updated_at": update.updated_at
            }
        )
        conn.commit()

def get_recent_interactions(student_id: int, topic_id: int, limit: int = 5):
    with engine.connect() as conn:
        result = conn.execute(
            text("""
            SELECT * FROM interaction_log
            WHERE student_id = :student_id
              AND topic_id = :topic_id
            ORDER BY created_at DESC
            LIMIT :limit
            """),
            {"student_id": student_id, "topic_id": topic_id, "limit": limit}
        )
        interactions = result.fetchall()
        return [dict(interaction._mapping) for interaction in interactions]

def log_interaction(entry: InteractionLogEntry):
    with engine.connect() as conn:
        conn.execute(
            text("""
            INSERT INTO interaction_log (
                student_id, problem_id, topic_id, reasoning_state,
                submit_result, non_progress_flag, turn_number,
                hints_used_this_turn, mastery_score, dependency_score,
                current_tier, turn_summary, run_test_result
            ) VALUES (
                :student_id, :problem_id, :topic_id, :reasoning_state,
                :submit_result, :non_progress_flag, :turn_number,
                :hints_used_this_turn, :mastery_score, :dependency_score,
                :current_tier, :turn_summary, :run_test_result
            )
            """),
            {
                "student_id": entry.student_id,
                "problem_id": entry.problem_id,
                "topic_id": entry.topic_id,
                "reasoning_state": entry.reasoning_state.value,
                "submit_result": entry.submit_result.value,
                "non_progress_flag": entry.non_progress_flag,
                "turn_number": entry.turn_number,
                "hints_used_this_turn": entry.hints_used_this_turn,
                "mastery_score": entry.mastery_score,
                "dependency_score": entry.dependency_score,
                "current_tier": entry.current_tier,
                "turn_summary": entry.turn_summary,
                "run_test_result": entry.run_test_result
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