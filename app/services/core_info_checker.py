import asyncio
import logging

from app.models.nemsis import NEMSISRecord
from app.services.gp_caller import call_gp
from app.services.medical_db import query_records

logger = logging.getLogger(__name__)


def is_core_info_complete(record: NEMSISRecord) -> bool:
    """Check if all 4 core patient identifiers are present."""
    p = record.patient
    has_name = bool(p.patient_name_first or p.patient_name_last)
    has_address = bool(p.patient_address)
    has_age = bool(p.patient_age)
    has_gender = bool(p.patient_gender)
    return has_name and has_address and has_age and has_gender


def get_full_name(record: NEMSISRecord) -> str:
    """Get patient full name from NEMSIS record."""
    parts = []
    if record.patient.patient_name_first:
        parts.append(record.patient.patient_name_first)
    if record.patient.patient_name_last:
        parts.append(record.patient.patient_name_last)
    return " ".join(parts) if parts else "Unknown"


async def trigger_downstream(record: NEMSISRecord) -> tuple[str, str]:
    """Trigger GP call and medical DB query in parallel once core info is complete."""
    name = get_full_name(record)
    age = record.patient.patient_age or "Unknown"
    gender = record.patient.patient_gender or "Unknown"
    address = record.patient.patient_address or "Unknown"
    dob = record.patient.patient_date_of_birth

    logger.info("Core info complete for %s. Triggering downstream lookups.", name)

    gp_result, db_result = await asyncio.gather(
        call_gp(
            patient_name=name,
            patient_age=age,
            patient_gender=gender,
            patient_address=address,
        ),
        query_records(
            patient_name=name,
            patient_age=age,
            patient_gender=gender,
            patient_dob=dob,
        ),
    )

    return gp_result, db_result
