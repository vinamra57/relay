import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import ANTHROPIC_API_KEY
from app.database import get_db
from app.models.nemsis import NEMSISRecord
from app.services.core_info_checker import is_core_info_complete
from app.services.event_bus import event_bus
from app.services.nemsis_extractor import extract_nemsis
from app.services.transcription import TranscriptionService

logger = logging.getLogger(__name__)
router = APIRouter()

# Word count threshold - trigger extraction after this many new words
WORD_COUNT_THRESHOLD = 10
# Max interval between extractions (fallback if not enough words)
MAX_EXTRACTION_INTERVAL = 3


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
    current_partial = ""  # Current partial transcript (not yet committed)
    current_nemsis = NEMSISRecord()
    extraction_lock = asyncio.Lock()
    core_info_sent = False  # Track if we've notified client about core info completion
    last_extracted_word_count = 0  # Track word count at last extraction
    extraction_task: asyncio.Task | None = None
    stop_extraction = asyncio.Event()
    extract_now = asyncio.Event()  # Signal to extract immediately

    async def _safe_send(data: dict) -> None:
        """Send JSON to websocket, logging on failure."""
        try:
            await websocket.send_json(data)
        except Exception:
            logger.debug("WebSocket send failed (client may have disconnected)")

    async def on_partial(text: str):
        """Handle partial transcript from ElevenLabs."""
        nonlocal current_partial
        current_partial = text
        await _safe_send({"type": "transcript_partial", "text": text})
        
        # Check if we have enough new words to trigger extraction
        full_text = (accumulated_transcript + " " + text).strip() if accumulated_transcript else text
        current_word_count = len(full_text.split())
        if current_word_count - last_extracted_word_count >= WORD_COUNT_THRESHOLD:
            extract_now.set()  # Signal extraction loop to run now

    async def on_committed(text: str):
        """Handle committed transcript from ElevenLabs."""
        nonlocal accumulated_transcript, current_partial

        now = datetime.now(timezone.utc).isoformat()
        current_partial = ""  # Reset partial since it's now committed

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

        # Send committed transcript to client immediately (for UI display)
        await _safe_send(
            {
                "type": "transcript_committed",
                "text": text,
                "full_transcript": accumulated_transcript,
            }
        )
        # Trigger extraction on commit as well
        extract_now.set()

    async def _extraction_loop():
        """Background task that extracts NEMSIS data based on word count or max interval."""
        nonlocal current_nemsis, core_info_sent, last_extracted_word_count

        while not stop_extraction.is_set():
            # Wait for either: extract_now signal, max interval, or stop signal
            try:
                done, pending = await asyncio.wait(
                    [
                        asyncio.create_task(extract_now.wait()),
                        asyncio.create_task(stop_extraction.wait()),
                    ],
                    timeout=MAX_EXTRACTION_INTERVAL,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                # Cancel pending tasks
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            except asyncio.TimeoutError:
                pass

            if stop_extraction.is_set():
                break
            
            # Reset extract_now for next trigger
            extract_now.clear()

            # Get full text including current partial
            full_text = accumulated_transcript
            if current_partial:
                full_text = (full_text + " " + current_partial).strip() if full_text else current_partial

            # Only extract if there's enough new words
            current_word_count = len(full_text.split()) if full_text else 0
            if current_word_count <= last_extracted_word_count:
                continue

            # Skip if no API key
            if not ANTHROPIC_API_KEY:
                continue

            async with extraction_lock:
                try:
                    new_words = current_word_count - last_extracted_word_count
                    logger.info("Running NEMSIS extraction (%d new words, %d total)", 
                               new_words, current_word_count)
                    
                    current_nemsis = await extract_nemsis(
                        full_text, current_nemsis
                    )
                    last_extracted_word_count = current_word_count

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

                    # Check if core info is now complete
                    core_complete = is_core_info_complete(current_nemsis)

                    await db.execute(
                        """UPDATE cases SET
                            nemsis_data = ?, patient_name = ?, patient_address = ?,
                            patient_age = ?, patient_gender = ?, core_info_complete = ?, updated_at = ?
                        WHERE id = ?""",
                        (
                            nemsis_json,
                            patient_name,
                            patient.patient_address,
                            patient.patient_age,
                            patient.patient_gender,
                            1 if core_complete else 0,
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

                    # Send core_info_complete message once when all 4 fields are present
                    if core_complete and not core_info_sent:
                        core_info_sent = True
                        logger.info("Core info complete for %s - notifying client", patient_name)
                        await _safe_send({"type": "core_info_complete"})
                        await event_bus.publish(case_id, {"type": "core_info_complete"})
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
        last_extracted_word_count = len(accumulated_transcript.split()) if accumulated_transcript else 0
        try:
            current_nemsis = NEMSISRecord.model_validate_json(existing["nemsis_data"])
        except Exception:
            logger.warning("Failed to parse NEMSIS data for case %s", case_id)
            current_nemsis = NEMSISRecord()

    # Start transcription service
    stt = TranscriptionService(on_partial=on_partial, on_committed=on_committed)
    await stt.start()

    # Start the interval-based extraction loop
    extraction_task = asyncio.create_task(_extraction_loop())

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
        # Stop the extraction loop
        stop_extraction.set()
        if extraction_task:
            extraction_task.cancel()
            try:
                await extraction_task
            except asyncio.CancelledError:
                pass

        await stt.stop()
        
        # Run one final extraction to capture any remaining text
        if ANTHROPIC_API_KEY and len(accumulated_transcript) > last_extracted_length:
            logger.info("Running final NEMSIS extraction before closing")
            try:
                async with extraction_lock:
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
                    core_complete = is_core_info_complete(current_nemsis)
                    
                    await db.execute(
                        """UPDATE cases SET
                            nemsis_data = ?, patient_name = ?, patient_address = ?,
                            patient_age = ?, patient_gender = ?, core_info_complete = ?, updated_at = ?
                        WHERE id = ?""",
                        (
                            nemsis_json,
                            patient_name,
                            patient.patient_address,
                            patient.patient_age,
                            patient.patient_gender,
                            1 if core_complete else 0,
                            now,
                            case_id,
                        ),
                    )
            except Exception as e:
                logger.error("Final NEMSIS extraction error: %s", e)
        
        # Mark case as completed if it was active
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "UPDATE cases SET status = 'completed', updated_at = ?"
            " WHERE id = ? AND status = 'active'",
            (now, case_id),
        )
        await db.commit()
