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
    RECORDS_EMAIL,
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
    chief_complaint: str | None = None,
    records_email: str | None = None,
) -> dict:
    """Place an outbound call to a GP practice via ElevenLabs + Twilio.

    Args:
        phone_number: GP practice phone number to call (E.164 or standard format)
        patient_name: Patient name for the call script
        patient_dob: Patient date of birth for identification
        hospital_callback: Hospital number for voicemail callback
        case_id: Case ID for reference in the call
        chief_complaint: Brief description of what happened to the patient
        records_email: Email address where GP should send medical records

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
    situation = chief_complaint or "a medical emergency"
    email = records_email or RECORDS_EMAIL

    prompt = (
        f"You are a hospital coordinator calling a GP practice on behalf of emergency services. "
        f"Be professional, calm, and concise.\n\n"
        f"Your patient {patient_name} (date of birth: {patient_dob or 'unknown'}) is currently "
        f"being transported by ambulance due to {situation}.\n\n"
        f"Your goals:\n"
        f"1. Introduce yourself as calling from the emergency coordination team.\n"
        f"2. Tell them their patient {patient_name} is in an ambulance due to {situation}.\n"
        f"3. Ask them to send the patient's medical records to {email}.\n"
        f"4. Provide the callback number {callback} for any follow-up.\n"
        f"5. Thank them and end the call.\n\n"
        f"If you reach voicemail, leave a clear message with the patient name, situation, "
        f"the email {email} for records, and the callback number {callback}.\n"
        f"Keep it short — this is urgent."
    )

    first_message = (
        f"Hello, this is the emergency coordination team. I'm calling about your patient "
        f"{patient_name}, who is currently being transported by ambulance due to {situation}. "
        f"We'd like to request their medical records — could you please send them to {email}?"
    )

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
            },
            "conversation_config_override": {
                "agent": {
                    "prompt": {"prompt": prompt},
                    "first_message": first_message,
                },
            },
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
