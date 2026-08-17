import os
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from sqlalchemy import create_engine, text

load_dotenv()

db_url = (
    f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
)

engine = create_engine(db_url)

with engine.connect() as conn:
    result = conn.execute(text("SELECT version();"))
    print(result.fetchone())

model = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0)  

response = model.invoke("Hello, how are you?")

print(response.content)