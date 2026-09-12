"""
Evaluates agent.py's evaluate_reasoning classifier against wmcnicho/StudyChat, a dataset
of real student prompts to a general ChatGPT assistant in an AI course (NOT our
Socratic-verification-specific context -- see the caveat printed at the end of the report).

Step 1: sample prompts, show the dataset's own llm_label distribution (a dialogue-act
category, not a genuine/bypass label -- e.g. "conceptual_questions>Computer Science").
Step 2: map each sampled prompt's label to genuine/bypass/excluded using GENUINE_LABELS/
BYPASS_LABELS below (agreed on by looking at step 1's real distribution+examples -- not
assumed; every excluded category isn't a reasoning response at all: pasted context, error
messages, chit-chat, prose-editing requests, etc., with no honest ground truth for how a
genuine/bypass classifier should treat them).
Step 3: run every included prompt through the REAL evaluate_reasoning function from
agent.py (not a reimplementation) against one dedicated throwaway attempt (never
testuser's real data -- deleted at the end), and report agreement + a confusion matrix
(false-genuine and false-bypass rates kept separate, since they have different
consequences: a false-genuine lets a bypass slip through undetected, a false-bypass makes
the tutor needlessly redirect a student who was already reasoning genuinely).

StudyChat is a gated dataset -- requires HF_TOKEN in backend/.env (on an account that has
already accepted the dataset's terms on Hugging Face); huggingface_hub picks it up
automatically, no login step needed beyond that.

Usage:
    python scripts/studychat_eval.py
"""
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

import random
from collections import Counter

from datasets import load_dataset
from dotenv import load_dotenv

load_dotenv()

from db import engine, ProblemAttemptInsert, insert_attempt  # noqa: E402
from sqlalchemy import text  # noqa: E402
from agent import evaluate_reasoning  # noqa: E402

SAMPLE_SIZE = 120
SEED = 42
PROMPT_FIELD = "prompt"
LABEL_FIELD = "llm_label"

# Agreed mapping (see module docstring) -- anything not listed in either set below is
# excluded, not forced into a bucket.
BYPASS_LABELS = {
    "writing_request>Write Code",
    "verification>Verify Code",
    "editing_request>Edit Code",
}
GENUINE_LABELS = {
    "conceptual_questions>Computer Science",
    "conceptual_questions>Python Library",
    "conceptual_questions>Programming Language",
    "conceptual_questions>Programming Tools",
    "conceptual_questions>Mathematics",
    "conceptual_questions>Other Concept",
    "contextual_questions>Assignment Clarification",
    "contextual_questions>Code Explanation",
    "contextual_questions>Interpret Output",
}

# StudyChat prompts are standalone messages to a general assistant -- there's no real
# probe_question they were replying to. A single generic, neutral Socratic probe stands
# in for all of them; this is exactly the "general classification behavior, not in-context
# performance" limitation the report calls out explicitly.
GENERIC_PROBE_QUESTION = (
    "What's your thinking so far on this, and why do you think that approach would work?"
)

# A real, existing problem/topic -- only used to satisfy problem_attempts'/interaction_log's
# foreign keys for the one throwaway attempt this eval runs against. Not otherwise relevant.
THROWAWAY_PROBLEM_ID = 1
THROWAWAY_TOPIC_ID = 7


def load_sample():
    if not os.getenv("HF_TOKEN"):
        print("HF_TOKEN not set in backend/.env -- see the setup instructions before running this.")
        sys.exit(1)

    ds = load_dataset("wmcnicho/StudyChat", split="train")
    print(f"Full dataset size: {len(ds)} interactions")

    if PROMPT_FIELD not in ds.column_names or LABEL_FIELD not in ds.column_names:
        print(
            f"\nExpected fields {PROMPT_FIELD!r}/{LABEL_FIELD!r} not found in "
            f"{ds.column_names} -- update PROMPT_FIELD/LABEL_FIELD above to match."
        )
        sys.exit(1)

    candidate_indices = [
        i for i, prompt in enumerate(ds[PROMPT_FIELD])
        if prompt and prompt.strip()
    ]

    random.seed(SEED)
    sample_size = min(SAMPLE_SIZE, len(candidate_indices))
    sample_indices = random.sample(candidate_indices, sample_size)
    return ds.select(sample_indices)


def print_label_distribution(sample):
    label_counts = Counter(row[LABEL_FIELD]["label"] for row in sample)
    print(f"\n{LABEL_FIELD} distribution across {len(sample)} sampled prompts:")
    for label, count in label_counts.most_common():
        print(f"  {count:4d}  {label!r}")


def map_ground_truth(label):
    if label in BYPASS_LABELS:
        return "bypass"
    if label in GENUINE_LABELS:
        return "genuine"
    return None  # excluded


def setup_throwaway_attempt():
    with engine.connect() as conn:
        conn.execute(text(
            "INSERT INTO students (username, student_name) "
            "VALUES ('studychat_eval', 'studychat_eval') ON CONFLICT (username) DO NOTHING"
        ))
        conn.commit()
        student_id = conn.execute(
            text("SELECT student_id FROM students WHERE username = 'studychat_eval'")
        ).fetchone()[0]

    attempt_id = insert_attempt(ProblemAttemptInsert(
        student_id=student_id,
        problem_id=THROWAWAY_PROBLEM_ID,
        topic_id=THROWAWAY_TOPIC_ID,
        tier=1,
        hint_cap=3,
    ))
    return student_id, attempt_id


def cleanup_throwaway_attempt(student_id, attempt_id):
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM interaction_log WHERE attempt_id = :id"), {"id": attempt_id})
        conn.execute(text("DELETE FROM problem_attempts WHERE attempt_id = :id"), {"id": attempt_id})
        conn.execute(text("DELETE FROM student_skill_state WHERE student_id = :id"), {"id": student_id})
        conn.execute(text("DELETE FROM students WHERE student_id = :id"), {"id": student_id})
        conn.commit()


def run_evaluation(sample, student_id, attempt_id):
    cases = []
    for row in sample:
        ground_truth = map_ground_truth(row[LABEL_FIELD]["label"])
        if ground_truth is None:
            continue
        cases.append({
            "prompt": row[PROMPT_FIELD],
            "label": row[LABEL_FIELD]["label"],
            "ground_truth": ground_truth,
        })

    print(f"\n{len(cases)} of {len(sample)} sampled prompts fall into genuine/bypass "
          f"after excluding non-reasoning categories -- these are what actually get evaluated.")

    results = []
    for i, case in enumerate(cases):
        state = {
            "probe_question": GENERIC_PROBE_QUESTION,
            "student_message": case["prompt"],
            "attempt_id": attempt_id,
            "student_id": student_id,
            "problem_id": THROWAWAY_PROBLEM_ID,
            "topic_id": THROWAWAY_TOPIC_ID,
            "genuine_reasoning_shown": False,
            "tier": 1,
            "mastery_score": 0.0,
            "dependency_score": 0.0,
            "struggle_detected": False,
        }
        # The real, unmodified node function -- including its own DB writes
        # (mark_attempt_engaged, log_interaction) against the throwaway attempt above.
        outcome = evaluate_reasoning(state)
        prediction = outcome["reasoning_state"]  # "genuine" or "bypass"
        # turn_summary is the model's own one-sentence explanation of its classification --
        # kept so a false-bypass/false-genuine case can be inspected concretely afterward,
        # not just counted.
        results.append({**case, "prediction": prediction, "turn_summary": outcome.get("turn_summary")})
        if (i + 1) % 10 == 0 or i + 1 == len(cases):
            print(f"  evaluated {i + 1}/{len(cases)}")

    return results


def print_report(results):
    total = len(results)
    agree = sum(1 for r in results if r["prediction"] == r["ground_truth"])

    genuine_truth = [r for r in results if r["ground_truth"] == "genuine"]
    bypass_truth = [r for r in results if r["ground_truth"] == "bypass"]

    false_bypass = sum(1 for r in genuine_truth if r["prediction"] == "bypass")
    false_genuine = sum(1 for r in bypass_truth if r["prediction"] == "genuine")

    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"Evaluated sample size: {total} (after excluding non-reasoning categories "
          f"from the original {SAMPLE_SIZE}-prompt sample)")
    print(f"Overall agreement rate: {agree}/{total} = {agree / total:.1%}")

    print("\nConfusion matrix:")
    print(f"  Ground truth = genuine ({len(genuine_truth)}):  "
          f"predicted genuine = {len(genuine_truth) - false_bypass}, "
          f"predicted bypass = {false_bypass}  "
          f"(false-bypass rate = {false_bypass / len(genuine_truth):.1%})" if genuine_truth else "  (none)")
    print(f"  Ground truth = bypass  ({len(bypass_truth)}):  "
          f"predicted bypass = {len(bypass_truth) - false_genuine}, "
          f"predicted genuine = {false_genuine}  "
          f"(false-genuine rate = {false_genuine / len(bypass_truth):.1%})" if bypass_truth else "  (none)")

    false_bypass_cases = [r for r in genuine_truth if r["prediction"] == "bypass"]
    false_genuine_cases = [r for r in bypass_truth if r["prediction"] == "genuine"]

    print(f"\nFalse-bypass cases ({len(false_bypass_cases)} total) -- ground truth genuine, "
          f"predicted bypass. All of them, with the model's own stated reasoning:")
    for r in false_bypass_cases:
        prompt_preview = r["prompt"].strip().replace("\n", " ")[:150]
        print(f"\n  [{r['label']!r}]")
        print(f"    prompt:       {prompt_preview}")
        print(f"    turn_summary: {r['turn_summary']}")

    print(f"\nFalse-genuine cases ({len(false_genuine_cases)} total) -- ground truth bypass, "
          f"predicted genuine. All of them, with the model's own stated reasoning:")
    for r in false_genuine_cases:
        prompt_preview = r["prompt"].strip().replace("\n", " ")[:150]
        print(f"\n  [{r['label']!r}]")
        print(f"    prompt:       {prompt_preview}")
        print(f"    turn_summary: {r['turn_summary']}")

    print("\nCAVEAT: StudyChat was collected from a general AI-course ChatGPT assistant, not "
          "our Socratic-verification-specific context. Every prompt here was evaluated against "
          "a single generic, neutral placeholder probe_question (there was no real prior probe "
          "these students were actually replying to), and with genuine_reasoning_shown always "
          "False (no multi-turn history). This measures the classifier's general genuine/bypass "
          "judgment on realistic student text, not its in-context performance inside an actual "
          "tutoring conversation.")


def main():
    sample = load_sample()
    print_label_distribution(sample)

    student_id, attempt_id = setup_throwaway_attempt()
    try:
        results = run_evaluation(sample, student_id, attempt_id)
    finally:
        cleanup_throwaway_attempt(student_id, attempt_id)

    print_report(results)


if __name__ == "__main__":
    main()
