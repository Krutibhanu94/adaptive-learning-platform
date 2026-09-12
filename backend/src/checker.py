import json
import os
import tempfile

import docker
from docker.errors import ImageNotFound

# Rebuilt from python:3.12-slim + sortedcontainers (see sandbox/Dockerfile) -- the only
# third-party import found across every prelude currently in the database.
SANDBOX_IMAGE_TAG = "adaptive-tutor-sandbox:latest"
SANDBOX_DIR = os.path.join(os.path.dirname(__file__), "..", "sandbox")

MEMORY_LIMIT = "256m"
NANO_CPUS = 500_000_000  # 0.5 CPU
TIMEOUT_SECONDS = 10

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = docker.from_env()
    return _client


def _ensure_image(client):
    try:
        client.images.get(SANDBOX_IMAGE_TAG)
    except ImageNotFound:
        client.images.build(path=SANDBOX_DIR, tag=SANDBOX_IMAGE_TAG, rm=True)


def _build_harness(prelude: str, student_code: str, entry_point: str, test_harness: str, examples: list) -> str:
    # prelude and test_harness come from the trusted, dataset-seeded problems table --
    # running them is safe in that sense. The actual security boundary is the container
    # itself (no network, resource caps, non-root, ephemeral), not anything in this
    # script; student_code is untrusted and runs with the same trust level as the rest
    # of this file precisely because the container is what contains it, not the script.
    #
    # test_harness defines check(candidate) as a sequence of asserts -- Python halts at
    # the first failing one, so we only ever get the first failure, not all of them
    # (a deliberate choice: a probe should ground itself in one concrete case, not
    # enumerate everything wrong at once). candidate is wrapped to log every call's
    # args/kwargs/result as it happens, so when an assert fails we can report exactly
    # what the student's code actually returned for that case, not just that it didn't
    # match -- check(candidate)'s own asserts don't preserve that on their own.
    #
    # examples (the same LeetCode-style input/output strings the frontend shows *before*
    # any run) get a second, best-effort pass only when the full suite already passed:
    # each "Input:" string is parsed into real call arguments with eval() -- safe here for
    # the same reason as everywhere else in this script, since examples are dataset-
    # provided, not student-provided -- and the candidate is called directly so the
    # actual output can be shown alongside the example, without claiming a per-example
    # pass/fail verdict (this harness has no reliable way to compare a structural return
    # type like a linked list or tree against the example's expected-output string the
    # same way check(candidate) itself does internally). A parse/type mismatch (e.g. an
    # example whose input is itself a structural type the naive eval-based parser can't
    # reconstruct) degrades that one example to "unavailable" rather than failing the run.
    return f"""
import json
import traceback

{prelude}

{student_code}

_call_log = []

def _wrap_candidate(fn):
    def _wrapper(*args, **kwargs):
        result = fn(*args, **kwargs)
        _call_log.append({{"args": args, "kwargs": kwargs, "result": result}})
        return result
    return _wrapper

candidate = _wrap_candidate({entry_point})

{test_harness}

def _parse_example_input(input_str):
    kwargs = {{}}
    parts = []
    depth = 0
    in_str = None
    current = []
    for ch in input_str:
        if in_str:
            current.append(ch)
            if ch == in_str:
                in_str = None
            continue
        if ch in "\\"'":
            in_str = ch
            current.append(ch)
            continue
        if ch in "([{{":
            depth += 1
        elif ch in ")]}}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    for part in parts:
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        kwargs[key.strip()] = eval(val.strip())
    return kwargs

def _run_examples():
    results = []
    for example in json.loads({json.dumps(json.dumps(examples))}):
        entry = {{"input": example.get("input"), "output": example.get("output"), "actual": None}}
        try:
            parsed_args = _parse_example_input(example.get("input") or "")
            entry["actual"] = repr(candidate(**parsed_args))
        except Exception:
            entry["actual"] = None
        results.append(entry)
    return results

try:
    check(candidate)
    print(json.dumps({{"all_passed": True, "failure": None, "examples": _run_examples()}}))
except Exception as e:
    tb = traceback.extract_tb(e.__traceback__)
    source_line = tb[-1].line if tb else None
    last_call = _call_log[-1] if _call_log else None
    print(json.dumps({{
        "all_passed": False,
        "failure": {{
            "error": type(e).__name__ + ": " + str(e),
            "assertion": source_line,
            "call_args": repr(last_call["args"]) if last_call else None,
            "call_kwargs": repr(last_call["kwargs"]) if last_call else None,
            "actual": repr(last_call["result"]) if last_call else None,
        }},
    }}))
"""


def run_correctness_check(problem: dict, student_code: str) -> dict:
    """
    Runs student_code against problem's test_harness (the dataset's own
    check(candidate) correctness function) inside an isolated, resource-limited Docker
    container (no network, memory/CPU caps, non-root, read-only root filesystem,
    auto-removed after the run). Returns {"all_passed": bool, "failures": [...], "examples": [...] or None},
    matching the shape probe_node already expects from run_test_result -- "failures"
    holds zero or one entries (the first case that failed, with rich detail: the
    assertion source, the call args/kwargs, and what the student's code actually
    returned), not one entry per test case. "examples" is only populated when
    all_passed is True -- the same (up to 3) example cases the frontend shows before any
    run, each with the actual output the candidate produced for it (or None if that one
    example's input couldn't be reconstructed from its display string). No per-example
    pass/fail verdict -- see _build_harness for why.
    """
    examples = (problem.get("test_cases") or [])[:3]
    harness_source = _build_harness(
        problem["test_harness_prelude"],
        student_code,
        problem["entry_point"],
        problem["test_harness"],
        examples,
    )

    client = _get_client()
    _ensure_image(client)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(harness_source)
        harness_path = f.name

    container = None
    try:
        container = client.containers.run(
            SANDBOX_IMAGE_TAG,
            command=["python", "/harness.py"],
            volumes={harness_path: {"bind": "/harness.py", "mode": "ro"}},
            mem_limit=MEMORY_LIMIT,
            memswap_limit=MEMORY_LIMIT,  # prevents swap from bypassing the memory cap
            nano_cpus=NANO_CPUS,
            network_disabled=True,
            read_only=True,
            tmpfs={"/tmp": "size=16m"},
            user="nobody",
            detach=True,
        )

        try:
            wait_result = container.wait(timeout=TIMEOUT_SECONDS)
            exit_code = wait_result.get("StatusCode", 1)
        except Exception:
            container.kill()
            return {
                "all_passed": False,
                "failures": [{"error": f"Execution timed out after {TIMEOUT_SECONDS}s"}],
            }

        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")

        if exit_code != 0:
            return {
                "all_passed": False,
                "failures": [{"error": f"Execution failed (exit {exit_code}): {logs.strip()[-2000:]}"}],
            }

        try:
            parsed = json.loads(logs.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            return {
                "all_passed": False,
                "failures": [{"error": f"Could not parse harness output: {logs.strip()[-2000:]}"}],
            }

        if parsed.get("all_passed"):
            return {"all_passed": True, "failures": [], "examples": parsed.get("examples") or []}
        failure = parsed.get("failure")
        return {"all_passed": False, "failures": [failure] if failure else []}
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:
                pass
        os.unlink(harness_path)
