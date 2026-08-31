import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from db import insert_topic, insert_student

TOPICS = [
    ("Arrays", "Working with sequences of elements stored in contiguous memory."),
    ("Strings", "Working with sequences of characters and text-based data."),
    ("Sorting", "Arranging elements in a specific order."),
    ("Stacks", "A LIFO data structure supporting push and pop operations."),
    ("Recursion", "Solving problems by having a function call itself."),
]

STUDENTS =[
    ("testuser", "Test Student"),
]

for topic_name, topic_description in TOPICS:
    insert_topic(topic_name, topic_description)

for username, student_name in STUDENTS:
    insert_student(username, student_name)

print("Topics and students loaded successfully.")