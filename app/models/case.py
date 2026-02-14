from pydantic import BaseModel

from app.models.nemsis import NEMSISRecord


class CaseCreate(BaseModel):
    pass


class CaseResponse(BaseModel):
    id: str
    created_at: str
    status: str
    full_transcript: str
    nemsis_data: NEMSISRecord
    core_info_complete: bool
    patient_name: str | None = None
    patient_address: str | None = None
    patient_age: str | None = None
    patient_gender: str | None = None
    gp_response: str | None = None
    medical_db_response: str | None = None
    summary: str | None = None
    updated_at: str | None = None


class CaseListItem(BaseModel):
    id: str
    created_at: str
    status: str
    patient_name: str | None = None
    core_info_complete: bool
    chief_complaint: str | None = None


class CaseStatusUpdate(BaseModel):
    status: str
