from langchain_anthropic import ChatAnthropic
from sqlalchemy import text
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

from config import engine


class ChatRequest(BaseModel):
    message: str

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

model = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0)

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.post("/ping")
async def ping(request: ChatRequest):
    response = model.invoke(request.message)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT version();"))
        db_version = result.fetchone()[0]

    return {"reply": response.content, "db_check": db_version}
