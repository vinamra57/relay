import json
import logging

from app.database import get_db
from app.models.summary import CaseSummary, HospitalSummary
from app.services.llm import get_llm_client

logger = logging.getLogger(__name__)
CASE_SUMMARY_PROMPT = """You are a clinical summarization AI for emergency medical services.

Given the case data below (transcript, NEMSIS-compliant structured data, GP response,
and medical database response), generate a concise case summary for the paramedic/dispatch view.

Rules:
- one_liner: A single sentence (<100 chars) capturing the patient and chief complaint.
- clinical_narrative: 2-4 sentences covering the clinical picture, interventions, and status.
- key_findings: List of 3-6 most important clinical findings (vitals, ECG, exam results).
- actions_taken: List of procedures and medications administered.
- urgency: One of "critical", "high", "moderate", "low" based on clinical picture.

Respond with ONLY a JSON object with these exact keys: one_liner, clinical_narrative, key_findings, actions_taken, urgency.
No markdown, no explanation."""

HOSPITAL_SUMMARY_PROMPT = """You are a hospital preparation AI for incoming EMS patients.

Given the case data below, generate a structured hospital preparation summary so the
receiving team can prepare resources, staff, and equipment before the patient arrives.

Rules:
- patient_demographics: Age, gender, name if available.
- chief_complaint: Primary reason for EMS activation.
- vitals_summary: All recorded vital signs in a readable sentence.
- procedures_performed: List of EMS procedures as a readable string.
- medications_administered: List of medications given as a readable string.
- clinical_impression: Primary and secondary clinical impressions.
- recommended_preparations: Specific preparations the hospital should make (e.g. cath lab, trauma bay).
- patient_history: Known medical history, GP info, database records.
- priority_level: One of "critical", "high", "moderate", "low".
- special_considerations: Allergies, access issues, family contact, or other notes.

Respond with ONLY a JSON object with these exact keys: patient_demographics, chief_complaint, vitals_summary, procedures_performed, medications_administered, clinical_impression, recommended_preparations, patient_history, priority_level, special_considerations.
No markdown, no explanation."""


async def _load_case_data(case_id: str) -> dict:
    """Load all case data from the database for summary generation."""
    db = await get_db()
    case = await db.fetch_one("SELECT * FROM cases WHERE id = ?", (case_id,))
    if not case:
        raise ValueError(f"Case {case_id} not found")

    nemsis_data: dict = {}
    try:
        nemsis_data = json.loads(case["nemsis_data"] or "{}")
    except json.JSONDecodeError:
        logger.warning("Failed to parse NEMSIS data for case %s", case_id)

    return {
        "case_id": case_id,
        "transcript": case["full_transcript"] or "",
        "nemsis": nemsis_data,
        "patient_name": case["patient_name"] or "",
        "patient_age": case["patient_age"] or "",
        "patient_gender": case["patient_gender"] or "",
        "gp_response": case["gp_response"] or "",
        "medical_db_response": case["medical_db_response"] or "",
    }


def _empty_case_summary() -> CaseSummary:
    """Minimal valid case summary when no LLM is available."""
    return CaseSummary(
        one_liner="No summary available.",
        clinical_narrative="",
        key_findings=[],
        actions_taken=[],
        urgency="moderate",
    )


def _empty_hospital_summary() -> HospitalSummary:
    """Minimal valid hospital summary when no LLM is available."""
    return HospitalSummary(
        patient_demographics="",
        chief_complaint="",
        vitals_summary="",
        procedures_performed="",
        medications_administered="",
        clinical_impression="",
        recommended_preparations="",
        patient_history="",
        priority_level="moderate",
        special_considerations="",
    )


async def generate_summary(case_id: str, urgency: str = "standard") -> CaseSummary:
    """Generate a case summary using configured LLM provider."""
    data = await _load_case_data(case_id)
    user_content = (
        f"Urgency context: {urgency}\n\n"
        f"Transcript:\n{data['transcript']}\n\n"
        f"NEMSIS Data:\n{json.dumps(data['nemsis'], indent=2)}\n\n"
        f"GP Response:\n{data['gp_response']}\n\n"
        f"Medical DB Response:\n{data['medical_db_response']}"
    )

    try:
        client = get_llm_client()
        if not client.available():
            return _empty_case_summary()
        return await client.generate_json(
            system=CASE_SUMMARY_PROMPT,
            user=user_content,
            response_model=CaseSummary,
            max_tokens=2048,
        )
    except Exception as e:
        logger.error("Case summary generation failed for %s: %s", case_id, e)
        return _empty_case_summary()


async def get_summary_for_hospital(case_id: str) -> HospitalSummary:
    """Generate a hospital preparation summary using configured LLM provider."""
    data = await _load_case_data(case_id)
    user_content = (
        f"Transcript:\n{data['transcript']}\n\n"
        f"NEMSIS Data:\n{json.dumps(data['nemsis'], indent=2)}\n\n"
        f"GP Response:\n{data['gp_response']}\n\n"
        f"Medical DB Response:\n{data['medical_db_response']}"
    )

    try:
        client = get_llm_client()
        if not client.available():
            return _empty_hospital_summary()
        return await client.generate_json(
            system=HOSPITAL_SUMMARY_PROMPT,
            user=user_content,
            response_model=HospitalSummary,
            max_tokens=2048,
        )
    except Exception as e:
        logger.error("Hospital summary generation failed for %s: %s", case_id, e)
        return _empty_hospital_summary()
