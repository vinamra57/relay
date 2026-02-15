import asyncio
import json
import logging
import random
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import DUMMY_MODE
from app.database import get_db
from app.models.nemsis import NEMSISRecord
from app.services.clinical_insights import update_case_insights
from app.services.core_info_checker import (
    is_core_info_complete,
    is_gp_contact_available,
    trigger_gp_call,
    trigger_medical_db,
)
from app.services.event_bus import event_bus
from app.services.nemsis_extractor import extract_nemsis
from app.services.transcription import TranscriptionService
from app.services.vitals_dataset import VitalsSequence, load_demo_vitals

logger = logging.getLogger(__name__)
router = APIRouter()

# Word count threshold - trigger extraction after this many new words
WORD_COUNT_THRESHOLD = 10
# Max interval between extractions (fallback if not enough words)
MAX_EXTRACTION_INTERVAL = 3


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

    # State for this session
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

    dummy_vitals_task: asyncio.Task | None = None
    dummy_running = True
    vitals_sequence = VitalsSequence(load_demo_vitals())

    async def _safe_send(data: dict) -> None:
        try:
            await websocket.send_json(data)
        except Exception:
            logger.debug("WebSocket send failed (client may have disconnected)")

    async def _persist_and_emit_nemsis() -> None:
        nemsis_json = current_nemsis.model_dump_json()
        now = datetime.now(UTC).isoformat()
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
        await event_bus.publish(case_id, {
            "type": "nemsis_update",
            "nemsis": nemsis_dict,
            "patient_name": patient_name,
        })

    async def on_partial(text: str):
        nonlocal current_partial
        current_partial = text
        await _safe_send({"type": "transcript_partial", "text": text})

        full_text = (accumulated_transcript + " " + text).strip() if accumulated_transcript else text
        current_word_count = len(full_text.split())
        if current_word_count - last_extracted_word_count >= WORD_COUNT_THRESHOLD:
            extract_now.set()

    async def on_committed(text: str):
        nonlocal accumulated_transcript, current_partial

        now = datetime.now(UTC).isoformat()
        current_partial = ""

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

    async def _extraction_loop():
        nonlocal current_nemsis, core_triggered, gp_call_triggered, last_extracted_word_count

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
            if current_partial:
                full_text = (full_text + " " + current_partial).strip() if full_text else current_partial

            current_word_count = len(full_text.split()) if full_text else 0
            if current_word_count <= last_extracted_word_count:
                continue

            async with extraction_lock:
                try:
                    current_nemsis = await extract_nemsis(full_text, current_nemsis)
                    last_extracted_word_count = current_word_count
                    await _persist_and_emit_nemsis()

                    # --- Trigger: Medical DB lookup (core info complete) ---
                    now = datetime.now(UTC).isoformat()
                    if not core_triggered and is_core_info_complete(current_nemsis):
                        core_triggered = True
                        await db.execute(
                            "UPDATE cases SET core_info_complete = 1, updated_at = ?"
                            " WHERE id = ?",
                            (now, case_id),
                        )
                        await db.commit()

                        await _safe_send(
                            {
                                "type": "core_info_complete",
                                "message": "Core patient info collected. "
                                "Triggering medical DB lookup.",
                            }
                        )
                        await event_bus.publish(case_id, {"type": "core_info_complete"})

                        db_response = await trigger_medical_db(current_nemsis)

                        await db.execute(
                            "UPDATE cases SET medical_db_response = ?,"
                            " updated_at = ? WHERE id = ?",
                            (db_response, datetime.now(UTC).isoformat(), case_id),
                        )
                        await db.commit()

                        await _safe_send(
                            {
                                "type": "medical_db_complete",
                                "medical_db_response": db_response,
                            }
                        )
                        await event_bus.publish(case_id, {
                            "type": "medical_db_complete",
                            "medical_db_response": db_response,
                        })

                        async def _update_insights_from_db():
                            try:
                                insights = await update_case_insights(case_id)
                                await event_bus.publish(case_id, {
                                    "type": "clinical_insights",
                                    "insights": insights.model_dump(),
                                })
                            except Exception as exc:
                                logger.warning("Failed to update clinical insights: %s", exc)

                        asyncio.create_task(_update_insights_from_db())  # noqa: RUF006

                    # --- Trigger: GP voice call (core info + GP contact) ---
                    if (
                        not gp_call_triggered
                        and is_core_info_complete(current_nemsis)
                        and is_gp_contact_available(current_nemsis)
                    ):
                        gp_call_triggered = True

                        await _safe_send(
                            {
                                "type": "gp_call_triggered",
                                "message": "GP contact detected. Initiating GP voice call.",
                            }
                        )

                        gp_response = await trigger_gp_call(current_nemsis, case_id)

                        await db.execute(
                            "UPDATE cases SET gp_response = ?,"
                            " updated_at = ? WHERE id = ?",
                            (gp_response, datetime.now(UTC).isoformat(), case_id),
                        )
                        await db.commit()

                        await _safe_send(
                            {
                                "type": "gp_call_complete",
                                "gp_response": gp_response,
                            }
                        )
                        await event_bus.publish(case_id, {
                            "type": "gp_call_complete",
                            "gp_response": gp_response,
                        })

                        async def _update_insights_from_gp():
                            try:
                                insights = await update_case_insights(case_id)
                                await event_bus.publish(case_id, {
                                    "type": "clinical_insights",
                                    "insights": insights.model_dump(),
                                })
                            except Exception as exc:
                                logger.warning("Failed to update clinical insights: %s", exc)

                        asyncio.create_task(_update_insights_from_gp())  # noqa: RUF006

                    if DUMMY_MODE:
                        async def _update_insights_from_nemsis():
                            try:
                                insights = await update_case_insights(case_id)
                                await event_bus.publish(case_id, {
                                    "type": "clinical_insights",
                                    "insights": insights.model_dump(),
                                })
                            except Exception as exc:
                                logger.warning("Failed to update clinical insights: %s", exc)

                        asyncio.create_task(_update_insights_from_nemsis())  # noqa: RUF006

                except Exception as exc:
                    logger.error("NEMSIS extraction error: %s", exc)

    async def _dummy_vitals_loop() -> None:
        nonlocal current_nemsis
        await asyncio.sleep(1.0)
        while dummy_running:
            try:
                async with extraction_lock:
                    vitals = current_nemsis.vitals
                    impression = (current_nemsis.situation.primary_impression or "").lower()

                    dataset_vitals = vitals_sequence.next()

                    if "stemi" in impression:
                        baseline = {"heart_rate": 108, "systolic_bp": 158, "diastolic_bp": 94, "respiratory_rate": 22, "spo2": 94, "blood_glucose": 145.0}
                        ranges = {"heart_rate": (95, 130), "systolic_bp": (140, 185), "diastolic_bp": (85, 110), "respiratory_rate": (18, 26), "spo2": (92, 97)}
                        bias = {"hr": 6, "resp": 1, "spo2": -1}
                    elif "stroke" in impression:
                        baseline = {"heart_rate": 90, "systolic_bp": 176, "diastolic_bp": 98, "respiratory_rate": 18, "spo2": 96, "blood_glucose": 120.0}
                        ranges = {"heart_rate": (70, 105), "systolic_bp": (155, 195), "diastolic_bp": (85, 115), "respiratory_rate": (14, 22), "spo2": (94, 99)}
                        bias = {"hr": 0, "resp": 0, "spo2": 0}
                    elif "trauma" in impression:
                        baseline = {"heart_rate": 128, "systolic_bp": 92, "diastolic_bp": 60, "respiratory_rate": 26, "spo2": 92, "blood_glucose": 110.0}
                        ranges = {"heart_rate": (110, 145), "systolic_bp": (80, 105), "diastolic_bp": (50, 72), "respiratory_rate": (20, 30), "spo2": (88, 95)}
                        bias = {"hr": 12, "resp": 2, "spo2": -2}
                    else:
                        baseline = {"heart_rate": 98, "systolic_bp": 138, "diastolic_bp": 84, "respiratory_rate": 20, "spo2": 95, "blood_glucose": 118.0}
                        ranges = {"heart_rate": (80, 115), "systolic_bp": (120, 155), "diastolic_bp": (70, 95), "respiratory_rate": (16, 24), "spo2": (92, 98)}
                        bias = {"hr": 0, "resp": 0, "spo2": 0}

                    def _adjust(value: int | float | None, key: str, noise: float, alpha: float, _baseline=baseline, _ranges=ranges) -> int:
                        base = _baseline[key]
                        low, high = _ranges[key]
                        if value is None:
                            return int(base)
                        updated = value + (base - value) * alpha + random.gauss(0, noise)
                        updated = max(low, min(high, updated))
                        return round(updated)

                    def _smooth(value: int | float | None, target: float, low: int, high: int, noise: float, alpha: float) -> int:
                        if value is None:
                            return round(target)
                        updated = value + (target - value) * alpha + random.gauss(0, noise)
                        updated = max(low, min(high, updated))
                        return round(updated)

                    if dataset_vitals:
                        hr_target = dataset_vitals["hr"] + bias["hr"]
                        resp_target = dataset_vitals["resp"] + bias["resp"]
                        spo2_target = dataset_vitals["spo2"] + bias["spo2"]

                        vitals.heart_rate = _smooth(vitals.heart_rate, hr_target, *ranges["heart_rate"], noise=0.6, alpha=0.4)
                        vitals.respiratory_rate = _smooth(vitals.respiratory_rate, resp_target, *ranges["respiratory_rate"], noise=0.4, alpha=0.35)
                        vitals.spo2 = _smooth(vitals.spo2, spo2_target, *ranges["spo2"], noise=0.2, alpha=0.45)
                    else:
                        vitals.heart_rate = _adjust(vitals.heart_rate, "heart_rate", 0.8, 0.12)
                        vitals.respiratory_rate = _adjust(vitals.respiratory_rate, "respiratory_rate", 0.4, 0.15)
                        vitals.spo2 = _adjust(vitals.spo2, "spo2", 0.25, 0.18)

                    hr_for_bp = vitals.heart_rate or baseline["heart_rate"]
                    sys_target = baseline["systolic_bp"] + (hr_for_bp - baseline["heart_rate"]) * 0.35
                    dia_target = baseline["diastolic_bp"] + (hr_for_bp - baseline["heart_rate"]) * 0.2
                    vitals.systolic_bp = _smooth(vitals.systolic_bp, sys_target, *ranges["systolic_bp"], noise=1.0, alpha=0.25)
                    vitals.diastolic_bp = _smooth(vitals.diastolic_bp, dia_target, *ranges["diastolic_bp"], noise=0.7, alpha=0.22)
                    vitals.blood_glucose = _smooth(vitals.blood_glucose, baseline["blood_glucose"], 70, 220, noise=0.6, alpha=0.08)
                    vitals.gcs_total = vitals.gcs_total or (13 if "stroke" in impression else 15)

                    await _persist_and_emit_nemsis()
            except Exception as exc:
                logger.debug("Dummy vitals update failed: %s", exc)

            await asyncio.sleep(0.5)

    # Load existing case data
    existing = await db.fetch_one(
        "SELECT full_transcript, nemsis_data, core_info_complete FROM cases WHERE id = ?",
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

    stt = TranscriptionService(on_partial=on_partial, on_committed=on_committed)
    await stt.start()

    extraction_task = asyncio.create_task(_extraction_loop())
    if DUMMY_MODE:
        dummy_vitals_task = asyncio.create_task(_dummy_vitals_loop())

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

        dummy_running = False
        if dummy_vitals_task:
            dummy_vitals_task.cancel()
            try:
                await dummy_vitals_task
            except asyncio.CancelledError:
                pass

        await stt.stop()

        if len(accumulated_transcript.split()) > last_extracted_word_count:
            logger.info("Running final NEMSIS extraction before closing")
            try:
                async with extraction_lock:
                    current_nemsis = await extract_nemsis(
                        accumulated_transcript, current_nemsis
                    )
                    await _persist_and_emit_nemsis()
            except Exception as exc:
                logger.error("Final NEMSIS extraction error: %s", exc)

        now = datetime.now(UTC).isoformat()
        if end_call_received:
            await event_bus.publish(case_id, {"type": "arrival_status", "status": "arrived"})
        await db.execute(
            "UPDATE cases SET status = 'completed', updated_at = ?"
            " WHERE id = ? AND status = 'active'",
            (now, case_id),
        )
        await db.commit()
