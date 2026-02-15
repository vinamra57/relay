import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# LLM configuration
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "auto")
LLM_DEFAULT_TIER = os.getenv("LLM_DEFAULT_TIER", "fast")
LLM_MODEL_FAST = os.getenv("LLM_MODEL_FAST", "")
LLM_MODEL_STANDARD = os.getenv("LLM_MODEL_STANDARD", "")
LLM_MODEL_HIGH = os.getenv("LLM_MODEL_HIGH", "")

# Demo/Debug mode (explicit)
DUMMY_MODE = os.getenv("DUMMY_MODE", "false").lower() in ("1", "true", "yes", "on")
VOICE_DUMMY = os.getenv("VOICE_DUMMY", "false").lower() in ("1", "true", "yes", "on")
GP_CALLS_ENABLED = os.getenv("GP_CALLS_ENABLED", "true").lower() in ("1", "true", "yes", "on")

DATABASE_PATH = os.getenv("DATABASE_PATH", "relay.db")

DATABASE_URL = os.getenv("DATABASE_URL", "")
DATABASE_MAX_CONNECTIONS = int(os.getenv("DATABASE_MAX_CONNECTIONS", "5"))
SEED_DEMO_CASES = os.getenv("SEED_DEMO_CASES", "true").lower() == "true"

BASE_DIR = Path(__file__).resolve().parent.parent
GP_DOCUMENT_PATH = os.getenv(
    "GP_DOCUMENT_PATH",
    str(BASE_DIR / "data" / "doc" / "Medical Record.pdf"),
)
GP_DOCUMENT_DELAY_SECONDS = int(os.getenv("GP_DOCUMENT_DELAY_SECONDS", "60"))
GP_CALL_PENDING_SECONDS = int(os.getenv("GP_CALL_PENDING_SECONDS", "8"))

# Perplexity Sonar API (GP contact resolution)
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")

# Twilio (outbound voice calls)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")

# ElevenLabs Conversational AI (voice agent)
ELEVENLABS_AGENT_ID = os.getenv("ELEVENLABS_AGENT_ID", "")
ELEVENLABS_PHONE_NUMBER_ID = os.getenv("ELEVENLABS_PHONE_NUMBER_ID", "")

# Hospital callback number for GP voicemail
HOSPITAL_CALLBACK_NUMBER = os.getenv("HOSPITAL_CALLBACK_NUMBER", "+1-555-0100")

# Email address for GPs to send medical records to
RECORDS_EMAIL = os.getenv("RECORDS_EMAIL", "records@relay.health")

# GCP (optional)
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")
GCP_PUBSUB_TOPIC = os.getenv("GCP_PUBSUB_TOPIC", "")
GCP_PUBSUB_SUBSCRIPTION_PREFIX = os.getenv("GCP_PUBSUB_SUBSCRIPTION_PREFIX", "relay-events")
