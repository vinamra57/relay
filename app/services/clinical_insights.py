import json
import logging
from datetime import UTC, datetime

from app.database import get_db
from app.models.clinical import (
    Attachment,
    ClinicalInsights,
    Contraindication,
    EvidenceItem,
    HistoryWarnings,
    LikelyDiagnosis,
    PrepAlert,
)
from app.services.llm import get_llm_client

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a clinical insights assistant for an emergency department dashboard.

Generate non-treatment, preparation-focused insights for hospital staff based on EMS data.
Return structured data only.

Rules:
- prep_alerts: 0-3 items. Focus on hospital preparation (e.g., stroke alert, cath lab readiness).
- contraindications: 0-4 items. Flag relevant allergies or interactions; do not give treatment advice.
- likely_diagnoses: 1-4 items. Provide likely working impressions with confidence (0-1).
- history_warnings: 0-5 succinct warnings based on past history/allergies/meds (non-treatment).
- evidence: concise source snippets supporting alerts or risks.
- attachments: if GP or medical records mention documents, include file references.
- updated_at: ISO timestamp.
"""

HISTORY_WARNINGS_PROMPT = """You are reviewing patient history for EMS handoff.

Based on the data provided, list up to 5 concise warnings or risks tied to the patient's
history, allergies, or chronic meds. Do not provide treatment advice. Output only JSON
with a single key "warnings" as a list of short strings."""


async def _load_case_data(case_id: str) -> dict:
    db = await get_db()
    case = await db.fetch_one("SELECT * FROM cases WHERE id = ?", (case_id,))
    if not case:
        raise ValueError(f"Case {case_id} not found")

    nemsis = {}
    try:
        nemsis = json.loads(case["nemsis_data"] or "{}")
    except json.JSONDecodeError:
        logger.warning("Failed to parse NEMSIS data for case %s", case_id)

    transcripts = []
    try:
        transcripts = await db.fetch_all(
            "SELECT segment_text, timestamp FROM transcripts WHERE case_id = ? ORDER BY id DESC LIMIT 4",
            (case_id,),
        )
    except Exception:
        logger.debug("Failed to load transcripts for case %s", case_id)

    return {
        "case_id": case_id,
        "nemsis": nemsis,
        "transcript": case["full_transcript"] or "",
        "gp_response": case["gp_response"] or "",
        "medical_db_response": case["medical_db_response"] or "",
        "transcripts": transcripts,
    }


def _build_evidence_items(data: dict) -> list[EvidenceItem]:
    evidence = []
    for row in data.get("transcripts", []):
        evidence.append(EvidenceItem(
            source_type="transcript",
            source_label="EMS audio",
            timestamp=row["timestamp"],
            summary=row["segment_text"],
        ))

    if data.get("gp_response"):
        evidence.append(EvidenceItem(
            source_type="gp_call",
            source_label="GP transmission",
            timestamp=datetime.now(UTC).isoformat(),
            summary=data["gp_response"][:180],
        ))

    if data.get("medical_db_response"):
        evidence.append(EvidenceItem(
            source_type="medical_db",
            source_label="Medical records",
            timestamp=datetime.now(UTC).isoformat(),
            summary=data["medical_db_response"][:180],
        ))

    return evidence


def _dummy_insights(data: dict) -> ClinicalInsights:
    nemsis = data.get("nemsis", {})
    situation = nemsis.get("situation", {})
    vitals = nemsis.get("vitals", {})
    history = nemsis.get("history", {})
    medications = nemsis.get("medications", {})

    impression = (situation.get("primary_impression") or "").lower()
    alerts: list[PrepAlert] = []

    if "stemi" in impression:
        alerts.append(PrepAlert(
            label="STEMI Alert",
            severity="critical",
            action="Prep cath lab + cardiology team",
        ))
    if "stroke" in impression:
        alerts.append(PrepAlert(
            label="Stroke Alert",
            severity="critical",
            action="Prep CT + neuro team",
        ))
    if "trauma" in impression:
        alerts.append(PrepAlert(
            label="Trauma Activation",
            severity="high",
            action="Prep trauma bay + blood products",
        ))
    if vitals.get("spo2") and vitals.get("spo2") < 92:
        alerts.append(PrepAlert(
            label="Respiratory Risk",
            severity="high",
            action="Prepare airway support",
        ))

    contraindications: list[Contraindication] = []
    allergies = history.get("allergies", []) or []
    if any("penicillin" in a.lower() for a in allergies):
        contraindications.append(Contraindication(
            label="Penicillin allergy",
            reason="Avoid beta-lactam exposure",
        ))

    meds = medications.get("medications", []) or []
    if any("warfarin" in m.lower() or "anticoagulant" in m.lower() for m in meds):
        contraindications.append(Contraindication(
            label="On anticoagulant",
            reason="Higher bleed risk",
        ))

    diagnoses: list[LikelyDiagnosis] = []
    if impression:
        diagnoses.append(LikelyDiagnosis(label=situation.get("primary_impression", ""), confidence=0.82))
    if situation.get("chief_complaint"):
        diagnoses.append(LikelyDiagnosis(label=situation.get("chief_complaint"), confidence=0.64))

    evidence = _build_evidence_items(data)

    attachments = []
    if data.get("gp_response"):
        attachments = [
            Attachment(
                name="GP Lab Results",
                file_type="PDF",
                url="/static/assets/gp_lab_results.pdf",
                source="GP transmission",
                timestamp=datetime.now(UTC).isoformat(),
            ),
            Attachment(
                name="Medication List",
                file_type="PDF",
                url="/static/assets/gp_medication_list.pdf",
                source="GP transmission",
                timestamp=datetime.now(UTC).isoformat(),
            ),
            Attachment(
                name="Radiology Report",
                file_type="PDF",
                url="/static/assets/radiology_report.pdf",
                source="GP transmission",
                timestamp=datetime.now(UTC).isoformat(),
            ),
            Attachment(
                name="Medication Reconciliation",
                file_type="PDF",
                url="/static/assets/medication_reconciliation.pdf",
                source="GP transmission",
                timestamp=datetime.now(UTC).isoformat(),
            ),
            Attachment(
                name="Prior Discharge Summary",
                file_type="PDF",
                url="/static/assets/prior_discharge_summary.pdf",
                source="GP transmission",
                timestamp=datetime.now(UTC).isoformat(),
            ),
            Attachment(
                name="12-Lead ECG",
                file_type="Image",
                url="/static/assets/ecg_trace.svg",
                source="GP transmission",
                timestamp=datetime.now(UTC).isoformat(),
            ),
            Attachment(
                name="Scene Photo",
                file_type="Image",
                url="/static/assets/scene_photo.svg",
                source="GP transmission",
                timestamp=datetime.now(UTC).isoformat(),
            ),
        ]

    history_warnings = _dummy_history_warnings(data)

    return ClinicalInsights(
        prep_alerts=alerts,
        contraindications=contraindications,
        likely_diagnoses=diagnoses,
        evidence=evidence,
        attachments=attachments,
        history_warnings=history_warnings,
        updated_at=datetime.now(UTC).isoformat(),
    )


def _dummy_history_warnings(data: dict) -> list[str]:
    nemsis = data.get("nemsis", {})
    history = nemsis.get("history", {})
    allergies = history.get("allergies") or []
    med_history = history.get("medical_history") or []
    warnings = []
    if any("penicillin" in a.lower() for a in allergies):
        warnings.append("Penicillin allergy on file")
    if any("diabetes" in h.lower() for h in med_history):
        warnings.append("Diabetes history — monitor glucose trends")
    if any("hypertension" in h.lower() for h in med_history):
        warnings.append("Hypertension history — anticipate elevated BP")
    if not warnings and (allergies or med_history):
        warnings.append("History present — review PMH/allergies")
    return warnings


async def _build_history_warnings(data: dict) -> list[str]:
    client = get_llm_client()
    if not client.available():
        return _dummy_history_warnings(data)

    user_content = (
        f"NEMSIS Data:\n{json.dumps(data['nemsis'], indent=2)}\n\n"
        f"GP Response:\n{data['gp_response']}\n\n"
        f"Medical DB Response:\n{data['medical_db_response']}\n\n"
    )

    try:
        parsed = await client.generate_json(
            system=HISTORY_WARNINGS_PROMPT,
            user=user_content,
            response_model=HistoryWarnings,
            max_tokens=512,
        )
        if parsed:
            return [w for w in parsed.warnings if isinstance(w, str)]
        return _dummy_history_warnings(data)
    except Exception as exc:
        logger.error("History warnings generation failed: %s", exc)
        return _dummy_history_warnings(data)


async def build_clinical_insights(case_id: str) -> ClinicalInsights:
    data = await _load_case_data(case_id)
    gp_available = bool(data.get("gp_response"))

    client = get_llm_client()
    if not client.available():
        return _dummy_insights(data)

    user_content = (
        f"Transcript:\n{data['transcript']}\n\n"
        f"NEMSIS Data:\n{json.dumps(data['nemsis'], indent=2)}\n\n"
        f"GP Response:\n{data['gp_response']}\n\n"
        f"Medical DB Response:\n{data['medical_db_response']}\n\n"
    )

    try:
        parsed = await client.generate_json(
            system=SYSTEM_PROMPT,
            user=user_content,
            response_model=ClinicalInsights,
            max_tokens=2048,
        )
        if parsed is None:
            logger.error("LLM returned no parsed insights for case %s", case_id)
            return _dummy_insights(data)
        parsed.updated_at = datetime.now(UTC).isoformat()
        parsed.history_warnings = await _build_history_warnings(data)
        if gp_available and not parsed.attachments:
            parsed.attachments = _dummy_insights(data).attachments
        return parsed
    except Exception as e:
        logger.error("Clinical insights generation failed for %s: %s", case_id, e)
        return _dummy_insights(data)


async def update_case_insights(case_id: str) -> ClinicalInsights:
    insights = await build_clinical_insights(case_id)
    db = await get_db()
    await db.execute(
        "UPDATE cases SET clinical_insights = ?, updated_at = ? WHERE id = ?",
        (json.dumps(insights.model_dump()), datetime.now(UTC).isoformat(), case_id),
    )
    await db.commit()
    return insights


async def get_cached_insights(case_id: str) -> ClinicalInsights:
    db = await get_db()
    case = await db.fetch_one("SELECT clinical_insights FROM cases WHERE id = ?", (case_id,))
    if not case:
        raise ValueError(f"Case {case_id} not found")
    raw = case["clinical_insights"]
    if not raw:
        return await update_case_insights(case_id)
    try:
        return ClinicalInsights.model_validate_json(raw)
    except Exception:
        logger.warning("Failed to parse cached clinical insights for %s", case_id)
        return await update_case_insights(case_id)
