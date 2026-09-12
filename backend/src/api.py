from datetime import datetime
from difflib import SequenceMatcher
from typing import Literal

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool
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
from agent import (
    CODE_GROWTH_THRESHOLD_CHARS,
    CODE_SIMILARITY_THRESHOLD,
    CODE_SNAPSHOT_WINDOW,
    STARTING_HINT_CAP,
    graph,
)
from pydantic import BaseModel

class ChatRequest(BaseModel):
    message: str

class TurnRequest(BaseModel):
    event_type: Literal["message", "code_update", "heartbeat", "resume", "run_test", "submit"]
    message: str | None = None
    code: str | None = None

def _is_similar_to_recent(code: str, recent_snapshots: list) -> bool:
    # Similarity, not exact match, against every snapshot still in the window -- not
    # just the immediately-previous one. Confirmed via a real debug session that natural
    # stuck-typing almost never lands on byte-identical text twice in a row, but does
    # oscillate between a couple of similar-but-not-identical attempts; comparing only
    # against the last snapshot would miss exactly that oscillation.
    return any(
        SequenceMatcher(None, code, snapshot).ratio() >= CODE_SIMILARITY_THRESHOLD
        for snapshot in recent_snapshots
    )

def _is_growing(code: str, recent_snapshots: list) -> bool:
    # Compares against the oldest snapshot still in the window -- "growth over the last
    # few edits," not lifetime growth since the very first line. A student slowly
    # building a solution incrementally has high similarity between adjacent snapshots
    # purely because each edit is small; that's still genuine progress, so growth vetoes
    # the similarity check regardless of how similar consecutive edits look.
    if not recent_snapshots:
        return False
    return (len(code) - len(recent_snapshots[0])) >= CODE_GROWTH_THRESHOLD_CHARS

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

        # Reopening this attempt is itself activity -- reset the clock so a real-world
        # gap since the student was last here (closed tab, navigated away) doesn't get
        # misread as idle struggle by the very next heartbeat. idle_seconds is reset
        # explicitly too, not just the timestamp: route_turn evaluates on every
        # invoke(), so a bare last_activity_at update would still leave a stale
        # idle_seconds from a prior heartbeat in play for this call.
        await run_in_threadpool(
            graph.invoke,
            {
                "student_message": None,
                "code_changed": False,
                "run_test_clicked": False,
                "run_test_result": None,
                "submit_clicked": False,
                "idle_seconds": 0,
                "last_activity_at": datetime.now().isoformat(),
            },
            {"configurable": {"thread_id": str(existing["attempt_id"])}},
        )

        return {
            "found": True,
            "attempt_id": existing["attempt_id"],
            "problem_id": problem["problem_id"],
            "problem_name": problem["problem_name"],
            "problem_description": problem["problem_description"],
            "test_cases": problem["test_cases"],
            "starter_code": problem["starter_code"],
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
    await run_in_threadpool(
        graph.invoke,
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
        "test_cases": next_problem["test_cases"],
        "starter_code": next_problem["starter_code"],
    }

@router.get("/attempts/{attempt_id}")
async def get_attempt_state(attempt_id: int):
    attempt = get_attempt(attempt_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found")

    problem_rows = get_problem(attempt["problem_id"])
    problem = problem_rows[0] if problem_rows else None

    config = {"configurable": {"thread_id": str(attempt_id)}}
    state = graph.get_state(config).values

    # There is no verbatim transcript to replay here -- interaction_log stores
    # LLM-generated turn summaries for analytics, not the raw probe/message text, and
    # probe_node itself never logs a row at all. So this recovers the single currently
    # outstanding question (if any), not a full back-and-forth history. A real chat
    # transcript would need its own persisted message log; flagged, not built here.
    pending = state.get("pending_response_to")
    if pending == "probe":
        current_message = state.get("probe_question")
    elif pending in ("checkin", "hint"):
        current_message = state.get("intervention_message")
    else:
        current_message = None

    return {
        "attempt_id": attempt_id,
        "problem_id": problem["problem_id"] if problem else attempt["problem_id"],
        "problem_name": problem["problem_name"] if problem else None,
        "problem_description": problem["problem_description"] if problem else None,
        "test_cases": problem["test_cases"] if problem else None,
        "starter_code": problem["starter_code"] if problem else None,
        "pending_response_to": pending,
        "current_message": current_message,
        "engagement_occurred": state.get("engagement_occurred", attempt["engagement_occurred"]),
        "escalated": state.get("escalated", attempt["escalated"]),
        "escalation_reason": state.get("escalation_reason", attempt["escalation_reason"]),
        "tier": state.get("tier", attempt["tier"]),
        "hint_cap": state.get("hint_cap", attempt["hint_cap"]),
        "hints_used": state.get("hints_used", attempt["hints_used"]),
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
        # A genuine reply is a fresh start for the edit-based struggle signal too, not
        # just the idle one -- otherwise a stale, already-past-threshold
        # struggle_duration_seconds from before the reply immediately re-triggers
        # struggling on the very next heartbeat, with zero real idle time elapsed,
        # regardless of how genuinely the student just engaged.
        turn_input["stuck_since"] = None
        turn_input["struggle_duration_seconds"] = 0

    elif request.event_type == "code_update":
        recent_snapshots = current.get("recent_code_snapshots") or []
        growing = _is_growing(request.code, recent_snapshots)
        similar = _is_similar_to_recent(request.code, recent_snapshots)
        stuck_since = current.get("stuck_since")

        if growing:
            # Genuine progress vetoes struggle regardless of similarity -- see _is_growing.
            new_stuck_since = None
        elif similar:
            # First qualifying snapshot starts the clock; otherwise leave it alone so
            # duration accumulates across the whole streak, not just this one edit.
            new_stuck_since = stuck_since or now.isoformat()
        else:
            # Genuinely different from anything recent, even if not yet longer --
            # benefit of the doubt for exploring a new approach.
            new_stuck_since = None

        turn_input["student_code"] = request.code
        turn_input["code_changed"] = not similar
        turn_input["recent_code_snapshots"] = (recent_snapshots + [request.code])[-CODE_SNAPSHOT_WINDOW:]
        turn_input["idle_seconds"] = 0
        turn_input["last_activity_at"] = now.isoformat()
        turn_input["stuck_since"] = new_stuck_since
        turn_input["struggle_duration_seconds"] = (
            int((now - datetime.fromisoformat(new_stuck_since)).total_seconds())
            if new_stuck_since else 0
        )

    elif request.event_type == "resume":
        # The student has just reopened/returned to this attempt (Workspace mounted --
        # a fresh visit, a browser back/forward, or a refresh that bypassed /start's own
        # resume branch). No student_message/student_code here, so this can't generate a
        # probe on its own -- it only resets the clock, the same fix /start's resume
        # branch applies, for the paths that don't go through /start at all.
        turn_input["idle_seconds"] = 0
        turn_input["last_activity_at"] = now.isoformat()

    elif request.event_type == "run_test":
        # The actual check now runs inside the graph itself (run_check_node, via a real
        # forced tool call to check_correctness) -- not here. This 404 guard stays as a
        # fast, clear failure for a missing problem rather than deferring to that node's
        # own softer "problem not found" fallback, which is meant for the model-driven
        # call, not this HTTP-level guard.
        problem_rows = get_problem(current["problem_id"])
        if not problem_rows:
            raise HTTPException(status_code=404, detail="Problem for this attempt no longer exists")

        turn_input["student_code"] = request.code
        turn_input["recent_code_snapshots"] = ((current.get("recent_code_snapshots") or []) + [request.code])[-CODE_SNAPSHOT_WINDOW:]
        turn_input["run_test_clicked"] = True
        turn_input["idle_seconds"] = 0
        turn_input["last_activity_at"] = now.isoformat()
        turn_input["stuck_since"] = None
        turn_input["struggle_duration_seconds"] = 0

    elif request.event_type == "submit":
        # Defensive backstop -- route_turn already no-ops silently if this isn't
        # satisfied (engagement gate), but the primary enforcement is the frontend
        # disabling Submit; a silent no-op here would be a confusing API response, so
        # reject explicitly instead.
        if not current.get("engagement_occurred", False):
            raise HTTPException(
                status_code=409,
                detail="Engagement gate not satisfied -- at least one probe/evaluate exchange must occur before submitting.",
            )

        # Same as run_test above: the check itself now runs inside run_check_node via a
        # real forced tool call, not here -- this stays only as the fast 404 guard.
        problem_rows = get_problem(current["problem_id"])
        if not problem_rows:
            raise HTTPException(status_code=404, detail="Problem for this attempt no longer exists")

        turn_input["student_code"] = request.code
        turn_input["recent_code_snapshots"] = ((current.get("recent_code_snapshots") or []) + [request.code])[-CODE_SNAPSHOT_WINDOW:]
        turn_input["submit_clicked"] = True
        turn_input["idle_seconds"] = 0
        turn_input["last_activity_at"] = now.isoformat()
        turn_input["stuck_since"] = None
        turn_input["struggle_duration_seconds"] = 0

    else:  # heartbeat -- a pure elapsed-time check, not new activity itself; leaves
           # last_activity_at and stuck_since untouched, just recomputes the derived
           # idle_seconds/struggle_duration_seconds from them.
        last_activity_raw = current.get("last_activity_at")
        idle_seconds = (
            (now - datetime.fromisoformat(last_activity_raw)).total_seconds()
            if last_activity_raw else 0
        )
        turn_input["idle_seconds"] = int(idle_seconds)

        stuck_since = current.get("stuck_since")
        struggle_duration = (
            (now - datetime.fromisoformat(stuck_since)).total_seconds()
            if stuck_since else 0
        )
        turn_input["struggle_duration_seconds"] = int(struggle_duration)

    # probe_question/intervention_message are sticky in the checkpoint -- a turn that
    # doesn't generate new tutor-facing text (e.g. evaluate_reasoning silently scoring a
    # reply, or a heartbeat where nothing fired) leaves them exactly as they were. Diff
    # against the pre-invoke snapshot so we only surface genuinely new text this turn,
    # instead of re-sending whatever's left over from a previous one.
    prior_probe_question = current.get("probe_question")
    prior_intervention_message = current.get("intervention_message")

    result = await run_in_threadpool(graph.invoke, turn_input, config)

    new_message = None
    if result.get("probe_question") != prior_probe_question:
        new_message = result.get("probe_question")
    elif result.get("intervention_message") != prior_intervention_message:
        new_message = result.get("intervention_message")

    response = {
        "message": new_message,
        "pending_response_to": result.get("pending_response_to"),
        "engagement_occurred": result.get("engagement_occurred", False),
        "escalated": result.get("escalated", False),
        "escalation_reason": result.get("escalation_reason"),
        "tier": result.get("tier"),
        "hint_cap": result.get("hint_cap"),
        "hints_used": result.get("hints_used", 0),
    }

    # run_test_result/final_result/next_problem are sticky in the checkpoint once set
    # (like probe_question/intervention_message), so they're only included in the
    # response for the event types that actually just produced them this call --
    # otherwise an unrelated later heartbeat/message would re-surface a stale test
    # result from a previous run_test/submit.
    if request.event_type in ("run_test", "submit"):
        response["run_test_result"] = result.get("run_test_result")

    if request.event_type == "code_update":
        # Surfaced for debugging the struggle detector from the browser console -- these
        # are what the backend actually computed by checking growth/similarity against
        # its own recent_code_snapshots window, the authoritative answer to "did this
        # register as struggle," not just what the client thinks it sent.
        response["code_changed"] = result.get("code_changed")
        response["stuck_since"] = result.get("stuck_since")
        response["struggle_duration_seconds"] = result.get("struggle_duration_seconds")

    if request.event_type == "submit":
        response["final_result"] = result.get("final_result")
        response["next_problem"] = {
            "problem_id": result.get("problem_id"),
            "problem_name": result.get("problem_name"),
            "problem_description": result.get("problem_description"),
        }

    return response

@router.post("/ping")
async def ping(request: ChatRequest):
    response = model.invoke(request.message)
    db_version = check_db_connection()
    return {"reply": response.content, "db_check": db_version}
