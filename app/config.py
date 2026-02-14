import os
from dotenv import load_dotenv

load_dotenv()

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
DUMMY_MODE = os.getenv("DUMMY_MODE", "true").lower() == "true"
DATABASE_PATH = os.getenv("DATABASE_PATH", "aria_health.db")
