import json
import logging

from openai import AsyncOpenAI

from app.config import DUMMY_MODE, OPENAI_API_KEY
from app.database import get_db
from app.models.summary import CaseSummary, HospitalSummary

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

CASE_SUMMARY_PROMPT = """You are a clinical summarization AI for emergency medical services.

Given the case data below (transcript, NEMSIS-compliant structured data, GP response,
and medical database response), generate a concise case summary for the paramedic/dispatch view.

Rules:
- one_liner: A single sentence (<100 chars) capturing the patient and chief complaint.
- clinical_narrative: 2-4 sentences covering the clinical picture, interventions, and status.
- key_findings: List of 3-6 most important clinical findings (vitals, ECG, exam results).
- actions_taken: List of procedures and medications administered.
- urgency: One of "critical", "high", "moderate", "low" based on clinical picture."""

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
- special_considerations: Allergies, access issues, family contact, or other notes."""


async def _load_case_data(case_id: str) -> dict:
    """Load all case data from the database for summary generation."""
    db = await get_db()
    row = await db.execute("SELECT * FROM cases WHERE id = ?", (case_id,))
    case = await row.fetchone()
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


async def generate_summary(case_id: str, urgency: str = "standard") -> CaseSummary:
    """Generate a case summary using GPT-5.2 structured output or dummy mode."""
    data = await _load_case_data(case_id)

    if DUMMY_MODE or not client:
        return _dummy_case_summary(data)

    user_content = (
        f"Urgency context: {urgency}\n\n"
        f"Transcript:\n{data['transcript']}\n\n"
        f"NEMSIS Data:\n{json.dumps(data['nemsis'], indent=2)}\n\n"
        f"GP Response:\n{data['gp_response']}\n\n"
        f"Medical DB Response:\n{data['medical_db_response']}"
    )

    try:
        response = await client.beta.chat.completions.parse(
            model="gpt-5.2",
            messages=[
                {"role": "system", "content": CASE_SUMMARY_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format=CaseSummary,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            logger.error("GPT-5.2 returned no parsed case summary for case %s", case_id)
            return _dummy_case_summary(data)
        return parsed
    except Exception as e:
        logger.error("Case summary generation failed for %s: %s", case_id, e)
        return _dummy_case_summary(data)


async def get_summary_for_hospital(case_id: str) -> HospitalSummary:
    """Generate a hospital preparation summary using GPT-5.2 or dummy mode."""
    data = await _load_case_data(case_id)

    if DUMMY_MODE or not client:
        return _dummy_hospital_summary(data)

    user_content = (
        f"Transcript:\n{data['transcript']}\n\n"
        f"NEMSIS Data:\n{json.dumps(data['nemsis'], indent=2)}\n\n"
        f"GP Response:\n{data['gp_response']}\n\n"
        f"Medical DB Response:\n{data['medical_db_response']}"
    )

    try:
        response = await client.beta.chat.completions.parse(
            model="gpt-5.2",
            messages=[
                {"role": "system", "content": HOSPITAL_SUMMARY_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format=HospitalSummary,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            logger.error("GPT-5.2 returned no parsed hospital summary for case %s", case_id)
            return _dummy_hospital_summary(data)
        return parsed
    except Exception as e:
        logger.error("Hospital summary generation failed for %s: %s", case_id, e)
        return _dummy_hospital_summary(data)


def _dummy_case_summary(data: dict) -> CaseSummary:
    """Build a deterministic case summary from NEMSIS data for dummy/test mode."""
    nemsis = data.get("nemsis", {})
    patient = nemsis.get("patient", {})
    vitals = nemsis.get("vitals", {})
    situation = nemsis.get("situation", {})
    procedures = nemsis.get("procedures", {})
    medications = nemsis.get("medications", {})

    # Build name
    first = patient.get("patient_name_first") or ""
    last = patient.get("patient_name_last") or ""
    name = f"{first} {last}".strip() or "Unknown patient"

    age = patient.get("patient_age") or "unknown age"
    gender = patient.get("patient_gender") or "unknown gender"
    complaint = situation.get("chief_complaint") or "unspecified complaint"
    impression = situation.get("primary_impression") or ""

    one_liner = f"{name}, {age}y {gender}, {complaint}"
    if len(one_liner) > 100:
        one_liner = one_liner[:97] + "..."

    # Narrative
    parts = [f"{name} is a {age} year old {gender} presenting with {complaint}."]
    if impression:
        parts.append(f"Primary impression: {impression}.")
    proc_list = procedures.get("procedures") or []
    med_list = medications.get("medications") or []
    if proc_list or med_list:
        parts.append(
            f"Interventions include {len(proc_list)} procedure(s) and {len(med_list)} medication(s)."
        )

    # Key findings
    findings: list[str] = []
    if vitals.get("systolic_bp") and vitals.get("diastolic_bp"):
        findings.append(f"BP {vitals['systolic_bp']}/{vitals['diastolic_bp']}")
    if vitals.get("heart_rate"):
        findings.append(f"HR {vitals['heart_rate']}")
    if vitals.get("respiratory_rate"):
        findings.append(f"RR {vitals['respiratory_rate']}")
    if vitals.get("spo2"):
        findings.append(f"SpO2 {vitals['spo2']}%")
    if vitals.get("gcs_total"):
        findings.append(f"GCS {vitals['gcs_total']}")
    if impression:
        findings.append(impression)
    if not findings:
        findings.append("No vitals recorded")

    # Urgency
    urgency = "moderate"
    if impression and any(
        k in impression.lower() for k in ["stemi", "stroke", "cardiac arrest", "trauma"]
    ):
        urgency = "critical"
    elif vitals.get("spo2") and vitals["spo2"] < 90:
        urgency = "critical"
    elif vitals.get("heart_rate") and vitals["heart_rate"] > 120:
        urgency = "high"

    return CaseSummary(
        one_liner=one_liner,
        clinical_narrative=" ".join(parts),
        key_findings=findings,
        actions_taken=proc_list + med_list,
        urgency=urgency,
    )


def _dummy_hospital_summary(data: dict) -> HospitalSummary:
    """Build a deterministic hospital summary from NEMSIS data for dummy/test mode."""
    nemsis = data.get("nemsis", {})
    patient = nemsis.get("patient", {})
    vitals = nemsis.get("vitals", {})
    situation = nemsis.get("situation", {})
    procedures = nemsis.get("procedures", {})
    medications = nemsis.get("medications", {})

    first = patient.get("patient_name_first") or ""
    last = patient.get("patient_name_last") or ""
    name = f"{first} {last}".strip() or "Unknown"
    age = patient.get("patient_age") or "unknown"
    gender = patient.get("patient_gender") or "unknown"

    # Vitals string
    vitals_parts: list[str] = []
    if vitals.get("systolic_bp") and vitals.get("diastolic_bp"):
        vitals_parts.append(f"BP {vitals['systolic_bp']}/{vitals['diastolic_bp']}")
    if vitals.get("heart_rate"):
        vitals_parts.append(f"HR {vitals['heart_rate']}")
    if vitals.get("respiratory_rate"):
        vitals_parts.append(f"RR {vitals['respiratory_rate']}")
    if vitals.get("spo2"):
        vitals_parts.append(f"SpO2 {vitals['spo2']}%")
    if vitals.get("blood_glucose"):
        vitals_parts.append(f"Glucose {vitals['blood_glucose']}")
    if vitals.get("gcs_total"):
        vitals_parts.append(f"GCS {vitals['gcs_total']}")
    vitals_str = ", ".join(vitals_parts) if vitals_parts else "No vitals recorded"

    proc_list = procedures.get("procedures") or []
    med_list = medications.get("medications") or []
    impression = situation.get("primary_impression") or "Not yet determined"
    secondary = situation.get("secondary_impression") or ""
    clinical_str = impression
    if secondary:
        clinical_str += f"; {secondary}"

    # Priority
    priority = "moderate"
    if any(k in impression.lower() for k in ["stemi", "stroke", "cardiac arrest", "trauma"]):
        priority = "critical"
    elif vitals.get("spo2") and vitals["spo2"] < 90:
        priority = "critical"
    elif vitals.get("heart_rate") and vitals["heart_rate"] > 120:
        priority = "high"

    # Recommended preparations
    preps: list[str] = []
    if "stemi" in impression.lower():
        preps.append("Activate cardiac catheterization lab")
        preps.append("Cardiology team standby")
    if "stroke" in impression.lower():
        preps.append("CT scanner standby")
        preps.append("Neurology team standby")
    if "trauma" in impression.lower():
        preps.append("Trauma bay preparation")
    if not preps:
        preps.append("Standard ED preparation")

    gp = data.get("gp_response") or "No GP data available"
    db_resp = data.get("medical_db_response") or "No database records"
    history = f"GP: {gp} | Records: {db_resp}"

    return HospitalSummary(
        patient_demographics=f"{name}, {age} year old {gender}",
        chief_complaint=situation.get("chief_complaint") or "Not specified",
        vitals_summary=vitals_str,
        procedures_performed=", ".join(proc_list) if proc_list else "None recorded",
        medications_administered=", ".join(med_list) if med_list else "None administered",
        clinical_impression=clinical_str,
        recommended_preparations="; ".join(preps),
        patient_history=history,
        priority_level=priority,
        special_considerations="None noted",
    )
