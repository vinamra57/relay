"""GP caller orchestrator — resolves GP contact, places voice call, logs audit.

Flow:
1. Check preconditions (GP name or confirmed GP phone must be available)
2. Resolve phone number (use confirmed number or look up via Perplexity Sonar)
3. Place outbound call (ElevenLabs + Twilio)
4. Log call to gp_call_audit table
5. Return status string
"""

import logging
from datetime import UTC, datetime

from app.config import HOSPITAL_CALLBACK_NUMBER
from app.database import get_db
from app.services.gp_lookup import lookup_gp_phone
from app.services.voice_agent import place_gp_call

logger = logging.getLogger(__name__)


async def call_gp(
    patient_name: str,
    patient_age: str,
    patient_gender: str,
    patient_address: str,
    gp_name: str | None = None,
    gp_phone: str | None = None,
    gp_practice_name: str | None = None,
    patient_dob: str | None = None,
    case_id: str | None = None,
) -> str:
    """Orchestrate GP contact: resolve number, place call, log audit.

    Args:
        patient_name: Patient full name
        patient_age: Patient age
        patient_gender: Patient gender
        patient_address: Patient address (used as location for GP lookup)
        gp_name: GP or doctor name (from transcript)
        gp_phone: Confirmed GP phone number (from transcript)
        gp_practice_name: Practice name (from transcript)
        patient_dob: Patient date of birth
        case_id: Case ID for audit and call reference

    Returns:
        Status string describing the call outcome.
    """
    # 1. Check preconditions
    if not gp_name and not gp_phone:
        logger.info("No GP contact available for %s — skipping GP call", patient_name)
        return "No GP contact available — GP call not triggered."

    logger.info(
        "GP call triggered for %s (gp_name=%s, gp_phone=%s, practice=%s)",
        patient_name, gp_name, gp_phone, gp_practice_name,
    )

    # 2. Resolve phone number
    phone_number = None
    lookup_result = None

    if gp_phone:
        # Use confirmed GP phone directly
        phone_number = gp_phone
        logger.info("Using confirmed GP phone: %s", phone_number)
    else:
        # Look up via Perplexity Sonar
        location = patient_address or "unknown location"
        lookup_result = await lookup_gp_phone(
            gp_name=gp_name or "",
            location=location,
            practice_name=gp_practice_name,
        )
        if lookup_result:
            phone_number = lookup_result["phone"]
            logger.info(
                "GP phone resolved via lookup: %s (%s)",
                phone_number, lookup_result.get("practice_name"),
            )
        else:
            logger.warning("Could not resolve GP phone number for %s", gp_name)
            await _log_audit(
                case_id=case_id,
                phone_number="",
                patient_name=patient_name,
                patient_dob=patient_dob,
                outcome="lookup_failed",
            )
            return f"Could not resolve GP phone number for {gp_name}."

    # 3. Place call
    call_result = await place_gp_call(
        phone_number=phone_number,
        patient_name=patient_name,
        patient_dob=patient_dob,
        hospital_callback=HOSPITAL_CALLBACK_NUMBER,
        case_id=case_id,
    )

    # 4. Log audit
    outcome = call_result.get("status", "unknown")
    await _log_audit(
        case_id=case_id,
        phone_number=phone_number,
        patient_name=patient_name,
        patient_dob=patient_dob,
        outcome=outcome,
        call_sid=call_result.get("call_sid"),
        conversation_id=call_result.get("conversation_id"),
        transcript=call_result.get("transcript"),
    )

    # 5. Update case record if we have a case_id
    if case_id:
        try:
            db = await get_db()
            await db.execute(
                "UPDATE cases SET gp_call_status = ?, gp_call_transcript = ?, "
                "updated_at = ? WHERE id = ?",
                (
                    outcome,
                    call_result.get("transcript", ""),
                    datetime.now(UTC).isoformat(),
                    case_id,
                ),
            )
            await db.commit()
        except Exception as e:
            logger.error("Failed to update case GP call status: %s", e)

    # 6. Build status string
    if outcome == "dummy":
        return (
            f"[DUMMY] GP call placed to {phone_number} for {patient_name}. "
            f"{call_result.get('transcript', '')}"
        )
    elif outcome == "skipped":
        return "GP call skipped (disabled by configuration)."
    elif outcome == "initiated":
        return (
            f"GP call initiated to {phone_number} for {patient_name}. "
            f"Call SID: {call_result.get('call_sid')}. "
            f"Awaiting GP response via webhook."
        )
    elif outcome == "error":
        return (
            f"GP call failed for {patient_name}: {call_result.get('error', 'unknown error')}"
        )
    else:
        return f"GP call status: {outcome}"


async def _log_audit(
    case_id: str | None,
    phone_number: str,
    patient_name: str | None = None,
    patient_dob: str | None = None,
    outcome: str = "unknown",
    call_sid: str | None = None,
    conversation_id: str | None = None,
    transcript: str | None = None,
) -> None:
    """Insert a record into the gp_call_audit table."""
    try:
        db = await get_db()
        await db.execute(
            "INSERT INTO gp_call_audit "
            "(case_id, call_time, phone_number, patient_name, patient_dob, "
            "outcome, call_sid, conversation_id, transcript) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                case_id or "",
                datetime.now(UTC).isoformat(),
                phone_number,
                patient_name,
                patient_dob,
                outcome,
                call_sid,
                conversation_id,
                transcript,
            ),
        )
        await db.commit()
        logger.info(
            "GP call audit logged: case=%s, outcome=%s, phone=%s",
            case_id, outcome, phone_number,
        )
    except Exception as e:
        logger.error("Failed to log GP call audit: %s", e)
