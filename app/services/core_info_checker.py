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


def is_gp_contact_available(record: NEMSISRecord) -> bool:
    """Check if GP name or confirmed GP phone is available."""
    p = record.patient
    return bool(p.gp_name or p.gp_phone)


def get_full_name(record: NEMSISRecord) -> str:
    """Get patient full name from NEMSIS record."""
    parts = []
    if record.patient.patient_name_first:
        parts.append(record.patient.patient_name_first)
    if record.patient.patient_name_last:
        parts.append(record.patient.patient_name_last)
    return " ".join(parts) if parts else "Unknown"


async def trigger_medical_db(record: NEMSISRecord) -> str:
    """Trigger medical DB lookup. Requires core info only."""
    name = get_full_name(record)
    age = record.patient.patient_age or "Unknown"
    gender = record.patient.patient_gender or "Unknown"
    dob = record.patient.patient_date_of_birth

    logger.info("Core info complete for %s. Triggering medical DB lookup.", name)

    return await query_records(
        patient_name=name,
        patient_age=age,
        patient_gender=gender,
        patient_dob=dob,
    )


async def trigger_gp_call(record: NEMSISRecord, case_id: str) -> str:
    """Trigger GP call. Requires core info + GP contact."""
    name = get_full_name(record)
    age = record.patient.patient_age or "Unknown"
    gender = record.patient.patient_gender or "Unknown"
    address = record.patient.patient_address or "Unknown"
    dob = record.patient.patient_date_of_birth

    logger.info("GP contact available for %s. Triggering GP call.", name)

    chief_complaint = (
        record.situation.chief_complaint
        or record.situation.primary_impression
    )

    return await call_gp(
        patient_name=name,
        patient_age=age,
        patient_gender=gender,
        patient_address=address,
        gp_name=record.patient.gp_name,
        gp_phone=record.patient.gp_phone,
        gp_practice_name=record.patient.gp_practice_name,
        patient_dob=dob,
        case_id=case_id,
        chief_complaint=chief_complaint,
    )


async def trigger_downstream(record: NEMSISRecord) -> tuple[str, str]:
    """Legacy: Trigger GP call and medical DB query in parallel.

    Kept for backward compatibility. New code should use
    trigger_medical_db() and trigger_gp_call() separately.
    """
    import asyncio

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
            gp_name=record.patient.gp_name,
            gp_phone=record.patient.gp_phone,
            gp_practice_name=record.patient.gp_practice_name,
            patient_dob=dob,
        ),
        query_records(
            patient_name=name,
            patient_age=age,
            patient_gender=gender,
            patient_dob=dob,
        ),
    )

    return gp_result, db_result
