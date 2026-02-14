import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.database import get_db
from app.models.case import CaseCreate, CaseResponse, CaseListItem, CaseStatusUpdate
from app.models.nemsis import NEMSISRecord
from app.models.transcript import TranscriptSegment, TranscriptResponse

router = APIRouter(prefix="/api/cases", tags=["cases"])


@router.post("", response_model=CaseResponse)
async def create_case(body: CaseCreate):
    """Create a new emergency case."""
    db = await get_db()
    case_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    nemsis = NEMSISRecord()

    await db.execute(
        "INSERT INTO cases (id, created_at, status, full_transcript, nemsis_data, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (case_id, now, "active", "", nemsis.model_dump_json(), now),
    )
    await db.commit()

    return CaseResponse(
        id=case_id,
        created_at=now,
        status="active",
        full_transcript="",
        nemsis_data=nemsis,
        core_info_complete=False,
        updated_at=now,
    )


@router.get("", response_model=list[CaseListItem])
async def list_cases():
    """List all cases."""
    db = await get_db()
    rows = await db.execute(
        "SELECT id, created_at, status, patient_name, core_info_complete, nemsis_data FROM cases ORDER BY created_at DESC"
    )
    cases = await rows.fetchall()
    result = []
    for row in cases:
        chief = None
        try:
            nemsis = json.loads(row["nemsis_data"])
            chief = nemsis.get("situation", {}).get("chief_complaint")
        except Exception:
            pass
        result.append(CaseListItem(
            id=row["id"],
            created_at=row["created_at"],
            status=row["status"],
            patient_name=row["patient_name"],
            core_info_complete=bool(row["core_info_complete"]),
            chief_complaint=chief,
        ))
    return result


@router.get("/{case_id}", response_model=CaseResponse)
async def get_case(case_id: str):
    """Get a single case with full details."""
    db = await get_db()
    row = await db.execute("SELECT * FROM cases WHERE id = ?", (case_id,))
    case = await row.fetchone()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    nemsis = NEMSISRecord()
    try:
        nemsis = NEMSISRecord.model_validate_json(case["nemsis_data"])
    except Exception:
        pass

    return CaseResponse(
        id=case["id"],
        created_at=case["created_at"],
        status=case["status"],
        full_transcript=case["full_transcript"] or "",
        nemsis_data=nemsis,
        core_info_complete=bool(case["core_info_complete"]),
        patient_name=case["patient_name"],
        patient_address=case["patient_address"],
        patient_age=case["patient_age"],
        patient_gender=case["patient_gender"],
        gp_response=case["gp_response"],
        medical_db_response=case["medical_db_response"],
        summary=case["summary"],
        updated_at=case["updated_at"],
    )


@router.get("/{case_id}/nemsis")
async def get_case_nemsis(case_id: str):
    """Get just the NEMSIS data for a case."""
    db = await get_db()
    row = await db.execute("SELECT nemsis_data FROM cases WHERE id = ?", (case_id,))
    case = await row.fetchone()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    try:
        return json.loads(case["nemsis_data"])
    except Exception:
        return {}


@router.get("/{case_id}/transcripts", response_model=TranscriptResponse)
async def get_case_transcripts(case_id: str):
    """Get all raw transcript segments for a case."""
    db = await get_db()

    # Verify case exists
    row = await db.execute("SELECT id FROM cases WHERE id = ?", (case_id,))
    if not await row.fetchone():
        raise HTTPException(status_code=404, detail="Case not found")

    rows = await db.execute(
        "SELECT * FROM transcripts WHERE case_id = ? ORDER BY created_at ASC",
        (case_id,),
    )
    segments = await rows.fetchall()

    return TranscriptResponse(
        segments=[
            TranscriptSegment(
                id=s["id"],
                case_id=s["case_id"],
                segment_text=s["segment_text"],
                timestamp=s["timestamp"],
                segment_type=s["segment_type"],
                created_at=s["created_at"],
            )
            for s in segments
        ],
        total=len(segments),
    )


@router.patch("/{case_id}")
async def update_case_status(case_id: str, body: CaseStatusUpdate):
    """Update case status."""
    db = await get_db()
    row = await db.execute("SELECT id FROM cases WHERE id = ?", (case_id,))
    if not await row.fetchone():
        raise HTTPException(status_code=404, detail="Case not found")

    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "UPDATE cases SET status = ?, updated_at = ? WHERE id = ?",
        (body.status, now, case_id),
    )
    await db.commit()
    return {"id": case_id, "status": body.status, "updated_at": now}
