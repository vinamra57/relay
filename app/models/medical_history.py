"""Pydantic models for patient medical history from external databases."""

from pydantic import BaseModel


class PatientMedicalHistory(BaseModel):
    """Structured patient medical history from HIE/FHIR queries.

    This is the output format returned by the medical database service.
    Contains parsed, human-readable medical history for clinical use.
    """
    source: str = ""
    fhir_patient_id: str = ""
    patient_name: str = ""
    patient_dob: str | None = None
    patient_gender: str | None = None
    conditions: list[str] = []
    allergies: list[str] = []
    medications: list[str] = []
    immunizations: list[str] = []
    procedures: list[str] = []


class MedicalHistoryReport(BaseModel):
    """Full medical history report combining all sources.

    Combines FHIR query results with formatted text summary suitable
    for display to clinicians in both the ambulance and ER.
    """
    found: bool = False
    history: PatientMedicalHistory = PatientMedicalHistory()
    report_text: str = ""
