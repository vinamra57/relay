import json
import logging

from app.database import get_db
from app.models.clinical import AskResponse, EvidenceItem
from app.services.llm import get_llm_client

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an ER clinical assistant answering questions about an incoming patient.
Use only the provided case data. Keep answers short, factual, and operational.
Include evidence snippets where possible.
Return structured data only.
"""


async def _load_case_data(case_id: str) -> dict:
    db = await get_db()
    case = await db.fetch_one("SELECT * FROM cases WHERE id = ?", (case_id,))
    if not case:
        raise ValueError(f"Case {case_id} not found")

    nemsis_data = {}
    try:
        nemsis_data = json.loads(case["nemsis_data"] or "{}")
    except json.JSONDecodeError:
        pass

    transcripts = []
    try:
        transcripts = await db.fetch_all(
            "SELECT segment_text, timestamp FROM transcripts WHERE case_id = ? ORDER BY id DESC LIMIT 3",
            (case_id,),
        )
    except Exception:
        logger.debug("Failed to load transcripts for case %s", case_id)

    return {
        "nemsis": nemsis_data,
        "transcript": case["full_transcript"] or "",
        "gp_response": case["gp_response"] or "",
        "medical_db_response": case["medical_db_response"] or "",
        "transcripts": transcripts,
    }


def _dummy_answer(question: str, data: dict) -> AskResponse:
    nemsis = data.get("nemsis", {})
    vitals = nemsis.get("vitals", {})
    situation = nemsis.get("situation", {})
    meds = nemsis.get("medications", {}).get("medications", [])

    answer = "No data yet."
    if "vital" in question.lower() or "vitals" in question.lower():
        parts = []
        if vitals.get("heart_rate"):
            parts.append(f"HR {vitals['heart_rate']}")
        if vitals.get("spo2"):
            parts.append(f"SpO2 {vitals['spo2']}%")
        if vitals.get("systolic_bp") and vitals.get("diastolic_bp"):
            parts.append(f"BP {vitals['systolic_bp']}/{vitals['diastolic_bp']}")
        answer = "Latest vitals: " + (", ".join(parts) if parts else "pending")
    elif "med" in question.lower():
        answer = "Meds given: " + (", ".join(meds) if meds else "none recorded")
    elif "blood" in question.lower() or "lab" in question.lower():
        answer = "Latest labs: Troponin 0.16 ng/mL, WBC 11.2, Glucose 145 mg/dL (demo)."
    elif "complaint" in question.lower() or "impression" in question.lower():
        answer = situation.get("chief_complaint") or "Chief complaint not recorded yet."

    evidence = []
    for row in data.get("transcripts", []):
        evidence.append(EvidenceItem(
            source_type="transcript",
            source_label="EMS audio",
            timestamp=row["timestamp"],
            summary=row["segment_text"],
        ))

    return AskResponse(answer=answer, evidence=evidence, confidence=0.55)


async def answer_question(case_id: str, question: str) -> AskResponse:
    data = await _load_case_data(case_id)

    client = get_llm_client()
    if not client.available():
        return _dummy_answer(question, data)

    user_content = (
        f"Question: {question}\n\n"
        f"NEMSIS Data:\n{json.dumps(data['nemsis'], indent=2)}\n\n"
        f"Transcript:\n{data['transcript']}\n\n"
        f"GP Response:\n{data['gp_response']}\n\n"
        f"Medical DB Response:\n{data['medical_db_response']}\n\n"
    )

    try:
        parsed = await client.generate_json(
            system=SYSTEM_PROMPT,
            user=user_content,
            response_model=AskResponse,
            max_tokens=512,
        )
        return parsed
    except Exception as e:
        logger.error("Question answer failed for %s: %s", case_id, e)
        return _dummy_answer(question, data)
