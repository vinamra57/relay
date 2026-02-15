"""Tests for summary service with database integration."""

import json

import pytest

from app.models.summary import CaseSummary, HospitalSummary
from app.services.summary import (
    _empty_case_summary,
    _empty_hospital_summary,
    _load_case_data,
    generate_summary,
    get_summary_for_hospital,
)


async def _create_case_with_data(db, case_id: str = "test-sum-1", nemsis: dict | None = None):
    """Helper to insert a case with NEMSIS data directly into DB."""
    nemsis_json = json.dumps(nemsis or {})
    await db.execute(
        """INSERT INTO cases
           (id, created_at, status, full_transcript, nemsis_data, patient_name,
            patient_age, patient_gender, gp_response, medical_db_response, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            case_id,
            "2025-01-01T00:00:00",
            "active",
            "Patient is a 45 year old male with chest pain",
            nemsis_json,
            "John Smith",
            "45",
            "Male",
            "[GP STUB] History for John Smith",
            "[MEDICAL DB STUB] Records for John Smith",
            "2025-01-01T00:00:00",
        ),
    )
    await db.commit()


STEMI_NEMSIS = {
    "patient": {
        "patient_name_first": "John",
        "patient_name_last": "Smith",
        "patient_age": "45",
        "patient_gender": "Male",
    },
    "vitals": {
        "systolic_bp": 160,
        "diastolic_bp": 95,
        "heart_rate": 110,
        "spo2": 94,
    },
    "situation": {
        "chief_complaint": "Chest pain",
        "primary_impression": "STEMI",
    },
    "procedures": {"procedures": ["IV access", "12-lead ECG"]},
    "medications": {"medications": ["Aspirin 324mg"]},
}


class TestLoadCaseData:
    async def test_load_existing_case(self, db):
        await _create_case_with_data(db, "load-1", STEMI_NEMSIS)
        data = await _load_case_data("load-1")
        assert data["case_id"] == "load-1"
        assert data["patient_name"] == "John Smith"
        assert data["nemsis"]["patient"]["patient_name_first"] == "John"

    async def test_load_missing_case_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            await _load_case_data("nonexistent")

    async def test_load_case_with_bad_nemsis_json(self, db):
        await db.execute(
            """INSERT INTO cases
               (id, created_at, status, nemsis_data, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("bad-json", "2025-01-01", "active", "not-json{", "2025-01-01"),
        )
        await db.commit()
        data = await _load_case_data("bad-json")
        assert data["nemsis"] == {}


class TestEmptyFallbacks:
    """Without LLM keys, summaries return empty fallbacks."""

    def test_empty_case_summary(self):
        s = _empty_case_summary()
        assert isinstance(s, CaseSummary)
        assert s.urgency == "moderate"
        assert s.one_liner == "No summary available."

    def test_empty_hospital_summary(self):
        s = _empty_hospital_summary()
        assert isinstance(s, HospitalSummary)
        assert s.priority_level == "moderate"
        assert s.patient_demographics == ""


class TestGenerateSummary:
    async def test_returns_case_summary(self, db):
        """Without LLM, returns empty fallback summary."""
        await _create_case_with_data(db, "gen-1", STEMI_NEMSIS)
        result = await generate_summary("gen-1")
        assert isinstance(result, CaseSummary)
        # No LLM in test mode → empty fallback
        assert result.urgency == "moderate"

    async def test_empty_nemsis_returns_moderate(self, db):
        await _create_case_with_data(db, "gen-empty", {})
        result = await generate_summary("gen-empty")
        assert isinstance(result, CaseSummary)
        assert result.urgency == "moderate"

    async def test_missing_case_raises(self, db):
        with pytest.raises(ValueError):
            await generate_summary("nonexistent")


class TestGetSummaryForHospital:
    async def test_returns_hospital_summary(self, db):
        """Without LLM, returns empty fallback hospital summary."""
        await _create_case_with_data(db, "hosp-1", STEMI_NEMSIS)
        result = await get_summary_for_hospital("hosp-1")
        assert isinstance(result, HospitalSummary)
        # No LLM in test mode → empty fallback
        assert result.priority_level == "moderate"

    async def test_hospital_summary_empty_case(self, db):
        await _create_case_with_data(db, "hosp-empty", {})
        result = await get_summary_for_hospital("hosp-empty")
        assert isinstance(result, HospitalSummary)
        assert result.priority_level == "moderate"

    async def test_missing_case_raises(self, db):
        with pytest.raises(ValueError):
            await get_summary_for_hospital("nonexistent")
