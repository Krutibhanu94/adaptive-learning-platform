"""
Manually try the correctness checker against a real problem, outside the graph/API --
useful for testing checker.py in isolation before it's wired into /turn.

Usage:
    python scripts/try_checker.py <problem_id_or_name> <path_to_solution.py>

Examples:
    python scripts/try_checker.py 1 my_solution.py
    python scripts/try_checker.py "Two Sum" my_solution.py
    python scripts/try_checker.py "Add Two Numbers" my_solution.py

Requires Docker Desktop to be running.
"""
import json
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from db import engine
from sqlalchemy import text
from checker import run_correctness_check


def find_problem(identifier: str):
    with engine.connect() as conn:
        if identifier.isdigit():
            row = conn.execute(
                text("SELECT * FROM problems WHERE problem_id = :id"),
                {"id": int(identifier)},
            ).fetchone()
        else:
            row = conn.execute(
                text("SELECT * FROM problems WHERE problem_name ILIKE :name LIMIT 1"),
                {"name": identifier},
            ).fetchone()
        return dict(row._mapping) if row else None


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    identifier, code_path = sys.argv[1], sys.argv[2]

    problem = find_problem(identifier)
    if not problem:
        print(f"No problem found matching {identifier!r}")
        sys.exit(1)

    with open(code_path) as f:
        student_code = f.read()

    print(f"Problem: {problem['problem_name']} (id={problem['problem_id']}, tier={problem['tier']})")
    print(f"Starter code:\n{problem['starter_code']}")
    print()
    print("Running in sandbox (first run may take a moment if the image needs building)...")
    print()

    result = run_correctness_check(problem, student_code)

    if result["all_passed"]:
        print("ALL TESTS PASSED")
    else:
        print("FAILED")
        for failure in result["failures"]:
            print(json.dumps(failure, indent=2))


if __name__ == "__main__":
    main()
