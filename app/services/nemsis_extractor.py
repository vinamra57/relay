import json
import logging
import re

from anthropic import AsyncAnthropic

from app.config import ANTHROPIC_API_KEY
from app.models.nemsis import NEMSISRecord

logger = logging.getLogger(__name__)

try:
    client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
except Exception as e:
    logger.warning("Anthropic client init failed (NEMSIS extraction will be skipped): %s", e)
    client = None

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
- For times, extract any mentioned timestamps (e.g. "dispatched at 14:30").
- For gp_name, extract any mention of the patient's GP, primary care physician, or family doctor name.
- For gp_practice_name, extract the practice/clinic name if mentioned separately from the doctor's name.
- For gp_phone, extract a phone number ONLY if it is explicitly identified as the GP or practice phone number.
  Do NOT extract family member, pharmacy, or other contact numbers as gp_phone.

You must respond with ONLY a single JSON object that matches this schema. No markdown, no explanation, only the JSON.
Schema:"""


def _json_schema_prompt() -> str:
    """Return the JSON schema for NEMSISRecord so Claude can output valid JSON."""
    schema = NEMSISRecord.model_json_schema()
    return json.dumps(schema, indent=2)


async def extract_nemsis(transcript: str, existing: NEMSISRecord | None = None) -> NEMSISRecord:
    """Extract NEMSIS-compliant data from transcript using Claude (raw text to table)."""
    if not client:
        return existing or NEMSISRecord()

    context = ""
    if existing:
        context = f"\n\nPreviously extracted data (merge with new findings, don't overwrite with nulls):\n{existing.model_dump_json()}"

    user_content = (
        f"Extract NEMSIS ePCR fields from this paramedic transcript. "
        f"Respond with ONLY a JSON object matching the schema above.\n\n"
        f"Transcript:\n{transcript}{context}"
    )

    try:
        message = await client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=4096,
            system=SYSTEM_PROMPT + "\n" + _json_schema_prompt(),
            messages=[{"role": "user", "content": user_content}],
        )

        raw = ""
        for block in message.content:
            if hasattr(block, "text"):
                raw += block.text

        # Strip optional markdown code fence
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

        extracted = NEMSISRecord.model_validate_json(raw)

        if existing:
            extracted = _merge_records(existing, extracted)

        return extracted

    except Exception as e:
        logger.error("NEMSIS extraction failed: %s", e)
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
