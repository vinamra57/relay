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

from app.models.medical_history import MedicalHistoryReport, PatientMedicalHistory
from app.services.fhir_client import query_fhir_servers

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

    report = await build_medical_history_report(
        patient_name=patient_name,
        patient_age=patient_age,
        patient_gender=patient_gender,
        patient_dob=patient_dob,
    )

    return report.report_text


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
