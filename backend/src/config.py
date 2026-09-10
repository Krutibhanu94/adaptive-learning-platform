import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from langchain_anthropic import ChatAnthropic

load_dotenv()

db_url = (
    f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
)

engine = create_engine(db_url)

# Plain psycopg (v3) conninfo for LangGraph's PostgresSaver checkpointer, which
# is a separate driver from the psycopg2 engine above.
checkpoint_db_url = (
    f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
)

model = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0)

