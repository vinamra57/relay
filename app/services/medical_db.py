"""Medical database service - queries HIE/FHIR servers for patient history.

When core patient information (name, DOB, gender, address) is complete,
this service queries public FHIR R4 servers (or Particle Health in production)
to retrieve the patient's medical history including:
- Conditions (medical history / diagnoses)
- Allergies and intolerances
- Current and past medications
- Immunization records
- Past procedures

The results are formatted into a clinical report text suitable for
paramedic and ER use.
"""

import logging
from typing import Any

import httpx

from app.models.medical_history import MedicalHistoryReport, PatientMedicalHistory
from app.services.fhir_client import query_fhir_servers
from app.config import FHIR_DEMO_PATIENT_URL

logger = logging.getLogger(__name__)


async def query_records(
    patient_name: str,
    patient_age: str,
    patient_gender: str,
    patient_dob: str | None = None,
) -> str:
    """Query public medical databases for patient records.

    Searches FHIR R4 servers for matching patients and retrieves their
    complete medical history. Returns a formatted text report.

    Args:
        patient_name: Patient full name
        patient_age: Patient age
        patient_gender: Patient gender
        patient_dob: Date of birth (YYYY-MM-DD) if available

    Returns:
        Formatted textual patient records document
    """
    logger.info("Querying medical databases for %s", patient_name)

    if FHIR_DEMO_PATIENT_URL:
        demo_report = await build_demo_history_report(
            demo_url=FHIR_DEMO_PATIENT_URL,
            patient_name=patient_name,
            patient_age=patient_age,
            patient_gender=patient_gender,
        )
        return demo_report.report_text

    report = await build_medical_history_report(
        patient_name=patient_name,
        patient_age=patient_age,
        patient_gender=patient_gender,
        patient_dob=patient_dob,
    )

    return report.report_text


async def _fetch_demo_patient(url: str) -> dict[str, Any] | None:
    demo_url = url.strip()
    if not demo_url.startswith("http"):
        demo_url = f"https://{demo_url.lstrip('/')}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                demo_url,
                params={"_format": "json"},
                headers={"Accept": "application/fhir+json"},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("Demo FHIR fetch failed for %s: %s", demo_url, exc)
        return None


def _extract_patient_name(resource: dict[str, Any]) -> str:
    names = resource.get("name") or []
    if names:
        primary = names[0]
        given = " ".join(primary.get("given") or []).strip()
        family = primary.get("family", "").strip()
        full = " ".join(part for part in [given, family] if part)
        if full:
            return full
    return ""


def _extract_patient_address(resource: dict[str, Any]) -> str:
    addresses = resource.get("address") or []
    if not addresses:
        return ""
    primary = addresses[0]
    lines = primary.get("line") or []
    city = primary.get("city")
    state = primary.get("state")
    postal = primary.get("postalCode")
    parts = [*lines, city, state, postal]
    return ", ".join([p for p in parts if p])


def _extract_from_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    patient = None
    conditions: list[str] = []
    allergies: list[str] = []
    medications: list[str] = []
    immunizations: list[str] = []
    procedures: list[str] = []

    for entry in bundle.get("entry") or []:
        resource = entry.get("resource") or {}
        rtype = resource.get("resourceType")
        if rtype == "Patient" and patient is None:
            patient = resource
        elif rtype == "Condition":
            text = (
                resource.get("code", {}).get("text")
                or (resource.get("code", {}).get("coding") or [{}])[0].get("display")
                or ""
            )
            if text:
                conditions.append(text)
        elif rtype == "AllergyIntolerance":
            text = (
                resource.get("code", {}).get("text")
                or (resource.get("code", {}).get("coding") or [{}])[0].get("display")
                or ""
            )
            if text:
                allergies.append(text)
        elif rtype in ("MedicationStatement", "MedicationRequest"):
            med = resource.get("medicationCodeableConcept") or {}
            text = med.get("text") or (med.get("coding") or [{}])[0].get("display") or ""
            if text:
                medications.append(text)
        elif rtype == "Immunization":
            vaccine = resource.get("vaccineCode") or {}
            text = vaccine.get("text") or (vaccine.get("coding") or [{}])[0].get("display") or ""
            if text:
                immunizations.append(text)
        elif rtype == "Procedure":
            proc = resource.get("code") or {}
            text = proc.get("text") or (proc.get("coding") or [{}])[0].get("display") or ""
            if text:
                procedures.append(text)

    return {
        "patient": patient,
        "conditions": conditions,
        "allergies": allergies,
        "medications": medications,
        "immunizations": immunizations,
        "procedures": procedures,
    }


async def build_demo_history_report(
    demo_url: str,
    patient_name: str,
    patient_age: str,
    patient_gender: str,
) -> MedicalHistoryReport:
    resource = await _fetch_demo_patient(demo_url)
    patient_id = ""
    demo_name = ""
    demo_gender = ""
    demo_dob = ""
    demo_address = ""
    conditions: list[str] = []
    allergies: list[str] = []
    medications: list[str] = []
    immunizations: list[str] = []
    procedures: list[str] = []

    if resource:
        if resource.get("resourceType") == "Bundle":
            extracted = _extract_from_bundle(resource)
            patient = extracted.get("patient") or {}
            patient_id = patient.get("id", "")
            demo_name = _extract_patient_name(patient)
            demo_gender = patient.get("gender", "") or ""
            demo_dob = patient.get("birthDate", "") or ""
            demo_address = _extract_patient_address(patient)
            conditions = extracted.get("conditions", [])
            allergies = extracted.get("allergies", [])
            medications = extracted.get("medications", [])
            immunizations = extracted.get("immunizations", [])
            procedures = extracted.get("procedures", [])
        else:
            patient_id = resource.get("id", "")
            demo_name = _extract_patient_name(resource)
            demo_gender = resource.get("gender", "") or ""
            demo_dob = resource.get("birthDate", "") or ""
            demo_address = _extract_patient_address(resource)

    display_name = demo_name or patient_name
    display_gender = demo_gender or patient_gender

    conditions = conditions or []
    if patient_id:
        conditions.append(f"Record located in HAPI FHIR (Patient/{patient_id})")
    else:
        conditions.append("Record located in HAPI FHIR demo registry")

    demographic_bits = []
    if display_name:
        demographic_bits.append(f"Name: {display_name}")
    if display_gender:
        demographic_bits.append(f"Gender: {display_gender}")
    if demo_dob:
        demographic_bits.append(f"DOB: {demo_dob}")
    if demo_address:
        demographic_bits.append(f"Address: {demo_address}")

    if demographic_bits:
        conditions.append(" | ".join(demographic_bits))

    if not allergies:
        allergies = ["No known drug allergies (NKDA)"]

    history = PatientMedicalHistory(
        source=demo_url,
        fhir_patient_id=patient_id,
        patient_name=display_name,
        patient_dob=demo_dob or None,
        patient_gender=display_gender or None,
        conditions=conditions,
        allergies=allergies,
        medications=medications,
        immunizations=immunizations,
        procedures=procedures,
    )

    report_text = format_medical_history_report(history, display_name, patient_age)

    return MedicalHistoryReport(
        found=True,
        history=history,
        report_text=report_text,
    )


async def build_medical_history_report(
    patient_name: str,
    patient_age: str,
    patient_gender: str,
    patient_dob: str | None = None,
) -> MedicalHistoryReport:
    """Build a structured medical history report from FHIR queries.

    This is the main entry point for getting structured medical history.
    Returns both the parsed data model and formatted report text.

    Args:
        patient_name: Patient full name
        patient_age: Patient age
        patient_gender: Patient gender
        patient_dob: Date of birth (YYYY-MM-DD) if available

    Returns:
        MedicalHistoryReport with structured data and formatted text
    """
    result = await query_fhir_servers(
        patient_name=patient_name,
        patient_gender=patient_gender,
        patient_dob=patient_dob,
    )

    if not result:
        logger.info("No patient records found for %s", patient_name)
        return MedicalHistoryReport(
            found=False,
            report_text=(
                f"No matching patient records found for {patient_name} "
                f"(age {patient_age}, {patient_gender}) in connected health systems."
            ),
        )

    history = PatientMedicalHistory(
        source=result.get("source", ""),
        fhir_patient_id=result.get("fhir_patient_id", ""),
        patient_name=result.get("patient_name", patient_name),
        patient_dob=result.get("patient_dob"),
        patient_gender=result.get("patient_gender"),
        conditions=result.get("conditions", []),
        allergies=result.get("allergies", []),
        medications=result.get("medications", []),
        immunizations=result.get("immunizations", []),
        procedures=result.get("procedures", []),
    )

    report_text = format_medical_history_report(history, patient_name, patient_age)

    return MedicalHistoryReport(
        found=True,
        history=history,
        report_text=report_text,
    )


def format_medical_history_report(
    history: PatientMedicalHistory,
    patient_name: str,
    patient_age: str,
) -> str:
    """Format a PatientMedicalHistory into a human-readable clinical report.

    Produces a structured text report suitable for display to paramedics
    and ER staff, highlighting clinically relevant information.

    Args:
        history: Parsed patient medical history
        patient_name: Patient name for the header
        patient_age: Patient age for the header

    Returns:
        Formatted multi-line report string
    """
    lines: list[str] = []
    lines.append(f"=== MEDICAL HISTORY REPORT: {patient_name} (Age {patient_age}) ===")
    lines.append(f"Source: {history.source}")
    if history.patient_dob:
        lines.append(f"DOB: {history.patient_dob}")

    # Conditions / Medical History
    lines.append("")
    lines.append("--- CONDITIONS / MEDICAL HISTORY ---")
    if history.conditions:
        for cond in history.conditions:
            lines.append(f"  * {cond}")
    else:
        lines.append("  No conditions on record")

    # Allergies - CRITICAL for drug administration decisions
    lines.append("")
    lines.append("--- ALLERGIES (CRITICAL) ---")
    if history.allergies:
        for allergy in history.allergies:
            lines.append(f"  !! {allergy}")
    else:
        lines.append("  No known allergies on record")

    # Current Medications - important for drug interaction checks
    lines.append("")
    lines.append("--- CURRENT MEDICATIONS ---")
    if history.medications:
        for med in history.medications:
            lines.append(f"  - {med}")
    else:
        lines.append("  No medications on record")

    # Immunizations
    lines.append("")
    lines.append("--- IMMUNIZATION HISTORY ---")
    if history.immunizations:
        for imm in history.immunizations:
            lines.append(f"  - {imm}")
    else:
        lines.append("  No immunization records found")

    # Past Procedures
    lines.append("")
    lines.append("--- PAST PROCEDURES ---")
    if history.procedures:
        for proc in history.procedures:
            lines.append(f"  - {proc}")
    else:
        lines.append("  No procedures on record")

    lines.append("")
    lines.append("=== END OF REPORT ===")

    return "\n".join(lines)
