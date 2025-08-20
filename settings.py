import os
from dotenv import load_dotenv
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

PG_HOST = os.getenv("PG_HOST")
PG_USER=os.getenv("PG_USER")
PG_PASSWORD=os.getenv("PG_PASSWORD")
PG_DB=os.getenv("PG_DB")
PG_PORT=os.getenv("PG_PORT")

DB_DSN = f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DB}"

BROKER_URL = os.getenv("BROKER_URL")