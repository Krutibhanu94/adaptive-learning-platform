from fastapi import APIRouter
from config import model
from db import check_db_connection, get_student, get_topics
from pydantic import BaseModel

class ChatRequest(BaseModel):
    message: str

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


@router.post("/ping")
async def ping(request: ChatRequest):
    response = model.invoke(request.message)
    db_version = check_db_connection()
    return {"reply": response.content, "db_check": db_version}
