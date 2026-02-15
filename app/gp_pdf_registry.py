"""Registry of GP medical record PDFs by patient name.

Add PDFs under data/gp_records/ and register them here. When the GP call
"simulation" runs, only if the case patient name matches an entry do we
"receive" that PDF and record it in the DB (gp_response).

To add more PDFs later: put the file in data/gp_records/ and add a row below.
"""

import logging
from pathlib import Path

from app.services.gp_documents import extract_text_from_pdf, summarize_gp_document

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Patient name (exact match after normalizing) -> path relative to project root.
# Add more rows as you add more PDFs under data/gp_records/.
GP_PDF_RECORDS = [
    {"patient_name": "Daniel Wilson", "pdf_path": "data/gp_records/Medical Record.pdf"},
    # Example for future PDFs:
    # {"patient_name": "Jane Smith", "pdf_path": "data/gp_records/Jane_Smith_Records.pdf"},
]


def _normalize_name(name: str) -> str:
    if not name:
        return ""
    return " ".join(name.lower().split())


def get_pdf_path_for_patient(patient_name: str) -> Path | None:
    """Return the absolute path to the PDF for this patient, or None if no match."""
    key = _normalize_name(patient_name)
    if not key:
        return None
    for rec in GP_PDF_RECORDS:
        if _normalize_name(rec["patient_name"]) == key:
            full = _PROJECT_ROOT / rec["pdf_path"]
            if full.exists():
                return full
            logger.warning("GP PDF registered for %s but file not found: %s", patient_name, full)
            return None
    return None


def load_gp_record_for_patient(patient_name: str) -> tuple[str, str]:
    """Load the GP record PDF for this patient if name matches.

    Returns (raw_text, summary) if a matching PDF exists and could be read;
    otherwise ("", "No data found from the GP.").
    Simulates: only when name matches do we "receive" a PDF from the GP and record it.
    """
    path = get_pdf_path_for_patient(patient_name)
    if path is None:
        logger.info("No GP record PDF for patient '%s'; simulating no data from GP.", patient_name)
        return "", "No data found from the GP."

    raw_text = extract_text_from_pdf(str(path))
    summary = summarize_gp_document(raw_text)
    logger.info("GP record loaded for patient '%s' from %s (simulated receive).", patient_name, path.name)
    return raw_text, summary
