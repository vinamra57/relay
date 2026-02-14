from pydantic import BaseModel


class HospitalSummary(BaseModel):
    """Structured summary for hospital preparation (GPT-5.2 structured output)."""

    patient_demographics: str
    chief_complaint: str
    vitals_summary: str
    procedures_performed: str
    medications_administered: str
    clinical_impression: str
    recommended_preparations: str
    patient_history: str
    priority_level: str  # "critical", "high", "moderate", "low"
    special_considerations: str


class CaseSummary(BaseModel):
    """General case summary for paramedic/dispatch view."""

    one_liner: str
    clinical_narrative: str
    key_findings: list[str]
    actions_taken: list[str]
    urgency: str  # "critical", "high", "moderate", "low"
