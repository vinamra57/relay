import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.database import get_db
from app.models.nemsis import NEMSISRecord
from app.services.transcription import TranscriptionService
from app.services.nemsis_extractor import extract_nemsis
from app.services.core_info_checker import is_core_info_complete, trigger_downstream

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/stream/{case_id}")
async def stream_endpoint(websocket: WebSocket, case_id: str):
    """WebSocket endpoint for streaming audio from wearable mic.

    Flow:
    1. Receives audio chunks from client
    2. Relays to ElevenLabs for transcription (or dummy mode)
    3. On committed transcript: runs GPT-5.2 NEMSIS extraction
    4. Pushes transcript + NEMSIS updates back to client
    5. When core info complete: triggers GP + medical DB lookups
    """
    await websocket.accept()
    db = await get_db()

    # Verify case exists
    row = await db.execute("SELECT id FROM cases WHERE id = ?", (case_id,))
    case = await row.fetchone()
    if not case:
        await websocket.send_json({"type": "error", "message": f"Case {case_id} not found"})
        await websocket.close()
        return

    # State for this session
    accumulated_transcript = ""
    current_nemsis = NEMSISRecord()
    core_triggered = False
    extraction_lock = asyncio.Lock()

    async def on_partial(text: str):
        """Handle partial transcript from ElevenLabs."""
        try:
            await websocket.send_json({"type": "transcript_partial", "text": text})
        except Exception:
            pass

    async def on_committed(text: str):
        """Handle committed transcript from ElevenLabs."""
        nonlocal accumulated_transcript, current_nemsis, core_triggered

        now = datetime.now(timezone.utc).isoformat()

        # Save raw segment to database
        await db.execute(
            "INSERT INTO transcripts (case_id, segment_text, timestamp, segment_type) VALUES (?, ?, ?, ?)",
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
        try:
            await websocket.send_json({
                "type": "transcript_committed",
                "text": text,
                "full_transcript": accumulated_transcript,
            })
        except Exception:
            pass

        # Run NEMSIS extraction (non-blocking but serialized)
        asyncio.create_task(_run_extraction(text, now))

    async def _run_extraction(segment_text: str, timestamp: str):
        nonlocal current_nemsis, core_triggered

        async with extraction_lock:
            try:
                current_nemsis = await extract_nemsis(accumulated_transcript, current_nemsis)

                nemsis_json = current_nemsis.model_dump_json()
                now = datetime.now(timezone.utc).isoformat()

                # Update NEMSIS data in DB
                patient = current_nemsis.patient
                patient_name = " ".join(
                    filter(None, [patient.patient_name_first, patient.patient_name_last])
                ) or None

                await db.execute(
                    """UPDATE cases SET
                        nemsis_data = ?, patient_name = ?, patient_address = ?,
                        patient_age = ?, patient_gender = ?, updated_at = ?
                    WHERE id = ?""",
                    (
                        nemsis_json, patient_name, patient.patient_address,
                        patient.patient_age, patient.patient_gender, now, case_id,
                    ),
                )
                await db.commit()

                # Send NEMSIS update to client
                try:
                    await websocket.send_json({
                        "type": "nemsis_update",
                        "nemsis": current_nemsis.model_dump(),
                    })
                except Exception:
                    pass

                # Check core info completeness
                if not core_triggered and is_core_info_complete(current_nemsis):
                    core_triggered = True
                    await db.execute(
                        "UPDATE cases SET core_info_complete = 1, updated_at = ? WHERE id = ?",
                        (now, case_id),
                    )
                    await db.commit()

                    try:
                        await websocket.send_json({
                            "type": "core_info_complete",
                            "message": "Core patient info collected. Triggering downstream lookups.",
                        })
                    except Exception:
                        pass

                    # Trigger GP + medical DB in parallel
                    gp_response, db_response = await trigger_downstream(current_nemsis)

                    await db.execute(
                        "UPDATE cases SET gp_response = ?, medical_db_response = ?, updated_at = ? WHERE id = ?",
                        (gp_response, db_response, datetime.now(timezone.utc).isoformat(), case_id),
                    )
                    await db.commit()

                    try:
                        await websocket.send_json({
                            "type": "downstream_complete",
                            "gp_response": gp_response,
                            "medical_db_response": db_response,
                        })
                    except Exception:
                        pass

            except Exception as e:
                logger.error(f"NEMSIS extraction error: {e}")

    # Load existing case data
    row = await db.execute("SELECT full_transcript, nemsis_data, core_info_complete FROM cases WHERE id = ?", (case_id,))
    existing = await row.fetchone()
    if existing:
        accumulated_transcript = existing["full_transcript"] or ""
        try:
            current_nemsis = NEMSISRecord.model_validate_json(existing["nemsis_data"])
        except Exception:
            current_nemsis = NEMSISRecord()
        core_triggered = bool(existing["core_info_complete"])

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
            "UPDATE cases SET status = 'completed', updated_at = ? WHERE id = ? AND status = 'active'",
            (now, case_id),
        )
        await db.commit()
