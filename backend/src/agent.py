from datetime import datetime

from config import checkpoint_db_url, model
from typing import Literal, TypedDict
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import StateGraph, START, END
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from db import (
    InteractionLogEntry,
    ProblemAttemptUpdate,
    ReasoningState,
    StudentSkillStateUpdate,
    SubmitResult,
    count_bypass_for_attempt,
    count_turns_for_attempt,
    conclude_attempt,
    get_attempt,
    get_attempts_for_tier,
    get_next_problem,
    get_student_skill_state,
    increment_attempt_hints,
    log_interaction,
    mark_attempt_engaged,
    mark_attempt_struggle,
    update_student_skill_state,
)

# Opening-silence thresholds come straight from the spec ("~3 minutes", "~5 minutes").
# Ongoing idle/repeated-edit thresholds are carried over from the pre-refactor
# implementation's own tuning constants (180s, 5 edits) -- the spec names these two
# triggers but doesn't give numbers, so these are implementation defaults, not
# spec-mandated values.
OPENING_SILENCE_SECONDS = 180
OPENING_FOLLOWUP_SECONDS = 300
ONGOING_IDLE_SECONDS = 180
ONGOING_REPEATED_EDIT_THRESHOLD = 5
STARTING_HINT_CAP = 3


class GraphState(TypedDict, total=False):
    # Identity for this attempt.
    student_id: int
    topic_id: int
    problem_id: int
    attempt_id: int
    problem_description: str

    # This invocation's input -- one external event per graph run.
    student_message: str | None
    student_code: str | None
    code_changed: bool
    idle_seconds: int
    repeated_edit_count: int
    run_test_clicked: bool
    run_test_result: dict | None
    submit_clicked: bool

    # Attempt-level state, rehydrated from Problem_Attempts / Student_Skill_State
    # at graph entry (see checkpointing note near graph.compile() below).
    tier: int
    hint_cap: int
    hints_used: int
    engagement_occurred: bool
    struggle_detected: bool
    # What we're currently waiting on a reply to, if anything -- this is what makes
    # pause/resume across separate invocations possible instead of needing every
    # input upfront in one graph.invoke() call.
    pending_response_to: Literal["probe", "checkin", "hint"] | None
    # True only for the one-time proactive probe fired by opening-silence -- gates the
    # opening-specific 5-minute follow-up timer. Any other outstanding probe falls back
    # to the standard idle/repeated-edit checks, not this timer.
    is_opening_probe: bool
    # Server-computed bookkeeping the /turn endpoint uses to derive idle_seconds and
    # repeated_edit_count each call -- not sent by the frontend directly, just persisted
    # here via the checkpointer like everything else in this block.
    last_activity_at: str | None
    last_student_code: str | None

    # Produced during this run.
    probe_question: str
    # Stored as the plain "genuine"/"bypass" string, not the ReasoningState enum --
    # this field is never read back from state (only ever set here and written into
    # InteractionLogEntry locally), and the checkpointer's msgpack serializer doesn't
    # natively support custom Enum types, which was logging a deserialization warning
    # on every turn ("will be blocked in a future version").
    reasoning_state: str
    turn_summary: str
    intervention_message: str
    mastery_score: float
    dependency_score: float
    bypass_count: int
    escalated: bool
    escalation_reason: str | None
    final_result: SubmitResult


class ReasoningEvaluation(BaseModel):
    classification: Literal["genuine", "bypass"]
    summary: str


def probe_node(state: GraphState) -> GraphState:
    run_test_result = state.get("run_test_result")
    student_code = state.get("student_code")
    student_message = state.get("student_message")
    is_opening_probe = False

    if run_test_result and not run_test_result.get("all_passed"):
        prompt = f"""You are a Socratic tutor. A student ran their tests on this problem:
        {state['problem_description']}

        Here is what failed:
        {run_test_result.get('failures')}

        Ask a single Socratic question grounded specifically in what failed, to help them
        reason about why. Do not confirm the fix, and do not give the answer."""
    elif student_message:
        prompt = f"""You are a Socratic tutor. A student is working on this problem:
        {state['problem_description']}
        The student said: "{student_message}"
        Respond with a single Socratic question that pushes the student to reason through
        their approach. Do not confirm whether they are right or wrong, and do not give
        the answer."""
    elif student_code:
        # Reached when there's no fresh message this turn but code exists to ground a
        # proactive probe in -- e.g. the opening-silence probe firing after the student
        # started coding without saying anything.
        prompt = f"""You are a Socratic tutor. A student is working on this problem:
        {state['problem_description']}

        Here is the code they've written so far:
        {student_code}

        Look at what they've actually written, and ask a single Socratic question about
        whatever seems most worth probing right now — this could be about their overall
        approach, a specific line, their choice of syntax, an edge case, a variable's
        purpose, or anything else genuinely relevant to what's in front of you.
        Do not confirm whether their code is correct, and do not give the answer."""
    else:
        prompt = f"""You are a Socratic tutor. A student has just opened this problem and
        hasn't said anything yet:
        {state['problem_description']}
        Proactively ask a single Socratic question to get them started thinking about
        their approach. Do not give the answer."""
        is_opening_probe = True

    reply = model.invoke(prompt)
    return {
        "probe_question": reply.content,
        "pending_response_to": "probe",
        "is_opening_probe": is_opening_probe,
    }


def evaluate_reasoning(state: GraphState) -> GraphState:
    prompt = f"""You are evaluating a student's response to a Socratic tutoring question.
    The tutor asked: "{state['probe_question']}"
    The student replied: "{state['student_message']}"
    Classify this reply as one of two categories:
    - "genuine" — the student attempts to reason through the question, even imperfectly,
      or asks a genuine clarifying question of their own.
    - "bypass" — the student demands the direct answer, restates without engaging, or
      otherwise avoids reasoning through the question.

    Then, write a short one-sentence summary of what happened this turn, including a short
    direct quote from the student's reply if it's the specific reason behind your
    classification.
    """

    evaluation = model.with_structured_output(ReasoningEvaluation).invoke(prompt)
    reasoning_state = ReasoningState(evaluation.classification)

    mark_attempt_engaged(state["attempt_id"])
    turn_number = count_turns_for_attempt(state["attempt_id"]) + 1

    log_interaction(InteractionLogEntry(
        student_id=state["student_id"],
        problem_id=state["problem_id"],
        topic_id=state["topic_id"],
        attempt_id=state["attempt_id"],
        reasoning_state=reasoning_state,
        submit_result=SubmitResult.NO_SUBMISSION,
        non_progress_flag=state.get("struggle_detected", False),
        turn_number=turn_number,
        hints_used_this_turn=0,
        mastery_score=state.get("mastery_score", 0.0),
        dependency_score=state.get("dependency_score", 0.0),
        current_tier=state.get("tier", 1),
        turn_summary=evaluation.summary,
        run_test_result=None,
        created_at=datetime.now()
    ))

    return {
        "reasoning_state": reasoning_state.value,
        "turn_summary": evaluation.summary,
        "engagement_occurred": True,
        "pending_response_to": None,
        "is_opening_probe": False,
    }


def decline_hint(state: GraphState) -> GraphState:
    # Enforces the hint cap live: no more Tier 2 hints for the rest of this attempt once
    # granting one would exceed it. Does NOT touch tier/escalation -- that consequence is
    # still decided once, at Submit, in decide_node. The student can keep working and
    # submit whenever they're ready; this just stops offering further hints.
    message = (
        "You've used all the hints available for this attempt. Keep working through it, "
        "and submit whenever you're ready — this attempt won't offer any more hints, but "
        "nothing is stopping you from submitting."
    )

    mark_attempt_struggle(state["attempt_id"])

    turn_number = count_turns_for_attempt(state["attempt_id"]) + 1
    log_interaction(InteractionLogEntry(
        student_id=state["student_id"],
        problem_id=state["problem_id"],
        topic_id=state["topic_id"],
        attempt_id=state["attempt_id"],
        reasoning_state=ReasoningState.NONE,
        submit_result=SubmitResult.NO_SUBMISSION,
        non_progress_flag=True,
        turn_number=turn_number,
        hints_used_this_turn=0,
        mastery_score=state.get("mastery_score", 0.0),
        dependency_score=state.get("dependency_score", 0.0),
        current_tier=state.get("tier", 1),
        turn_summary="Hint cap reached for this attempt; declined to give another hint.",
        run_test_result=None,
        created_at=datetime.now()
    ))

    return {
        "intervention_message": message,
        "struggle_detected": True,
        "hints_used": state.get("hints_used", 0),
        "pending_response_to": "hint",
        "is_opening_probe": False,
    }


def run_intervention(state: GraphState, tier: Literal["checkin", "hint"]) -> GraphState:
    if tier == "hint" and state.get("hints_used", 0) >= state.get("hint_cap", STARTING_HINT_CAP):
        return decline_hint(state)

    hints_used_this_turn = 0

    if tier == "checkin":
        prompt = f"""The student appears to have paused while working on this problem:
        {state['problem_description']}

        Write a brief, friendly check-in message asking why they've paused — without
        assuming they're stuck, since they may just be thinking or took a short break.
        Invite them to share what's going on."""
    else:
        hint_cap = state.get("hint_cap", STARTING_HINT_CAP)
        if hint_cap <= 1:
            generosity_guidance = (
                "This student's hint cap has tapered down significantly from consistent "
                "improvement. Keep this hint extremely minimal — a single subtle nudge, "
                "trusting them to do the rest. Do not reveal the solution."
            )
        elif hint_cap < STARTING_HINT_CAP:
            generosity_guidance = (
                "This student's hint cap has tapered down some from recent improvement. "
                "Keep this hint fairly minimal, offering less direct guidance than usual. "
                "Do not reveal the solution."
            )
        else:
            generosity_guidance = "Provide a standard, moderate level of hint support. Do not reveal the solution."

        prompt = f"""The student is working on this problem:
        {state['problem_description']}

        The student has been struggling to make progress (idle, or repeatedly editing
        without meaningful change).

        {generosity_guidance}

        Provide a single, subject-matter hint that nudges them toward the concept they
        may be missing — do not reveal the solution or write code for them."""
        hints_used_this_turn = 1

    reply = model.invoke(prompt)
    message = reply.content

    mark_attempt_struggle(state["attempt_id"])

    new_hints_used = state.get("hints_used", 0)
    if tier == "hint":
        new_hints_used = increment_attempt_hints(state["attempt_id"])

    turn_number = count_turns_for_attempt(state["attempt_id"]) + 1
    log_interaction(InteractionLogEntry(
        student_id=state["student_id"],
        problem_id=state["problem_id"],
        topic_id=state["topic_id"],
        attempt_id=state["attempt_id"],
        reasoning_state=ReasoningState.NONE,
        submit_result=SubmitResult.NO_SUBMISSION,
        non_progress_flag=True,
        turn_number=turn_number,
        hints_used_this_turn=hints_used_this_turn,
        mastery_score=state.get("mastery_score", 0.0),
        dependency_score=state.get("dependency_score", 0.0),
        current_tier=state.get("tier", 1),
        turn_summary=f"Intervention ({tier}): {message}",
        run_test_result=None,
        created_at=datetime.now()
    ))

    return {
        "intervention_message": message,
        "struggle_detected": True,
        "hints_used": new_hints_used,
        "pending_response_to": tier,
        "is_opening_probe": False,
    }


def intervene_checkin_node(state: GraphState) -> GraphState:
    return run_intervention(state, "checkin")


def intervene_hint_node(state: GraphState) -> GraphState:
    return run_intervention(state, "hint")


def escalate_node(state: GraphState) -> GraphState:
    # Reached either from sustained no-progress after a check-in *and* a hint (the
    # "original three-tier silence-handling design" the spec says still applies), or
    # from decide_node finding the hint cap exceeded with no tier left below it.
    reason = (
        "Sustained no-progress despite a check-in and a hint."
        if state.get("pending_response_to") == "hint"
        else "Hint cap exceeded with no tier remaining below the current one."
    )
    message = "It looks like you might be stuck — this has been flagged for your instructor to check in with you directly."

    mark_attempt_struggle(state["attempt_id"])

    turn_number = count_turns_for_attempt(state["attempt_id"]) + 1
    log_interaction(InteractionLogEntry(
        student_id=state["student_id"],
        problem_id=state["problem_id"],
        topic_id=state["topic_id"],
        attempt_id=state["attempt_id"],
        reasoning_state=ReasoningState.NONE,
        submit_result=SubmitResult.NO_SUBMISSION,
        non_progress_flag=True,
        turn_number=turn_number,
        hints_used_this_turn=0,
        mastery_score=state.get("mastery_score", 0.0),
        dependency_score=state.get("dependency_score", 0.0),
        current_tier=state.get("tier", 1),
        turn_summary=f"Escalated to human intervention: {reason}",
        run_test_result=None,
        created_at=datetime.now()
    ))

    return {
        "escalated": True,
        "escalation_reason": reason,
        "intervention_message": message,
        "pending_response_to": None,
    }


def log_test_pass_node(state: GraphState) -> GraphState:
    # "All pass, and genuine engagement already occurred this attempt -> no forced
    # conversation." Still worth a log row for a complete audit trail of every Run Test
    # click, distinct from Problem_Attempts.result, which is the attempt's final outcome.
    turn_number = count_turns_for_attempt(state["attempt_id"]) + 1
    log_interaction(InteractionLogEntry(
        student_id=state["student_id"],
        problem_id=state["problem_id"],
        topic_id=state["topic_id"],
        attempt_id=state["attempt_id"],
        reasoning_state=ReasoningState.NONE,
        submit_result=SubmitResult.PASS,
        non_progress_flag=False,
        turn_number=turn_number,
        hints_used_this_turn=0,
        mastery_score=state.get("mastery_score", 0.0),
        dependency_score=state.get("dependency_score", 0.0),
        current_tier=state.get("tier", 1),
        turn_summary="All tests passed; engagement already satisfied this attempt, so no forced conversation.",
        run_test_result=state.get("run_test_result"),
        created_at=datetime.now()
    ))
    return {}


def update_node(state: GraphState) -> GraphState:
    # Fires once per attempt, only on Submit. Reads accumulated per-attempt data (via
    # attempt_id) rather than the last N raw interaction_log rows.
    bypass_count = count_bypass_for_attempt(state["attempt_id"])

    current_mastery = state.get("mastery_score", 0.0)
    current_dependency = state.get("dependency_score", 0.0)

    if bypass_count == 0:
        mastery_delta = 0.1
        dependency_delta = -0.05
    else:
        mastery_delta = 0.0
        dependency_delta = 0.1

    new_mastery = min(1.0, max(0.0, current_mastery + mastery_delta))
    new_dependency = min(1.0, max(0.0, current_dependency + dependency_delta))

    return {
        "mastery_score": new_mastery,
        "dependency_score": new_dependency,
        "bypass_count": bypass_count,
    }


def decide_node(state: GraphState) -> GraphState:
    attempt = get_attempt(state["attempt_id"])
    skill_state = get_student_skill_state(state["student_id"], state["topic_id"])
    current_tier = skill_state["current_tier"]
    hint_cap = skill_state["hint_cap"]
    hints_used = attempt["hints_used"]

    escalated = False
    escalation_reason = None

    if hints_used > hint_cap:
        # Defensive only -- live enforcement in decline_hint() means this shouldn't
        # normally be reachable, since a hint request that would exceed the cap is
        # declined rather than granted. Kept as a safety net.
        if current_tier > 1:
            new_tier = current_tier - 1
            new_hint_cap = STARTING_HINT_CAP
        else:
            new_tier = current_tier
            new_hint_cap = hint_cap
            escalated = True
            escalation_reason = "Hint cap exceeded with no tier remaining below the current one."
    else:
        # The hint-cap sequence (3, 2, 1) tracks the 1st/2nd/3rd attempt at this tier --
        # not fixed problem IDs, whichever problems those happen to be. The advance/
        # step-down decision only happens once, after the 3rd attempt at this tier.
        recent_attempts = get_attempts_for_tier(state["student_id"], state["topic_id"], current_tier, limit=3)
        attempts_at_tier = len(recent_attempts) + 1  # including this one, now concluding

        if attempts_at_tier < 3:
            # Still building the trend window -- just step the cap down for the next
            # attempt at this same tier (3 -> 2 -> 1). No decision yet.
            new_tier = current_tier
            new_hint_cap = max(1, hint_cap - 1)
        else:
            # This is the 3rd (or later, defensively) attempt at this tier -- decide now,
            # using this attempt plus the two most recent prior ones, oldest first.
            chronological = list(reversed(recent_attempts))[-2:] + [
                {"hints_used": hints_used, "hint_cap": hint_cap}
            ]

            decreasing = all(
                chronological[i]["hints_used"] > chronological[i + 1]["hints_used"]
                for i in range(len(chronological) - 1)
            )
            maxed_out_every_time = all(a["hints_used"] >= a["hint_cap"] for a in chronological)

            if decreasing and not maxed_out_every_time:
                new_tier = current_tier + 1
            else:
                new_tier = max(1, current_tier - 1)
            new_hint_cap = STARTING_HINT_CAP

    update_student_skill_state(StudentSkillStateUpdate(
        student_id=state["student_id"],
        topic_id=state["topic_id"],
        current_tier=new_tier,
        mastery_score=state["mastery_score"],
        dependency_score=state["dependency_score"],
        hint_cap=new_hint_cap,
        updated_at=datetime.now()
    ))

    run_test_result = state.get("run_test_result") or {}
    final_result = SubmitResult.PASS if run_test_result.get("all_passed") else SubmitResult.FAIL

    conclude_attempt(ProblemAttemptUpdate(
        attempt_id=state["attempt_id"],
        result=final_result,
        escalated=escalated,
        escalation_reason=escalation_reason
    ))

    turn_number = count_turns_for_attempt(state["attempt_id"]) + 1
    log_interaction(InteractionLogEntry(
        student_id=state["student_id"],
        problem_id=state["problem_id"],
        topic_id=state["topic_id"],
        attempt_id=state["attempt_id"],
        reasoning_state=ReasoningState.NONE,
        submit_result=final_result,
        non_progress_flag=attempt["struggle_detected"],
        turn_number=turn_number,
        hints_used_this_turn=0,
        mastery_score=state["mastery_score"],
        dependency_score=state["dependency_score"],
        current_tier=new_tier,
        turn_summary=f"Attempt submitted. Result: {final_result.value}. Bypass count: {state.get('bypass_count', 0)}.",
        run_test_result=run_test_result,
        created_at=datetime.now()
    ))

    return {
        "tier": new_tier,
        "hint_cap": new_hint_cap,
        "escalated": escalated,
        "escalation_reason": escalation_reason,
        "final_result": final_result,
    }


def serve_node(state: GraphState) -> GraphState:
    # Returns the next problem's data only. Opening it (inserting its own
    # Problem_Attempts row) happens via a separate call once the student actually
    # starts it -- that's a fresh attempt lifecycle, not a continuation of this one.
    next_problem = get_next_problem(state["student_id"], state["topic_id"], state.get("tier"))
    if next_problem is None:
        return {
            "problem_id": None,
            "problem_name": None,
            "problem_description": "No more problems available at this tier. Please check back later.",
        }
    return {
        "problem_id": next_problem["problem_id"],
        "problem_description": next_problem["problem_description"],
        "problem_name": next_problem["problem_name"],
    }


def route_turn(state: GraphState) -> str:
    if state.get("submit_clicked"):
        if state.get("engagement_occurred"):
            return "update"
        return "end"  # engagement gate not satisfied -- frontend should already block this

    if state.get("run_test_clicked"):
        run_test_result = state.get("run_test_result") or {}
        if run_test_result.get("all_passed") and state.get("engagement_occurred"):
            return "log_test_pass"
        return "probe"

    pending = state.get("pending_response_to")
    idle = state.get("idle_seconds", 0)
    repeated_edits = state.get("repeated_edit_count", 0)
    struggling = idle >= ONGOING_IDLE_SECONDS or repeated_edits >= ONGOING_REPEATED_EDIT_THRESHOLD

    if state.get("student_message"):
        if pending == "probe":
            return "evaluate_reasoning"
        return "probe"  # spontaneous message, or a reply to a check-in/hint -- fresh probe cycle

    # No message, no run test, no submit this invocation -- a heartbeat/idle check.
    if pending == "hint":
        return "escalate" if struggling else "end"

    if pending == "checkin":
        return "intervene_hint" if struggling else "end"

    if pending == "probe":
        if state.get("is_opening_probe"):
            # The opening sequence's own one-time timer -- not code-activity-dependent,
            # since the whole point is the student hasn't acted at all yet.
            return "intervene_checkin" if idle >= OPENING_FOLLOWUP_SECONDS else "end"
        # Any other outstanding probe falls back to the standard struggle checks.
        return "intervene_checkin" if struggling else "end"

    if not state.get("engagement_occurred") and idle >= OPENING_SILENCE_SECONDS:
        return "probe"  # proactive opening probe

    return "intervene_checkin" if struggling else "end"


graph_builder = StateGraph(GraphState)
graph_builder.add_node("probe", probe_node)
graph_builder.add_node("evaluate_reasoning", evaluate_reasoning)
graph_builder.add_node("intervene_checkin", intervene_checkin_node)
graph_builder.add_node("intervene_hint", intervene_hint_node)
graph_builder.add_node("escalate", escalate_node)
graph_builder.add_node("log_test_pass", log_test_pass_node)
graph_builder.add_node("update", update_node)
graph_builder.add_node("decide", decide_node)
graph_builder.add_node("serve", serve_node)

graph_builder.add_conditional_edges(
    START,
    route_turn,
    {
        "probe": "probe",
        "evaluate_reasoning": "evaluate_reasoning",
        "intervene_checkin": "intervene_checkin",
        "intervene_hint": "intervene_hint",
        "escalate": "escalate",
        "log_test_pass": "log_test_pass",
        "update": "update",
        "end": END,
    }
)

# Every branch except Submit's ends the invocation here -- this is the "pause" point.
# The three genuine tools (correctness checker, problem retriever, concept-note
# retriever) are NOT implemented as real tool-calling in this pass -- they remain
# plain placeholder function calls (e.g. get_next_problem above), per the current
# design scope. Real tool registration is separate, future work.
graph_builder.add_edge("probe", END)
graph_builder.add_edge("evaluate_reasoning", END)
graph_builder.add_edge("intervene_checkin", END)
graph_builder.add_edge("intervene_hint", END)
graph_builder.add_edge("escalate", END)
graph_builder.add_edge("log_test_pass", END)
graph_builder.add_edge("update", "decide")
graph_builder.add_edge("decide", "serve")
graph_builder.add_edge("serve", END)

# Real checkpointer for pause/resume persistence, keyed by attempt_id as the
# thread_id -- callers pass config={"configurable": {"thread_id": attempt_id}}
# to graph.invoke()/graph.stream(). Short-term/live-conversation state
# (pending_response_to, probe_question, tier, hint_cap, hints_used,
# engagement_occurred, struggle_detected, mastery_score, dependency_score,
# is_opening_probe) now lives here across invocations instead of being
# reconstructed from the database on every turn: a caller only needs to supply
# the fields specific to this invocation (student_message, student_code,
# idle_seconds, run_test_clicked, etc.) plus the identity/starting fields on
# the one call that opens a brand new attempt -- LangGraph merges partial
# state updates into whatever this thread_id already has checkpointed.
#
# autocommit/prepare_threshold=0/dict_row match what PostgresSaver itself uses
# internally (see PostgresSaver.from_conn_string) and are required for it to
# work correctly against the pool.
_checkpoint_pool = ConnectionPool(
    conninfo=checkpoint_db_url,
    max_size=10,
    kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    open=True,
)
checkpointer = PostgresSaver(_checkpoint_pool)
checkpointer.setup()  # no-op after the first run; creates/migrates checkpoint tables.

graph = graph_builder.compile(checkpointer=checkpointer)


