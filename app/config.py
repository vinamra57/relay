import os

from dotenv import load_dotenv

load_dotenv()

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DATABASE_PATH = os.getenv("DATABASE_PATH", "aria_health.db")

# Modal inference (OpenAI-compatible vLLM endpoint)
MODAL_ENDPOINT_URL = os.getenv("MODAL_ENDPOINT_URL", "")
MODAL_MODEL_NAME = os.getenv(
    "MODAL_MODEL_NAME", "Qwen/Qwen3-8B"
)

# Perplexity Sonar API (GP contact resolution)
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")

# ElevenLabs Conversational AI (voice agent)
ELEVENLABS_AGENT_ID = os.getenv("ELEVENLABS_AGENT_ID", "")
ELEVENLABS_PHONE_NUMBER_ID = os.getenv("ELEVENLABS_PHONE_NUMBER_ID", "")

# Hospital callback number for GP voicemail
HOSPITAL_CALLBACK_NUMBER = os.getenv("HOSPITAL_CALLBACK_NUMBER", "+1-555-0100")

# Email address for GPs to send medical records to
RECORDS_EMAIL = os.getenv("RECORDS_EMAIL", "records@ariahealth.com")
