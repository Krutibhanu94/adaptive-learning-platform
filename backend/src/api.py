from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from config import model
from db import (
    ProblemAttemptInsert,
    check_db_connection,
    get_attempt,
    get_next_problem,
    get_open_attempt_for_topic,
    get_problem,
    get_student,
    get_student_skill_state,
    get_topic_progress,
    get_topics,
    insert_attempt,
)
from agent import STARTING_HINT_CAP, graph
from pydantic import BaseModel

class ChatRequest(BaseModel):
    message: str

class TurnRequest(BaseModel):
    event_type: Literal["message", "code_update", "heartbeat"]
    message: str | None = None
    code: str | None = None

router = APIRouter()

@router.get("/students/{student_id}")
async def student(student_id: int):
    result = get_student(student_id)
    if result is None:
        return {"found": False, "message": "Student not found"}
    return {"found": True, "student": result}

@router.get("/topics")
async def topics():
    result = get_topics()
    return {"topics": result}

@router.get("/student/{student_id}/topics/{topic_id}/progress")
async def topic_progress(student_id: int, topic_id: int):
    result = get_topic_progress(student_id, topic_id)
    return {"progress": result}

@router.post("/students/{student_id}/topics/{topic_id}/start")
async def start_attempt(student_id: int, topic_id: int):
    existing = get_open_attempt_for_topic(student_id, topic_id)

    if existing:
        problem_rows = get_problem(existing["problem_id"])
        if not problem_rows:
            raise HTTPException(status_code=404, detail="Attempt references a problem that no longer exists")
        problem = problem_rows[0]
        return {
            "found": True,
            "attempt_id": existing["attempt_id"],
            "problem_id": problem["problem_id"],
            "problem_name": problem["problem_name"],
            "problem_description": problem["problem_description"],
        }

    skill_state = get_student_skill_state(student_id, topic_id)
    tier = skill_state["current_tier"] if skill_state else 1
    hint_cap = skill_state["hint_cap"] if skill_state else STARTING_HINT_CAP
    mastery_score = skill_state["mastery_score"] if skill_state else 0.0
    dependency_score = skill_state["dependency_score"] if skill_state else 0.0

    next_problem = get_next_problem(student_id, topic_id, tier)
    if next_problem is None:
        return {"found": False, "message": "No more problems available at this tier."}

    attempt_id = insert_attempt(ProblemAttemptInsert(
        student_id=student_id,
        problem_id=next_problem["problem_id"],
        topic_id=topic_id,
        tier=tier,
        hint_cap=hint_cap,
    ))
    attempt = get_attempt(attempt_id)

    # Seed the checkpoint for this brand new attempt. idle_seconds defaults to 0 (no
    # input this call), so route_turn's opening-silence check can't fire yet -- this
    # invocation always resolves to "end" with no side effects, same as any other
    # non-triggering turn.
    graph.invoke(
        {
            "student_id": student_id,
            "topic_id": topic_id,
            "problem_id": attempt["problem_id"],
            "attempt_id": attempt["attempt_id"],
            "problem_description": next_problem["problem_description"],
            "tier": attempt["tier"],
            "hint_cap": attempt["hint_cap"],
            "hints_used": attempt["hints_used"],
            "engagement_occurred": attempt["engagement_occurred"],
            "struggle_detected": attempt["struggle_detected"],
            "mastery_score": mastery_score,
            "dependency_score": dependency_score,
            "last_activity_at": datetime.now().isoformat(),
        },
        {"configurable": {"thread_id": str(attempt_id)}},
    )

    return {
        "found": True,
        "attempt_id": attempt_id,
        "problem_id": next_problem["problem_id"],
        "problem_name": next_problem["problem_name"],
        "problem_description": next_problem["problem_description"],
    }

@router.post("/attempts/{attempt_id}/turn")
async def turn(attempt_id: int, request: TurnRequest):
    config = {"configurable": {"thread_id": str(attempt_id)}}
    current = graph.get_state(config).values

    if not current:
        raise HTTPException(status_code=404, detail="No attempt found for this attempt_id -- start one first.")

    now = datetime.now()

    # Ephemeral, one-shot signals: explicitly reset every call so a stale value from a
    # previous turn (persisted by the checkpointer) can't leak into this turn's routing.
    turn_input = {
        "student_message": None,
        "code_changed": False,
        "run_test_clicked": False,
        "run_test_result": None,
        "submit_clicked": False,
    }

    if request.event_type == "message":
        turn_input["student_message"] = request.message
        turn_input["idle_seconds"] = 0
        turn_input["last_activity_at"] = now.isoformat()

    elif request.event_type == "code_update":
        last_code = current.get("last_student_code")
        code_changed = request.code != last_code
        turn_input["student_code"] = request.code
        turn_input["code_changed"] = code_changed
        turn_input["last_student_code"] = request.code
        turn_input["idle_seconds"] = 0
        turn_input["last_activity_at"] = now.isoformat()
        turn_input["repeated_edit_count"] = (
            0 if code_changed else current.get("repeated_edit_count", 0) + 1
        )

    else:  # heartbeat -- a pure elapsed-time check, not new activity itself; leaves
           # repeated_edit_count and last_activity_at untouched.
        last_activity_raw = current.get("last_activity_at")
        idle_seconds = (
            (now - datetime.fromisoformat(last_activity_raw)).total_seconds()
            if last_activity_raw else 0
        )
        turn_input["idle_seconds"] = int(idle_seconds)

    # probe_question/intervention_message are sticky in the checkpoint -- a turn that
    # doesn't generate new tutor-facing text (e.g. evaluate_reasoning silently scoring a
    # reply, or a heartbeat where nothing fired) leaves them exactly as they were. Diff
    # against the pre-invoke snapshot so we only surface genuinely new text this turn,
    # instead of re-sending whatever's left over from a previous one.
    prior_probe_question = current.get("probe_question")
    prior_intervention_message = current.get("intervention_message")

    result = graph.invoke(turn_input, config)

    new_message = None
    if result.get("probe_question") != prior_probe_question:
        new_message = result.get("probe_question")
    elif result.get("intervention_message") != prior_intervention_message:
        new_message = result.get("intervention_message")

    return {
        "message": new_message,
        "pending_response_to": result.get("pending_response_to"),
        "engagement_occurred": result.get("engagement_occurred", False),
        "escalated": result.get("escalated", False),
        "escalation_reason": result.get("escalation_reason"),
        "tier": result.get("tier"),
        "hint_cap": result.get("hint_cap"),
        "hints_used": result.get("hints_used", 0),
    }

@router.post("/ping")
async def ping(request: ChatRequest):
    response = model.invoke(request.message)
    db_version = check_db_connection()
    return {"reply": response.content, "db_check": db_version}
