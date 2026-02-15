import os

from dotenv import load_dotenv

load_dotenv()

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DATABASE_PATH = os.getenv("DATABASE_PATH", "aria_health.db")

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
