import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from datasets import load_dataset
from db import get_topics, insert_problem, ProblemInsert
import json

ds = load_dataset("newfacade/LeetCodeDataset", split="train")
print("problems:", ds[0])

def format_title(task_id: str) -> str:
    return task_id.replace("-", " ").title()

TOPIC_TAG_MAP = {
    "Array": "Arrays",
    "String": "Strings",
    "Sorting": "Sorting",
    "Stack": "Stacks",
    "Recursion": "Recursion",
}

def match_topics(tags: list) -> list:
    matched = []
    for tag in tags:
        if tag in TOPIC_TAG_MAP:
            topic_name = TOPIC_TAG_MAP[tag]
            if topic_name not in matched:
                matched.append(topic_name)
    return matched


DIFFICULTY_TO_TIER = {
    "Easy": 1,
    "Medium": 2,
    "Hard": 3,
}

def get_tier(difficulty: str) -> int:
    return DIFFICULTY_TO_TIER[difficulty]

# The topics are fetched from the database and a mapping from topic name to topic id is created. 
# This mapping is used to associate problems with their corresponding topics when inserting them into the database.
topics = get_topics()
topic_name_to_id = {topic["topic_name"]: topic["topic_id"] for topic in topics}

# The script iterates over each problem in the dataset, matches its tags to the corresponding topics, and prepares the problem data for insertion into the database.
for problem in ds:
    matched_topics = match_topics(problem["tags"])

    if not matched_topics:
        continue

    problem_name = format_title(problem["task_id"])
    problem_description = problem["problem_description"]
    test_cases = json.dumps(problem["input_output"])
    tier = get_tier(problem["difficulty"])

    for topic_name in matched_topics:
        topic_id = topic_name_to_id.get(topic_name)

        problem_entry = ProblemInsert(
            problem_name=problem_name,
            problem_description=problem_description,
            test_cases=test_cases,
            tier=tier,
            topic_id=topic_id,
        )

        insert_problem(problem_entry)
