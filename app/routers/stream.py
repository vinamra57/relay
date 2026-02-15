import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import ANTHROPIC_API_KEY
from app.database import get_db
from app.models.nemsis import NEMSISRecord
from app.services.event_bus import event_bus
from app.services.nemsis_extractor import extract_nemsis
from app.services.transcription import TranscriptionService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/stream/{case_id}")
async def stream_endpoint(websocket: WebSocket, case_id: str):
    """WebSocket endpoint: voice → raw text (ElevenLabs), raw text → table (Claude NEMSIS)."""
    await websocket.accept()
    db = await get_db()

    # Verify case exists
    row = await db.execute("SELECT id FROM cases WHERE id = ?", (case_id,))
    case = await row.fetchone()
    if not case:
        await websocket.send_json(
            {"type": "error", "message": f"Case {case_id} not found"}
        )
        await websocket.close()
        return

    # State for this session
    accumulated_transcript = ""
    current_nemsis = NEMSISRecord()
    extraction_lock = asyncio.Lock()
    background_tasks: set[asyncio.Task] = set()

    async def _safe_send(data: dict) -> None:
        """Send JSON to websocket, logging on failure."""
        try:
            await websocket.send_json(data)
        except Exception:
            logger.debug("WebSocket send failed (client may have disconnected)")

    async def on_partial(text: str):
        """Handle partial transcript from ElevenLabs."""
        await _safe_send({"type": "transcript_partial", "text": text})

    async def on_committed(text: str):
        """Handle committed transcript from ElevenLabs."""
        nonlocal accumulated_transcript

        now = datetime.now(timezone.utc).isoformat()

        # Save raw segment to database
        await db.execute(
            "INSERT INTO transcripts (case_id, segment_text, timestamp, segment_type)"
            " VALUES (?, ?, ?, ?)",
            (case_id, text, now, "committed"),
        )

        # Append to accumulated transcript
        accumulated_transcript += (" " + text) if accumulated_transcript else text
        await db.execute(
            "UPDATE cases SET full_transcript = ?, updated_at = ? WHERE id = ?",
            (accumulated_transcript, now, case_id),
        )
        await db.commit()

        # Send committed transcript to client
        await _safe_send(
            {
                "type": "transcript_committed",
                "text": text,
                "full_transcript": accumulated_transcript,
            }
        )

        # Run NEMSIS extraction only when Claude (Anthropic) key is set (no API key = skip entirely, no errors)
        if ANTHROPIC_API_KEY:
            task = asyncio.create_task(_run_extraction(text, now))
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)

    async def _run_extraction(segment_text: str, timestamp: str):
        nonlocal current_nemsis

        async with extraction_lock:
            try:
                current_nemsis = await extract_nemsis(
                    accumulated_transcript, current_nemsis
                )

                nemsis_json = current_nemsis.model_dump_json()
                now = datetime.now(timezone.utc).isoformat()

                patient = current_nemsis.patient
                patient_name = (
                    " ".join(
                        filter(
                            None,
                            [patient.patient_name_first, patient.patient_name_last],
                        )
                    )
                    or None
                )

                await db.execute(
                    """UPDATE cases SET
                        nemsis_data = ?, patient_name = ?, patient_address = ?,
                        patient_age = ?, patient_gender = ?, updated_at = ?
                    WHERE id = ?""",
                    (
                        nemsis_json,
                        patient_name,
                        patient.patient_address,
                        patient.patient_age,
                        patient.patient_gender,
                        now,
                        case_id,
                    ),
                )
                await db.commit()

                nemsis_dict = current_nemsis.model_dump()
                await _safe_send({"type": "nemsis_update", "nemsis": nemsis_dict})
                await event_bus.publish(case_id, {
                    "type": "nemsis_update",
                    "nemsis": nemsis_dict,
                    "patient_name": patient_name,
                })
            except Exception as e:
                logger.error("NEMSIS extraction error: %s", e)

    # Load existing case data
    row = await db.execute(
        "SELECT full_transcript, nemsis_data FROM cases WHERE id = ?",
        (case_id,),
    )
    existing = await row.fetchone()
    if existing:
        accumulated_transcript = existing["full_transcript"] or ""
        try:
            current_nemsis = NEMSISRecord.model_validate_json(existing["nemsis_data"])
        except Exception:
            logger.warning("Failed to parse NEMSIS data for case %s", case_id)
            current_nemsis = NEMSISRecord()

    # Start transcription service
    stt = TranscriptionService(on_partial=on_partial, on_committed=on_committed)
    await stt.start()

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)

            if data.get("type") == "audio_chunk":
                await stt.send_audio(data.get("data", ""))
            elif data.get("type") == "end_call":
                break
    except WebSocketDisconnect:
        logger.info(f"Client disconnected from case {case_id}")
    except Exception as e:
        logger.error(f"WebSocket error for case {case_id}: {e}")
    finally:
        await stt.stop()
        # Mark case as completed if it was active
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "UPDATE cases SET status = 'completed', updated_at = ?"
            " WHERE id = ? AND status = 'active'",
            (now, case_id),
        )
        await db.commit()
