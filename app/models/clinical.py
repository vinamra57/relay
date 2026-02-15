from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    source_type: str = ""
    source_label: str = ""
    timestamp: str = ""
    summary: str = ""
    uri: str | None = None


class PrepAlert(BaseModel):
    label: str = ""
    severity: str = "moderate"
    action: str = ""
    evidence: list[EvidenceItem] = []


class Contraindication(BaseModel):
    label: str = ""
    reason: str = ""
    evidence: list[EvidenceItem] = []


class LikelyDiagnosis(BaseModel):
    label: str = ""
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    evidence: list[EvidenceItem] = []


class Attachment(BaseModel):
    name: str = ""
    file_type: str = ""
    url: str = ""
    source: str = ""
    timestamp: str = ""


class ClinicalInsights(BaseModel):
    prep_alerts: list[PrepAlert] = []
    contraindications: list[Contraindication] = []
    likely_diagnoses: list[LikelyDiagnosis] = []
    evidence: list[EvidenceItem] = []
    attachments: list[Attachment] = []
    history_warnings: list[str] = []
    updated_at: str = ""


class HistoryWarnings(BaseModel):
    warnings: list[str] = []


class AskRequest(BaseModel):
    case_id: str
    question: str


class AskResponse(BaseModel):
    answer: str
    evidence: list[EvidenceItem] = []
    confidence: float = Field(0.0, ge=0.0, le=1.0)
