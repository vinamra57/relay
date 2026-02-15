"""Webhook endpoints for GP voice call callbacks.

Receives post-call data from ElevenLabs Conversational AI after a GP call
completes, and updates the case record and audit log accordingly.
"""

import logging

from fastapi import APIRouter, Request

from app.database import get_db
from app.services.event_bus import event_bus

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/webhook/elevenlabs/post-call")
async def elevenlabs_post_call(request: Request) -> dict:
    """Receive post-call transcription webhook from ElevenLabs.

    ElevenLabs sends this webhook after a call completes with:
    - conversation_id: matches the ID returned from the outbound call API
    - transcript: full conversation transcript
    - call_status: completed, no-answer, busy, failed, etc.
    """
    try:
        payload = await request.json()
    except Exception:
        logger.error("Failed to parse ElevenLabs webhook payload")
        return {"status": "error", "message": "Invalid JSON"}

    conversation_id = payload.get("conversation_id", "")
    transcript = payload.get("transcript", "")
    call_status = payload.get("call_status", payload.get("status", "unknown"))

    logger.info(
        "ElevenLabs post-call webhook: conversation_id=%s, status=%s",
        conversation_id, call_status,
    )

    if not conversation_id:
        logger.warning("Post-call webhook missing conversation_id")
        return {"status": "ok", "message": "No conversation_id provided"}

    db = await get_db()

    # Look up case_id from gp_call_audit by conversation_id
    audit_row = await db.fetch_one(
        "SELECT case_id FROM gp_call_audit WHERE conversation_id = ?",
        (conversation_id,),
    )

    if not audit_row:
        logger.warning(
            "No audit record found for conversation_id=%s", conversation_id
        )
        return {"status": "ok", "message": "No matching audit record"}

    case_id = audit_row["case_id"]

    # Extract transcript text — handle various ElevenLabs webhook formats
    transcript_text = ""
    if isinstance(transcript, str):
        transcript_text = transcript
    elif isinstance(transcript, list):
        # List of turn objects: [{"role": "agent", "text": "..."}, ...]
        parts = []
        for turn in transcript:
            role = turn.get("role", "unknown")
            text = turn.get("text", turn.get("message", ""))
            if text:
                parts.append(f"[{role}] {text}")
        transcript_text = "\n".join(parts)
    elif isinstance(transcript, dict):
        transcript_text = transcript.get("text", str(transcript))

    # Map call status to outcome
    outcome = "answered" if call_status == "completed" else call_status

    # Update audit record
    await db.execute(
        "UPDATE gp_call_audit SET transcript = ?, outcome = ? "
        "WHERE conversation_id = ?",
        (transcript_text, outcome, conversation_id),
    )

    # Update case record
    await db.execute(
        "UPDATE cases SET gp_call_status = ?, gp_call_transcript = ? "
        "WHERE id = ?",
        (outcome, transcript_text, case_id),
    )
    await db.commit()

    logger.info(
        "GP call completed for case %s: status=%s, transcript_len=%d",
        case_id, outcome, len(transcript_text),
    )

    # Push event to dashboard via WebSocket event bus
    await event_bus.publish(case_id, {
        "type": "gp_call_transcript",
        "call_status": outcome,
        "transcript": transcript_text,
        "conversation_id": conversation_id,
    })

    return {"status": "ok"}
