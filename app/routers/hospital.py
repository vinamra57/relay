import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from app.database import ensure_demo_cases, get_db
from app.models.clinical import AskRequest, AskResponse, ClinicalInsights
from app.models.medical_history import MedicalHistoryReport
from app.models.summary import CaseSummary, HospitalSummary
from app.services.clinical_insights import get_cached_insights
from app.services.event_bus import event_bus
from app.services.medical_db import build_medical_history_report
from app.services.qa import answer_question
from app.services.summary import generate_summary, get_summary_for_hospital
from app.services.transcription import TranscriptionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hospital", tags=["hospital"])


@router.get("/summary/{case_id}", response_model=HospitalSummary)
async def get_hospital_summary(case_id: str):
    """Get hospital-facing preparation summary for an incoming EMS patient.

    Returns structured sections so the receiving team can prepare
    resources, staff, and equipment before the patient arrives.
    """
    try:
        return await get_summary_for_hospital(case_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Case not found") from None


@router.get("/case-summary/{case_id}", response_model=CaseSummary)
async def get_case_summary(
    case_id: str,
    urgency: str = Query("standard", pattern="^(critical|standard|handoff)$"),
):
    """Get a clinical case summary for paramedic/dispatch view.

    Urgency levels:
    - critical: immediate actionable summary
    - standard: comprehensive overview
    - handoff: hospital-ready transfer summary
    """
    try:
        return await generate_summary(case_id, urgency=urgency)
    except ValueError:
        raise HTTPException(status_code=404, detail="Case not found") from None


@router.get("/medical-history/{case_id}", response_model=MedicalHistoryReport)
async def get_medical_history(case_id: str):
    """Get patient medical history from FHIR/HIE databases.

    Queries connected health information exchanges for the patient's
    medical history including conditions, allergies, medications,
    immunizations, and past procedures.

    Requires core patient info (name, age, gender) to be available.
    """
    db = await get_db()
    case = await db.fetch_one(
        "SELECT patient_name, patient_age, patient_gender, nemsis_data FROM cases WHERE id = ?",
        (case_id,),
    )
    if not case:
        raise HTTPException(status_code=404, detail="Case not found") from None

    patient_name = case["patient_name"] or "Unknown"
    patient_age = case["patient_age"] or "Unknown"
    patient_gender = case["patient_gender"] or "Unknown"

    # Try to extract DOB from NEMSIS data
    patient_dob = None
    try:
        nemsis = json.loads(case["nemsis_data"] or "{}")
        patient_dob = nemsis.get("patient", {}).get("patient_date_of_birth")
    except json.JSONDecodeError:
        pass

    return await build_medical_history_report(
        patient_name=patient_name,
        patient_age=patient_age,
        patient_gender=patient_gender,
        patient_dob=patient_dob,
    )


@router.get("/clinical-insights/{case_id}", response_model=ClinicalInsights)
async def get_clinical_insights(case_id: str):
    """Get clinical insights for the hospital dashboard."""
    try:
        return await get_cached_insights(case_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Case not found") from None


@router.post("/ask", response_model=AskResponse)
async def ask_question(payload: AskRequest):
    """Answer clinician questions about a case."""
    try:
        return await answer_question(payload.case_id, payload.question)
    except ValueError:
        raise HTTPException(status_code=404, detail="Case not found") from None


@router.get("/active-cases")
async def get_active_cases():
    """Get all active cases with their current NEMSIS data for the dashboard."""
    db = await get_db()
    await ensure_demo_cases(db)
    cases = await db.fetch_all(
        "SELECT id, created_at, status, patient_name, patient_age, patient_gender, "
        "nemsis_data, core_info_complete, gp_response, medical_db_response "
        "FROM cases WHERE status = 'active' ORDER BY created_at DESC"
    )
    result = []
    has_real_case = any(row["id"] and not row["id"].startswith("demo-") for row in cases)
    for row in cases:
        if not has_real_case and row["id"].startswith("demo-"):
            continue
        nemsis: dict = {}
        try:
            nemsis = json.loads(row["nemsis_data"] or "{}")
        except json.JSONDecodeError:
            pass
        result.append({
            "id": row["id"],
            "created_at": row["created_at"],
            "patient_name": row["patient_name"],
            "patient_age": row["patient_age"],
            "patient_gender": row["patient_gender"],
            "core_info_complete": bool(row["core_info_complete"]),
            "nemsis": nemsis,
        })
    return result


@router.websocket("/ws/hospital")
async def hospital_dashboard_ws(websocket: WebSocket):
    """WebSocket for real-time hospital dashboard updates.

    Hospital staff connects here to receive live updates about all active cases.
    Events include: nemsis_update, medical_db_complete, gp_call_complete.
    """
    await websocket.accept()
    queue = event_bus.subscribe_all()
    logger.info("Hospital dashboard client connected")

    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=10.0)
            except asyncio.TimeoutError:
                event = {"type": "ping"}

            try:
                await websocket.send_json(event)
            except Exception:
                logger.debug("Failed to send event to hospital client")
                break
    except WebSocketDisconnect:
        logger.info("Hospital dashboard client disconnected")
    except asyncio.CancelledError:
        pass
    finally:
        event_bus.unsubscribe_all(queue)


@router.websocket("/ws/ask/{case_id}")
async def hospital_voice_qa_ws(websocket: WebSocket, case_id: str):
    """WebSocket for voice Q/A using ElevenLabs Scribe realtime."""
    await websocket.accept()
    db = await get_db()
    case = await db.fetch_one("SELECT id FROM cases WHERE id = ?", (case_id,))
    if not case:
        await websocket.send_json({"type": "error", "message": "Case not found"})
        await websocket.close()
        return

    accumulated = ""
    last_partial = ""

    async def on_partial(text: str):
        nonlocal last_partial
        last_partial = text
        await websocket.send_json({"type": "question_partial", "text": text})

    async def on_committed(text: str):
        nonlocal accumulated
        accumulated = f"{accumulated} {text}".strip() if accumulated else text
        await websocket.send_json({"type": "question_committed", "text": text})

    stt = TranscriptionService(
        on_partial=on_partial,
        on_committed=on_committed,
        dummy_segments=[
            "What medications were given en route",
            "Any known allergies or contraindications",
        ],
    )
    await stt.start()

    try:
        while True:
            msg = await websocket.receive_json()
            msg_type = msg.get("type")
            if msg_type == "audio_chunk":
                await stt.send_audio(msg.get("data", ""))
            elif msg_type == "text":
                accumulated = msg.get("text", "")
                break
            elif msg_type == "end":
                break
    except WebSocketDisconnect:
        pass
    finally:
        await stt.stop()

    question = accumulated or last_partial
    if not question:
        await websocket.send_json({"type": "answer", "answer": AskResponse(answer="No question captured.").model_dump()})
        await websocket.close()
        return

    answer = await answer_question(case_id, question)
    await websocket.send_json({
        "type": "answer",
        "question": question,
        "answer": answer.model_dump(),
    })
    await websocket.close()
