import logging
import re

from app.models.nemsis import NEMSISRecord
from app.services.gp_caller import call_gp
from app.services.medical_db import query_records

logger = logging.getLogger(__name__)

MIN_PHONE_DIGITS = 10  # Standard US phone number length


def _has_valid_phone(phone: str | None) -> bool:
    """Return True only if phone contains at least 10 digits."""
    if not phone:
        return False
    digits = re.sub(r"[^\d]", "", phone)
    return len(digits) >= MIN_PHONE_DIGITS


def is_core_info_complete(record: NEMSISRecord) -> bool:
    """Check if all 4 core patient identifiers are present."""
    p = record.patient
    has_name = bool(p.patient_name_first or p.patient_name_last)
    has_address = bool(p.patient_address)
    has_age = bool(p.patient_age)
    has_gender = bool(p.patient_gender)
    return has_name and has_address and has_age and has_gender


def is_gp_contact_available(record: NEMSISRecord) -> bool:
    """Check if GP name or confirmed GP phone is available.

    If a phone number is being dictated (even partially), wait until it
    has 10+ digits rather than triggering early on gp_name alone —
    otherwise the lookup returns a wrong number and ignores the real one.
    """
    p = record.patient
    if p.gp_phone:
        # Phone was mentioned — wait until fully extracted (10+ digits)
        return _has_valid_phone(p.gp_phone)
    # No phone mentioned — GP name alone is enough to trigger lookup
    return bool(p.gp_name)


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


