import logging

from fastapi import APIRouter, HTTPException, Query

from app.models.summary import CaseSummary, HospitalSummary
from app.services.summary import generate_summary, get_summary_for_hospital

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
