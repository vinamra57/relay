import logging

logger = logging.getLogger(__name__)


async def call_gp(
    patient_name: str,
    patient_age: str,
    patient_gender: str,
    patient_address: str,
) -> str:
    """Stub: Call a General Practitioner system to retrieve patient history.

    In production, this would:
    - Connect to a GP/PCP system API
    - Authenticate with the provider network
    - Query patient records by demographics
    - Return medical history, allergies, current medications, etc.

    Args:
        patient_name: Patient full name
        patient_age: Patient age
        patient_gender: Patient gender
        patient_address: Patient address

    Returns:
        Textual patient history document
    """
    logger.info(f"[GP STUB] Requesting patient history for {patient_name}")

    return (
        f"[GP STUB] Patient history request sent for {patient_name}, "
        f"age {patient_age}, {patient_gender}, residing at {patient_address}. "
        f"Awaiting GP system response. "
        f"In production, this would return: allergies, current medications, "
        f"medical history, previous surgeries, and primary care notes."
    )
