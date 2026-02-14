from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/hospital", tags=["hospital"])


@router.get("/summary/{case_id}")
async def get_hospital_summary(case_id: str):
    """Stub: Get hospital-facing summary for a case.

    This endpoint will be populated later with an implementation that:
    - Pulls all case data (transcript, NEMSIS, GP response, medical DB response)
    - Generates an urgency-appropriate summary
    - Returns structured sections for hospital preparation

    For now, returns a placeholder indicating the interface is ready.
    """
    return {
        "case_id": case_id,
        "status": "interface_ready",
        "message": "Hospital summary interface is ready. Implementation pending.",
        "expected_sections": [
            "patient_demographics",
            "chief_complaint",
            "vitals_summary",
            "procedures_performed",
            "medications_administered",
            "eta",
            "recommended_preparations",
            "patient_history",
        ],
    }
