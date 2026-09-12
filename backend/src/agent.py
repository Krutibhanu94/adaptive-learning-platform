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
# Ongoing idle/struggle thresholds are implementation defaults -- the spec names these
# triggers but doesn't give numbers.
OPENING_SILENCE_SECONDS = 180
OPENING_FOLLOWUP_SECONDS = 300
ONGOING_IDLE_SECONDS = 180
STARTING_HINT_CAP = 3
# Struggle detection: two independent checks per code_update against a recent window,
# not a raw count of similar edits (that was fragile -- see CLAUDE.md's turn-taking
# notes for the two real bugs it produced). "Similar" is judged by SequenceMatcher
# against any snapshot still in the window, not just the immediately-previous one, so
# oscillating between a couple of similar-but-not-identical attempts is still caught.
# "Growing" (net length increase over the window) vetoes it: a student slowly building a
# solution incrementally has high similarity between adjacent snapshots purely because
# each edit is small -- that's progress, not struggle, regardless of similarity.
CODE_SNAPSHOT_WINDOW = 5
CODE_SIMILARITY_THRESHOLD = 0.9
CODE_GROWTH_THRESHOLD_CHARS = 20
# How long code has to stay in a similar, non-growing state before it counts as struggle
# -- set at parity with ONGOING_IDLE_SECONDS as a starting point, not derived from
# anything authoritative.
STRUGGLE_TIME_THRESHOLD_SECONDS = 180


class GraphState(TypedDict, total=False):
    # Identity for this attempt.
    student_id: int
    topic_id: int
    problem_id: int
    attempt_id: int
    problem_description: str
    # Not read anywhere within agent.py itself -- only ever set by serve_node, to be
    # relayed back through the API response for the frontend to display. Was missing
    # from this schema entirely; LangGraph only tracks channels for declared keys, so
    # serve_node's "problem_name" was being silently dropped, never actually reaching
    # callers despite being returned.
    problem_name: str | None

    # This invocation's input -- one external event per graph run.
    student_message: str | None
    student_code: str | None
    code_changed: bool
    idle_seconds: int
    # Computed server-side from stuck_since (see below), the same way idle_seconds is
    # computed from last_activity_at -- agent.py never does its own datetime arithmetic.
    struggle_duration_seconds: int
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
    # to the standard idle/struggle checks, not this timer.
    is_opening_probe: bool
    # Sticky, attempt-scoped: True from the first time evaluate_reasoning classifies a
    # reply as genuine, for the rest of the attempt -- same pattern as
    # engagement_occurred/struggle_detected. This is what lets a later unprompted "let
    # me code first" (with no new reasoning attached) be accepted as earned readiness
    # rather than evasive bypass -- the trust comes from having reasoned genuinely at
    # some point in this attempt, not from the immediately preceding message.
    genuine_reasoning_shown: bool
    # Server-computed bookkeeping the /turn endpoint uses to derive idle_seconds and
    # struggle_duration_seconds each call -- not sent by the frontend directly, just
    # persisted here via the checkpointer like everything else in this block.
    last_activity_at: str | None
    # Rolling window (most recent last, capped at CODE_SNAPSHOT_WINDOW) of code reported
    # via code_update/run_test/submit -- used both for the similarity check and as the
    # growth-comparison baseline (current length vs. the oldest length still in the
    # window). Replaces a single last_student_code field.
    recent_code_snapshots: list[str]
    # ISO timestamp marking when the current "similar to something recent, and not
    # growing" streak began, or None when not currently in one (either genuinely
    # progressing, or too early to tell). Set on the first qualifying code_update, left
    # unchanged while the streak continues (so duration accumulates), cleared back to
    # None by genuine growth, a genuinely different (if not yet longer) attempt, a
    # message, run_test, submit, or an intervention firing (the same "give a fresh start"
    # treatment last_activity_at already gets in each of those cases).
    stuck_since: str | None

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
    # Plain "pass"/"fail" string, not the SubmitResult enum -- same reasoning as
    # reasoning_state above: never read back as an enum, and the checkpointer's msgpack
    # serializer doesn't natively support custom Enum types.
    final_result: str


class ReasoningEvaluation(BaseModel):
    classification: Literal["genuine", "bypass"]
    summary: str
    # Independent of classification: true if the student is signaling, in their own
    # words, that they want to stop discussing and go implement their own
    # understanding -- regardless of whether the tutor's last message offered that as
    # an option. Demanding the tutor reveal or confirm the answer is never this, no
    # matter how it's phrased -- that stays classification="bypass".
    wants_to_proceed: bool = False


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
    genuine_shown = state.get("genuine_reasoning_shown", False)

    genuine_shown_context = ""
    if genuine_shown:
        genuine_shown_context = """

    Note: the student has already demonstrated genuine reasoning earlier in this
    attempt. If their current reply doesn't contain new reasoning but signals they
    want to move on to writing code (e.g. "let me code this up", "I'm ready now",
    "I think I've got it"), that's earned readiness worth respecting, not evasion --
    set wants_to_proceed to true. Only classify as bypass if they're demanding the
    answer be revealed or confirmed rather than choosing to go apply their own
    understanding."""

    prompt = f"""You are evaluating a student's response to a Socratic tutoring question.
    The tutor asked: "{state['probe_question']}"
    The student replied: "{state['student_message']}"

    Classify this reply as one of two categories:
    - "genuine" — the student attempts to reason through the question, even imperfectly,
      or asks a genuine clarifying question of their own.
    - "bypass" — the student demands the direct answer, restates without engaging, or
      otherwise avoids ever reasoning through the problem.

    Also set wants_to_proceed to true if the student is signaling -- in their own
    words, regardless of whether you just offered this as an option -- that they want
    to stop discussing and go try implementing their own understanding in code (e.g.
    "let me code this up", "I'm going to try it", "I think I've got it, let's move
    on"). This is different from demanding the tutor reveal or confirm the answer
    ("just tell me", "is this right?") -- that's still bypass, not a proceed signal,
    no matter how it's phrased.
    {genuine_shown_context}

    Then, write a short one-sentence summary of what happened this turn, including a short
    direct quote from the student's reply if it's the specific reason behind your
    classification.
    """

    evaluation = model.with_structured_output(ReasoningEvaluation).invoke(prompt)
    reasoning_state = ReasoningState(evaluation.classification)
    # Belt-and-suspenders: bypass always wins even if the model mis-flags
    # wants_to_proceed on a "just tell me" style reply -- demanding the answer never
    # counts as a legitimate exit, no matter the phrasing.
    wants_to_proceed = evaluation.wants_to_proceed and reasoning_state != ReasoningState.BYPASS
    genuine_shown_next = genuine_shown or reasoning_state == ReasoningState.GENUINE

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

    if wants_to_proceed:
        # Earned or demonstrated-in-the-moment readiness -- let them proceed. No
        # further probe; pending clears so idle detection resumes meaning "gone quiet"
        # again instead of "ignored a reply."
        return {
            "reasoning_state": reasoning_state.value,
            "turn_summary": evaluation.summary,
            "engagement_occurred": True,
            "pending_response_to": None,
            "is_opening_probe": False,
            "genuine_reasoning_shown": genuine_shown_next,
        }

    # Either remaining classification still needs a reply -- silence here is what made
    # a genuine answer indistinguishable from being ignored, which in turn made the next
    # idle check misfire a "you paused" message at a student who was actually just
    # waiting on the tutor. Both branches generate a fresh probe_question and re-arm
    # pending_response_to="probe" so the next reply gets evaluated the same way.
    if reasoning_state == ReasoningState.BYPASS:
        # A bypass reply leaves the original probe unanswered -- acknowledge it briefly
        # and redirect back to that question instead of moving on. Doesn't reveal
        # anything or scold -- just confirms the agent noticed and is still waiting.
        followup_prompt = f"""You are a Socratic tutor. You asked the student: "{state['probe_question']}"
        Instead of engaging with that question, the student said: "{state['student_message']}"

        Write a single short, gentle sentence that acknowledges what they said without
        judgment, and redirects them back to your original question. Do not answer the
        question yourself, do not lecture or scold, and do not repeat the full original
        question verbatim -- just a brief, warm nudge back to it."""
    else:
        # A genuine reply gets a real reply back: a brief acknowledgment (never
        # confirming correctness -- that stays off-limits) plus exactly one further
        # question. A student who wants to stop here can and will say so in their own
        # words (handled above via wants_to_proceed), so this doesn't need to manufacture
        # an explicit either/or every time -- that just made the dialogue feel stilted.
        followup_prompt = f"""You are a Socratic tutor. You asked the student: "{state['probe_question']}"
        The student reasoned through it and replied: "{state['student_message']}"

        Write a short response with two parts:
        1. Briefly acknowledge their reasoning without confirming whether it's correct
           or complete, and without revealing or implying the answer.
        2. Ask exactly one further question that surfaces a genuinely relevant angle
           they haven't considered yet -- an edge case, a complexity concern, a
           specific detail worth thinking about. If there's honestly nothing
           substantive left worth probing, ask directly whether they feel ready to move
           on to code instead of manufacturing a question for its own sake."""

    followup = model.invoke(followup_prompt)

    return {
        "reasoning_state": reasoning_state.value,
        "turn_summary": evaluation.summary,
        "engagement_occurred": True,
        "probe_question": followup.content,
        "pending_response_to": "probe",
        "is_opening_probe": False,
        "genuine_reasoning_shown": genuine_shown_next,
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
        # Same fresh-start treatment as a real hint firing (see run_intervention) --
        # without it, the very next heartbeat re-checks an already-past-threshold
        # condition and escalates again almost immediately, giving no real window to
        # act on "you can submit whenever you're ready."
        "idle_seconds": 0,
        "struggle_duration_seconds": 0,
        "last_activity_at": datetime.now().isoformat(),
        "stuck_since": None,
    }


def run_intervention(state: GraphState, tier: Literal["checkin", "hint"]) -> GraphState:
    if tier == "hint" and state.get("hints_used", 0) >= state.get("hint_cap", STARTING_HINT_CAP):
        return decline_hint(state)

    hints_used_this_turn = 0

    if tier == "checkin":
        # Idle and struggle are genuinely different states and shouldn't share one
        # generic message: idle means no activity at all (possibly thinking, possibly
        # away); struggle means actively working but stuck in a non-progressing pattern.
        # Telling an actively-typing student they've "paused" is inaccurate and
        # confusing -- idle wins when both happen to be true (see route_turn), since it's
        # the more literally-accurate description of what's happening right now.
        if state.get("idle_seconds", 0) >= ONGOING_IDLE_SECONDS:
            prompt = f"""The student appears to have paused while working on this problem:
            {state['problem_description']}

            Write a brief, warm check-in message asking why they've paused — without
            assuming they're stuck, since they may just be thinking or took a short break.
            Invite them to share what's going on. Keep the tone professional and direct,
            matching a thoughtful tutor — no emoji, no exclamation-heavy or overly casual
            phrasing."""
        else:
            prompt = f"""The student is actively working on this problem, but their code
            has stayed in a similar, non-progressing state for a while:
            {state['problem_description']}

            Write a brief, warm check-in that acknowledges they're actively engaged --
            do not say or imply they've paused or stopped, since they haven't. Ask how
            it's going, and invite them to share what's on their mind or where they feel
            stuck, without assuming they ARE stuck. Keep the tone professional and
            direct, matching a thoughtful tutor — no emoji, no exclamation-heavy or
            overly casual phrasing."""
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
        # A fresh start on both struggle signals the moment an intervention fires --
        # without this, the very next heartbeat re-checks an already-past-threshold
        # idle_seconds/struggle_duration_seconds and escalates again almost immediately,
        # giving no real window for the student to notice and respond. If they go right
        # back to the same stuck pattern, stuck_since restarts fresh from that moment;
        # if they stop touching code entirely, idle correctly takes over instead.
        "idle_seconds": 0,
        "struggle_duration_seconds": 0,
        "last_activity_at": datetime.now().isoformat(),
        "stuck_since": None,
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
    # None on a student's genuinely first-ever attempt at this topic -- no row has been
    # written yet (the first write happens below, via update_student_skill_state).
    # Same defaults /start already uses when seeding a brand new attempt.
    skill_state = get_student_skill_state(state["student_id"], state["topic_id"])
    current_tier = skill_state["current_tier"] if skill_state else 1
    hint_cap = skill_state["hint_cap"] if skill_state else STARTING_HINT_CAP
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
        "final_result": final_result.value,
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
    struggle_duration = state.get("struggle_duration_seconds", 0)
    struggling = idle >= ONGOING_IDLE_SECONDS or struggle_duration >= STRUGGLE_TIME_THRESHOLD_SECONDS

    if state.get("student_message"):
        if pending == "probe":
            return "evaluate_reasoning"
        return "probe"  # spontaneous message, or a reply to a check-in/hint -- fresh probe cycle

    # Once escalated, the agent stops proactively pushing -- no further check-ins,
    # hints, or opening probes -- for the rest of the attempt. The handoff to a human
    # is meant to be a genuine pause, not something routed around in the background.
    # Not a permanent lockout: a real student message is handled above, before this
    # gate, so normal tutoring still resumes if the student re-engages.
    if state.get("escalated"):
        return "end"

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


