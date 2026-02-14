import logging

from openai import AsyncOpenAI

from app.config import DUMMY_MODE, OPENAI_API_KEY
from app.models.nemsis import NEMSISRecord

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

SYSTEM_PROMPT = """You are an EMS data extraction AI specialized in NEMSIS v3.5-compliant ePCR (Electronic Patient Care Report) fields.

Your task: Extract structured medical data from paramedic voice transcripts.

Rules:
- Only fill fields you can confidently extract from the transcript.
- Leave fields as null if the information is not present or unclear.
- For patient_name_first and patient_name_last, split full names appropriately.
- For vitals, extract numeric values only.
- For procedures and medications, list each one mentioned.
- For gender, use: "Male", "Female", or "Unknown".
- Be precise with medical terminology in primary_impression and secondary_impression.
- Extract any mentioned location/address into the patient address fields.
- For GCS, extract individual components (eye, verbal, motor) when mentioned.
- For temperature, extract in Fahrenheit or Celsius as mentioned.
- For pain_scale, extract 0-10 numeric value.
- For medical_history, extract conditions like "hypertension", "diabetes", etc.
- For allergies, extract any mentioned drug or environmental allergies.
- For disposition fields, extract transport destination and mode if mentioned.
- For times, extract any mentioned timestamps (e.g. "dispatched at 14:30")."""


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

        raw = response.choices[0].message.content or "{}"
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
    if "female" in text:
        record.patient.patient_gender = "Female"
    elif "male" in text:
        record.patient.patient_gender = "Male"

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
    if "eyes 4" in text:
        record.vitals.gcs_eye = 4
    if "verbal 5" in text:
        record.vitals.gcs_verbal = 5
    if "motor 6" in text:
        record.vitals.gcs_motor = 6
    if "temperature 101" in text or "temp 101" in text:
        record.vitals.temperature = 101.0
    if "pain" in text and ("8 out of 10" in text or "8/10" in text):
        record.vitals.pain_scale = 8
    if "alert and oriented" in text:
        record.vitals.level_of_consciousness = "Alert and oriented"
    elif "unresponsive" in text:
        record.vitals.level_of_consciousness = "Unresponsive"

    # Extract situation
    if "chest pain" in text:
        record.situation.chief_complaint = "Chest pain radiating to left arm"
    if "stemi" in text:
        record.situation.primary_impression = "STEMI"
    if "st elevation" in text:
        record.situation.secondary_impression = "ST elevation in leads V1-V4"
    if "30 minutes ago" in text:
        record.situation.complaint_duration = "30 minutes"

    # Extract procedures
    procedures = []
    if "iv access" in text:
        procedures.append("IV access - right antecubital")
    if "12 lead" in text or "ecg" in text:
        procedures.append("12-lead ECG")
    if "cardiac catheterization" in text or "cath lab" in text:
        procedures.append("Cardiac catheterization lab activation")
    if "intubation" in text or "intubated" in text:
        procedures.append("Endotracheal intubation")
    if procedures:
        record.procedures.procedures = procedures

    # Extract medications
    medications = []
    if "aspirin" in text:
        medications.append("Aspirin 324mg PO")
    if "nitroglycerin" in text:
        medications.append("Nitroglycerin 0.4mg SL")
    if "morphine" in text:
        medications.append("Morphine 4mg IV")
    if "epinephrine" in text:
        medications.append("Epinephrine 1mg IV")
    if medications:
        record.medications.medications = medications

    # Extract history
    history_conditions = []
    if "hypertension" in text or "high blood pressure" in text:
        history_conditions.append("Hypertension")
    if "diabetes" in text:
        history_conditions.append("Diabetes mellitus type 2")
    if "copd" in text:
        history_conditions.append("COPD")
    if "asthma" in text:
        history_conditions.append("Asthma")
    if "coronary artery disease" in text or "cad" in text:
        history_conditions.append("Coronary artery disease")
    if history_conditions:
        record.history.medical_history = history_conditions

    # Extract allergies
    allergies = []
    if "allergic to penicillin" in text or "penicillin allergy" in text:
        allergies.append("Penicillin")
    if "no known allergies" in text or "nkda" in text:
        allergies.append("NKDA")
    if "allergic to sulfa" in text:
        allergies.append("Sulfonamides")
    if allergies:
        record.history.allergies = allergies

    # Extract disposition
    if "transporting to" in text or "en route to" in text:
        record.disposition.transport_mode = "Ground ambulance"
        record.disposition.transport_disposition = "Transported by EMS"
    if "general hospital" in text:
        record.disposition.destination_facility = "Springfield General Hospital"
        record.disposition.destination_type = "Hospital"
    if "cath lab" in text and "activating" in text:
        record.disposition.hospital_team_activation = ["Cardiac catheterization team"]
    if "trauma" in text and "team" in text:
        record.disposition.hospital_team_activation = ["Trauma team"]

    return record
