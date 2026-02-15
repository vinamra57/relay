import asyncio
import json
import logging
# import random  # unnecessary: only used by dummy vitals
import re
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import GP_DOCUMENT_DELAY_SECONDS
from app.database import get_db
from app.models.nemsis import NEMSISRecord
from app.services.core_info_checker import is_core_info_complete, is_gp_call_ready, trigger_gp_call, trigger_medical_db
from app.gp_pdf_registry import load_gp_record_for_patient
from app.services.nemsis_extractor import extract_nemsis
from app.services.transcription import TranscriptionService
# from app.services.vitals_dataset import VitalsSequence, load_demo_vitals

logger = logging.getLogger(__name__)
router = APIRouter()

# Word count threshold - trigger extraction after this many new words
WORD_COUNT_THRESHOLD = 20
# Max interval between extractions (fallback if not enough words)
MAX_EXTRACTION_INTERVAL = 2.0


@router.websocket("/ws/stream/{case_id}")
async def stream_endpoint(websocket: WebSocket, case_id: str):
    """WebSocket endpoint for streaming audio from wearable mic."""
    await websocket.accept()
    db = await get_db()

    # Verify case exists
    case = await db.fetch_one("SELECT id FROM cases WHERE id = ?", (case_id,))
    if not case:
        await websocket.send_json(
            {"type": "error", "message": f"Case {case_id} not found"}
        )
        await websocket.close()
        return

    # State for this session (minimal: voice→text, text→NEMSIS only)
    accumulated_transcript = ""
    current_partial = ""
    current_nemsis = NEMSISRecord()
    core_triggered = False
    gp_call_triggered = False
    extraction_lock = asyncio.Lock()
    last_extracted_word_count = 0
    extraction_task: asyncio.Task | None = None
    stop_extraction = asyncio.Event()
    extract_now = asyncio.Event()
    end_call_received = False

    # dummy_vitals_task: asyncio.Task | None = None
    # dummy_running = True
    # vitals_sequence = VitalsSequence(load_demo_vitals())
    pending_committed = ""
    pending_sentence_count = 0
    sentence_end_re = re.compile(r"[.!?]")
    sentence_end_at_end_re = re.compile(r"[.!?](\"|'|”)?\\s*$")
    gp_name_re = re.compile(
        r"(?:patient'?s\\s+)?(?:gp|primary care(?: doctor)?|doctor)\\s+(?:is\\s+)?(?:(Dr\\.?|Doctor)\\s+)?([A-Z][a-z]+(?:\\s+[A-Z][a-z]+)*)",
        re.IGNORECASE,
    )
    gp_practice_re = re.compile(
        r"(?:gp|primary care(?: doctor)?|doctor).*?\\bat\\s+([^\\.]+)",
        re.IGNORECASE,
    )

    async def _safe_send(data: dict) -> None:
        try:
            await websocket.send_json(data)
        except Exception:
            logger.debug("WebSocket send failed (client may have disconnected)")

    # Unnecessary for minimal flow: GP data status / event bus
    # async def _publish_gp_data_status(status: str, message: str) -> None:
    #     payload = {"type": "gp_data_status", "status": status, "message": message}
    #     await _safe_send(payload)
    #     await event_bus.publish(case_id, payload)

    async def _persist_and_emit_nemsis() -> None:
        nemsis_json = current_nemsis.model_dump_json()
        now = datetime.now(timezone.utc).isoformat()
        patient = current_nemsis.patient
        patient_name = (
            " ".join(filter(None, [patient.patient_name_first, patient.patient_name_last]))
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
        # if not SIMPLE_STREAM:
        #     await event_bus.publish(case_id, {"type": "nemsis_update", "nemsis": nemsis_dict, "patient_name": patient_name})

    def _count_sentence_endings(text: str) -> int:
        return len(sentence_end_re.findall(text))

    def _ends_with_sentence(text: str) -> bool:
        return bool(sentence_end_at_end_re.search(text.strip()))

    async def _flush_committed(text: str) -> None:
        nonlocal accumulated_transcript
        if not text:
            return

        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO transcripts (case_id, segment_text, timestamp, segment_type)"
            " VALUES (?, ?, ?, ?)",
            (case_id, text, now, "committed"),
        )

        accumulated_transcript += (" " + text) if accumulated_transcript else text
        await db.execute(
            "UPDATE cases SET full_transcript = ?, updated_at = ? WHERE id = ?",
            (accumulated_transcript, now, case_id),
        )
        await db.commit()

        await _safe_send(
            {
                "type": "transcript_committed",
                "text": text,
                "full_transcript": accumulated_transcript,
            }
        )
        extract_now.set()

    def _infer_gp_details(text: str) -> None:
        if not text:
            return
        patient = current_nemsis.patient
        if not patient.gp_name:
            match = gp_name_re.search(text)
            if match:
                title = match.group(1) or ""
                name = match.group(2) or ""
                combined = " ".join(part for part in [title, name] if part).strip()
                if combined:
                    patient.gp_name = combined
        if not patient.gp_practice_name:
            match = gp_practice_re.search(text)
            if match:
                practice = match.group(1).strip()
                if practice:
                    patient.gp_practice_name = practice

    # Unnecessary for minimal flow: GP call scheduling and document delivery
    # async def _schedule_gp_pending() -> None:
    #     await asyncio.sleep(GP_CALL_PENDING_SECONDS)
    #     if not gp_call_completed:
    #         await _publish_gp_data_status("pending", "GP call in progress")

    # async def _deliver_gp_document() -> None:
    #     nonlocal gp_doc_received
    #     await asyncio.sleep(GP_DOCUMENT_DELAY_SECONDS)
    #     ...
    #     asyncio.create_task(_update_insights_from_gp_doc())

    async def on_partial(text: str):
        nonlocal current_partial
        current_partial = text
        await _safe_send({"type": "transcript_partial", "text": text})

        full_text = accumulated_transcript
        if pending_committed:
            full_text = (full_text + " " + pending_committed).strip() if full_text else pending_committed
        full_text = (full_text + " " + text).strip() if full_text else text
        current_word_count = len(full_text.split())
        if current_word_count - last_extracted_word_count >= WORD_COUNT_THRESHOLD:
            extract_now.set()

    async def on_committed(text: str):
        nonlocal current_partial, pending_committed, pending_sentence_count

        current_partial = ""
        if text:
            pending_committed = f"{pending_committed} {text}".strip() if pending_committed else text
            pending_sentence_count += _count_sentence_endings(text)
            # Trigger extraction so core_info_complete / medical DB run while client still connected
            extract_now.set()

        should_flush = False
        if pending_sentence_count >= 2:
            should_flush = True
        elif pending_committed and _ends_with_sentence(pending_committed):
            should_flush = True

        if should_flush:
            await _flush_committed(pending_committed)
            pending_committed = ""
            pending_sentence_count = 0

    async def _extraction_loop():
        nonlocal current_nemsis, last_extracted_word_count, core_triggered, gp_call_triggered

        while not stop_extraction.is_set():
            try:
                _done, pending = await asyncio.wait(
                    [
                        asyncio.create_task(extract_now.wait()),
                        asyncio.create_task(stop_extraction.wait()),
                    ],
                    timeout=MAX_EXTRACTION_INTERVAL,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            except TimeoutError:
                pass

            if stop_extraction.is_set():
                break

            extract_now.clear()

            full_text = accumulated_transcript
            if pending_committed:
                full_text = (full_text + " " + pending_committed).strip() if full_text else pending_committed
            if current_partial:
                full_text = (full_text + " " + current_partial).strip() if full_text else current_partial

            current_word_count = len(full_text.split()) if full_text else 0
            if current_word_count <= last_extracted_word_count:
                continue

            async with extraction_lock:
                try:
                    current_nemsis = await extract_nemsis(full_text, current_nemsis)
                    _infer_gp_details(full_text)  # still part of text→NEMSIS (fill gp_name from transcript)
                    last_extracted_word_count = current_word_count
                    await _persist_and_emit_nemsis()

                    # When core info (name, address, age, gender) is complete, trigger Synthea/medical DB lookup once
                    if is_core_info_complete(current_nemsis) and not core_triggered:
                        core_triggered = True
                        now_utc = datetime.now(timezone.utc).isoformat()
                        await db.execute(
                            "UPDATE cases SET core_info_complete = 1, updated_at = ? WHERE id = ?",
                            (now_utc, case_id),
                        )
                        await db.commit()
                        await _safe_send({"type": "core_info_complete"})

                        nemsis_snapshot = current_nemsis.model_copy(deep=True)

                        async def _run_medical_db_and_emit(snapshot: NEMSISRecord) -> None:
                            try:
                                report = await trigger_medical_db(snapshot)
                                t = datetime.now(timezone.utc).isoformat()
                                await db.execute(
                                    "UPDATE cases SET medical_db_response = ?, updated_at = ? WHERE id = ?",
                                    (report, t, case_id),
                                )
                                await db.commit()
                                await _safe_send({"type": "medical_db_complete", "medical_db_response": report})
                            except Exception as exc:
                                logger.error("Medical DB (Synthea) lookup error: %s", exc)

                        asyncio.create_task(_run_medical_db_and_emit(nemsis_snapshot))

                    # When core + GP name + GP phone are ready, trigger real GP call (to NEMSIS gp_phone)
                    if is_gp_call_ready(current_nemsis) and not gp_call_triggered:
                        gp_call_triggered = True
                        nemsis_for_gp = current_nemsis.model_copy(deep=True)

                        async def _run_gp_call_and_deliver_doc() -> None:
                            try:
                                await _safe_send({"type": "gp_call_triggered", "message": "Initiating GP call for patient history..."})
                                gp_response = await trigger_gp_call(nemsis_for_gp, case_id)
                                await _safe_send({"type": "gp_call_complete", "gp_response": gp_response})
                                # After delay, simulate GP sending records: only if name matches a PDF do we "receive" and record in DB
                                await asyncio.sleep(GP_DOCUMENT_DELAY_SECONDS)
                                patient_name = " ".join(filter(None, [
                                    nemsis_for_gp.patient.patient_name_first,
                                    nemsis_for_gp.patient.patient_name_last,
                                ])) or "Unknown"
                                _raw, doc_summary = load_gp_record_for_patient(patient_name)
                                if doc_summary and "No data found" not in doc_summary:
                                    gp_response_text = doc_summary
                                else:
                                    gp_response_text = "Waiting to receive medical records from GP"
                                now_utc = datetime.now(timezone.utc).isoformat()
                                await db.execute(
                                    "UPDATE cases SET gp_response = ?, updated_at = ? WHERE id = ?",
                                    (gp_response_text, now_utc, case_id),
                                )
                                await db.commit()
                                await _safe_send({
                                    "type": "gp_data_received",
                                    "gp_document_summary": gp_response_text,
                                    "gp_response": gp_response_text,
                                })
                            except Exception as exc:
                                logger.error("GP call or document delivery error: %s", exc)

                        asyncio.create_task(_run_gp_call_and_deliver_doc())

                except Exception as exc:
                    logger.error("NEMSIS extraction error: %s", exc)

    # Unnecessary for minimal flow: synthetic vitals loop
    # async def _dummy_vitals_loop() -> None:
    #     ... (entire function commented)

    # Load existing case data
    existing = await db.fetch_one(
        "SELECT full_transcript, nemsis_data, core_info_complete, gp_call_status FROM cases WHERE id = ?",
        (case_id,),
    )
    if existing:
        accumulated_transcript = existing["full_transcript"] or ""
        last_extracted_word_count = len(accumulated_transcript.split()) if accumulated_transcript else 0
        try:
            current_nemsis = NEMSISRecord.model_validate_json(existing["nemsis_data"])
        except Exception:
            logger.warning("Failed to parse NEMSIS data for case %s", case_id)
            current_nemsis = NEMSISRecord()
        core_triggered = bool(existing["core_info_complete"])
        gp_call_triggered = bool(existing["gp_call_status"])

    stt = TranscriptionService(on_partial=on_partial, on_committed=on_committed)
    await stt.start()

    extraction_task = asyncio.create_task(_extraction_loop())
    # if not SIMPLE_STREAM and DUMMY_MODE:
    #     dummy_vitals_task = asyncio.create_task(_dummy_vitals_loop())

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)

            if data.get("type") == "audio_chunk":
                await stt.send_audio(data.get("data", ""))
            elif data.get("type") == "end_call":
                end_call_received = True
                break
    except WebSocketDisconnect:
        logger.info("Client disconnected from case %s", case_id)
    except Exception as exc:
        logger.error("WebSocket error for case %s: %s", case_id, exc)
    finally:
        stop_extraction.set()
        if extraction_task:
            extraction_task.cancel()
            try:
                await extraction_task
            except asyncio.CancelledError:
                pass

        # dummy_running = False
        # if dummy_vitals_task:
        #     dummy_vitals_task.cancel()
        #     try:
        #         await dummy_vitals_task
        #     except asyncio.CancelledError:
        #         pass

        await stt.stop()

        if current_partial:
            pending_committed = f"{pending_committed} {current_partial}".strip() if pending_committed else current_partial
        if pending_committed:
            await _flush_committed(pending_committed)
            pending_committed = ""
            pending_sentence_count = 0

        if len(accumulated_transcript.split()) > last_extracted_word_count:
            logger.info("Running final NEMSIS extraction before closing")
            try:
                async with extraction_lock:
                    current_nemsis = await extract_nemsis(
                        accumulated_transcript, current_nemsis
                    )
                    await _persist_and_emit_nemsis()
                    if is_core_info_complete(current_nemsis) and not core_triggered:
                        core_triggered = True
                        now_utc = datetime.now(timezone.utc).isoformat()
                        await db.execute(
                            "UPDATE cases SET core_info_complete = 1, updated_at = ? WHERE id = ?",
                            (now_utc, case_id),
                        )
                        await db.commit()
                        await _safe_send({"type": "core_info_complete"})
                        snapshot = current_nemsis.model_copy(deep=True)

                        async def _run_medical_db_and_emit_final(snapshot: NEMSISRecord) -> None:
                            try:
                                report = await trigger_medical_db(snapshot)
                                t = datetime.now(timezone.utc).isoformat()
                                await db.execute(
                                    "UPDATE cases SET medical_db_response = ?, updated_at = ? WHERE id = ?",
                                    (report, t, case_id),
                                )
                                await db.commit()
                                await _safe_send({"type": "medical_db_complete", "medical_db_response": report})
                            except Exception as exc:
                                logger.error("Medical DB (Synthea) lookup error: %s", exc)

                        asyncio.create_task(_run_medical_db_and_emit_final(snapshot))

                    if is_gp_call_ready(current_nemsis) and not gp_call_triggered:
                        gp_call_triggered = True
                        snapshot_gp = current_nemsis.model_copy(deep=True)

                        async def _run_gp_call_final() -> None:
                            try:
                                await _safe_send({"type": "gp_call_triggered", "message": "Initiating GP call for patient history..."})
                                gp_response = await trigger_gp_call(snapshot_gp, case_id)
                                await _safe_send({"type": "gp_call_complete", "gp_response": gp_response})
                                await asyncio.sleep(GP_DOCUMENT_DELAY_SECONDS)
                                patient_name = " ".join(filter(None, [
                                    snapshot_gp.patient.patient_name_first,
                                    snapshot_gp.patient.patient_name_last,
                                ])) or "Unknown"
                                _raw, doc_summary = load_gp_record_for_patient(patient_name)
                                if doc_summary and "No data found" not in doc_summary:
                                    gp_response_text = doc_summary
                                else:
                                    gp_response_text = "Waiting to receive medical records from GP"
                                now_utc = datetime.now(timezone.utc).isoformat()
                                await db.execute(
                                    "UPDATE cases SET gp_response = ?, updated_at = ? WHERE id = ?",
                                    (gp_response_text, now_utc, case_id),
                                )
                                await db.commit()
                                await _safe_send({
                                    "type": "gp_data_received",
                                    "gp_document_summary": gp_response_text,
                                    "gp_response": gp_response_text,
                                })
                            except Exception as exc:
                                logger.error("GP call or document delivery error: %s", exc)

                        asyncio.create_task(_run_gp_call_final())
            except Exception as exc:
                logger.error("Final NEMSIS extraction error: %s", exc)

        now = datetime.now(timezone.utc).isoformat()
        # if not SIMPLE_STREAM and end_call_received:
        #     await event_bus.publish(case_id, {"type": "arrival_status", "status": "arrived"})
        await db.execute(
            "UPDATE cases SET status = 'completed', updated_at = ?"
            " WHERE id = ? AND status = 'active'",
            (now, case_id),
        )
        await db.commit()
