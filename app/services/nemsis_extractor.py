import json
import logging

from openai import AsyncOpenAI

from app.config import OPENAI_API_KEY, DUMMY_MODE
from app.models.nemsis import NEMSISRecord

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

SYSTEM_PROMPT = """You are an EMS data extraction AI specialized in NEMSIS-compliant ePCR (Electronic Patient Care Report) fields.

Your task: Extract structured medical data from paramedic voice transcripts.

Rules:
- Only fill fields you can confidently extract from the transcript.
- Leave fields as null if the information is not present or unclear.
- For patient_name_first and patient_name_last, split full names appropriately.
- For vitals, extract numeric values only.
- For procedures and medications, list each one mentioned.
- For gender, use: "Male", "Female", or "Unknown".
- Be precise with medical terminology in primary_impression and secondary_impression.
- Extract any mentioned location/address into the patient address fields."""


async def extract_nemsis(transcript: str, existing: NEMSISRecord | None = None) -> NEMSISRecord:
    """Extract NEMSIS-compliant data from transcript using GPT-5.2 structured output."""
    if DUMMY_MODE or not client:
        return _dummy_extract(transcript)

    context = ""
    if existing:
        context = f"\n\nPreviously extracted data (merge with new findings, don't overwrite with nulls):\n{existing.model_dump_json()}"

    try:
        response = await client.chat.completions.create(
            model="gpt-5.2",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Extract NEMSIS ePCR fields from this paramedic transcript:\n\n{transcript}{context}",
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "nemsis_record",
                    "strict": True,
                    "schema": NEMSISRecord.model_json_schema(),
                },
            },
        )

        raw = response.choices[0].message.content
        extracted = NEMSISRecord.model_validate_json(raw)

        # Merge: keep existing non-null values if new extraction returns null
        if existing:
            extracted = _merge_records(existing, extracted)

        return extracted

    except Exception as e:
        logger.error(f"NEMSIS extraction failed: {e}")
        return existing or NEMSISRecord()


def _merge_records(existing: NEMSISRecord, new: NEMSISRecord) -> NEMSISRecord:
    """Merge two NEMSIS records, preferring new non-null values."""
    existing_dict = existing.model_dump()
    new_dict = new.model_dump()

    def _merge(old: dict, updated: dict) -> dict:
        result = {}
        for key in old:
            if key in updated:
                if isinstance(old[key], dict) and isinstance(updated[key], dict):
                    result[key] = _merge(old[key], updated[key])
                elif isinstance(updated[key], list):
                    # For lists, combine unique items
                    combined = list(old.get(key, []) or [])
                    for item in (updated[key] or []):
                        if item not in combined:
                            combined.append(item)
                    result[key] = combined
                elif updated[key] is not None:
                    result[key] = updated[key]
                else:
                    result[key] = old[key]
            else:
                result[key] = old[key]
        return result

    merged = _merge(existing_dict, new_dict)
    return NEMSISRecord.model_validate(merged)


def _dummy_extract(transcript: str) -> NEMSISRecord:
    """Simple keyword-based extraction for dummy mode."""
    record = NEMSISRecord()
    text = transcript.lower()

    # Extract name
    if "john" in text and "smith" in text:
        record.patient.patient_name_first = "John"
        record.patient.patient_name_last = "Smith"
    if "david" in text:
        record.patient.patient_name_first = "John David"

    # Extract age/gender
    if "45 year old" in text:
        record.patient.patient_age = "45"
    if "male" in text:
        record.patient.patient_gender = "Male"
    elif "female" in text:
        record.patient.patient_gender = "Female"

    # Extract address
    if "742 evergreen terrace" in text:
        record.patient.patient_address = "742 Evergreen Terrace"
        record.patient.patient_city = "Springfield"
        record.patient.patient_state = "Illinois"

    # Extract vitals
    if "160 over 95" in text or "160/95" in text:
        record.vitals.systolic_bp = 160
        record.vitals.diastolic_bp = 95
    if "heart rate 110" in text or "110 beats" in text:
        record.vitals.heart_rate = 110
    if "respiratory rate 22" in text:
        record.vitals.respiratory_rate = 22
    if "spo2 94" in text or "94 percent" in text:
        record.vitals.spo2 = 94
    if "glucose 145" in text or "blood glucose 145" in text:
        record.vitals.blood_glucose = 145.0
    if "gcs 15" in text:
        record.vitals.gcs_total = 15

    # Extract situation
    if "chest pain" in text:
        record.situation.chief_complaint = "Chest pain radiating to left arm"
    if "stemi" in text:
        record.situation.primary_impression = "STEMI"
    if "st elevation" in text:
        record.situation.secondary_impression = "ST elevation in leads V1-V4"

    # Extract procedures
    procedures = []
    if "iv access" in text:
        procedures.append("IV access - right antecubital")
    if "12 lead" in text or "ecg" in text:
        procedures.append("12-lead ECG")
    if "cardiac catheterization" in text or "cath lab" in text:
        procedures.append("Cardiac catheterization lab activation")
    if procedures:
        record.procedures.procedures = procedures

    # Extract medications
    medications = []
    if "aspirin" in text:
        medications.append("Aspirin 324mg PO")
    if "nitroglycerin" in text:
        medications.append("Nitroglycerin 0.4mg SL")
    if medications:
        record.medications.medications = medications

    return record
