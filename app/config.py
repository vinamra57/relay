import os

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

DATABASE_PATH = os.getenv("DATABASE_PATH", "aria_health.db")
DATABASE_URL = os.getenv("DATABASE_URL", "")
DATABASE_MAX_CONNECTIONS = int(os.getenv("DATABASE_MAX_CONNECTIONS", "5"))
SEED_DEMO_CASES = os.getenv("SEED_DEMO_CASES", "true").lower() == "true"

# Modal inference (OpenAI-compatible vLLM endpoint)
MODAL_ENDPOINT_URL = os.getenv("MODAL_ENDPOINT_URL", "")
MODAL_MODEL_NAME = os.getenv("MODAL_MODEL_NAME", "Qwen/Qwen3-8B")

# Perplexity Sonar API (GP contact resolution)
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")

# ElevenLabs Conversational AI (voice agent)
ELEVENLABS_AGENT_ID = os.getenv("ELEVENLABS_AGENT_ID", "")
ELEVENLABS_PHONE_NUMBER_ID = os.getenv("ELEVENLABS_PHONE_NUMBER_ID", "")

# Hospital callback number for GP voicemail
HOSPITAL_CALLBACK_NUMBER = os.getenv("HOSPITAL_CALLBACK_NUMBER", "+1-555-0100")

# GCP (optional)
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")
GCP_PUBSUB_TOPIC = os.getenv("GCP_PUBSUB_TOPIC", "")
GCP_PUBSUB_SUBSCRIPTION_PREFIX = os.getenv("GCP_PUBSUB_SUBSCRIPTION_PREFIX", "aria-health-events")
