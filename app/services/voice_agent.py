"""Voice call agent using ElevenLabs Conversational AI + Twilio.

Places outbound calls to GP practices via the ElevenLabs native Twilio
integration. The ElevenLabs agent handles the conversation script, voicemail
detection, and response capture.
"""

import logging

import httpx

from app.config import (
    ELEVENLABS_AGENT_ID,
    ELEVENLABS_API_KEY,
    ELEVENLABS_PHONE_NUMBER_ID,
    HOSPITAL_CALLBACK_NUMBER,
)

logger = logging.getLogger(__name__)

ELEVENLABS_OUTBOUND_URL = "https://api.elevenlabs.io/v1/convai/twilio/outbound-call"
ELEVENLABS_TIMEOUT = 30.0


async def place_gp_call(
    phone_number: str,
    patient_name: str,
    patient_dob: str | None,
    hospital_callback: str | None = None,
    case_id: str | None = None,
) -> dict:
    """Place an outbound call to a GP practice via ElevenLabs + Twilio.

    Args:
        phone_number: GP practice phone number to call (E.164 or standard format)
        patient_name: Patient name for the call script
        patient_dob: Patient date of birth for identification
        hospital_callback: Hospital number for voicemail callback
        case_id: Case ID for reference in the call

    Returns:
        Dict with keys: call_sid, conversation_id, status
    """
    if not ELEVENLABS_API_KEY:
        logger.error("ELEVENLABS_API_KEY not set, cannot place GP call")
        return {"call_sid": None, "conversation_id": None, "status": "error",
                "error": "ELEVENLABS_API_KEY not configured"}

    if not ELEVENLABS_AGENT_ID:
        logger.error("ELEVENLABS_AGENT_ID not set, cannot place GP call")
        return {"call_sid": None, "conversation_id": None, "status": "error",
                "error": "ELEVENLABS_AGENT_ID not configured"}

    if not ELEVENLABS_PHONE_NUMBER_ID:
        logger.error("ELEVENLABS_PHONE_NUMBER_ID not set, cannot place GP call")
        return {"call_sid": None, "conversation_id": None, "status": "error",
                "error": "ELEVENLABS_PHONE_NUMBER_ID not configured"}

    callback = hospital_callback or HOSPITAL_CALLBACK_NUMBER

    payload = {
        "agent_id": ELEVENLABS_AGENT_ID,
        "agent_phone_number_id": ELEVENLABS_PHONE_NUMBER_ID,
        "to_number": phone_number,
        "conversation_initiation_client_data": {
            "dynamic_variables": {
                "patient_name": patient_name,
                "patient_dob": patient_dob or "unknown",
                "hospital_callback": callback,
                "case_id": case_id or "unknown",
            }
        },
    }

    try:
        async with httpx.AsyncClient(timeout=ELEVENLABS_TIMEOUT) as client:
            resp = await client.post(
                ELEVENLABS_OUTBOUND_URL,
                headers={
                    "xi-api-key": ELEVENLABS_API_KEY,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()

        data = resp.json()
        result = {
            "call_sid": data.get("callSid"),
            "conversation_id": data.get("conversation_id"),
            "status": "initiated",
        }
        logger.info(
            "GP call initiated: call_sid=%s, conversation_id=%s, to=%s",
            result["call_sid"], result["conversation_id"], phone_number,
        )
        return result

    except httpx.HTTPStatusError as e:
        logger.error(
            "ElevenLabs outbound call failed (HTTP %s): %s",
            e.response.status_code, e.response.text[:500],
        )
        return {"call_sid": None, "conversation_id": None, "status": "error",
                "error": f"HTTP {e.response.status_code}"}
    except Exception as e:
        logger.error("GP call failed: %s", e)
        return {"call_sid": None, "conversation_id": None, "status": "error",
                "error": str(e)}


def _dummy_call(patient_name: str, case_id: str | None) -> dict:
    """Return synthetic call result for dummy mode."""
    return {
        "call_sid": f"dummy-sid-{case_id or 'none'}",
        "conversation_id": f"dummy-conv-{case_id or 'none'}",
        "status": "dummy",
        "transcript": (
            f"[DUMMY] GP practice answered. Confirmed patient {patient_name} is on file. "
            f"Allergies: Penicillin. Current medications: Metformin 500mg, Lisinopril 10mg. "
            f"Recent history: Type 2 diabetes, hypertension. Last visit: 3 weeks ago."
        ),
    }
