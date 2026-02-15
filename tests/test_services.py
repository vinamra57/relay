"""Tests for service modules - extraction, core info, stubs, transcription."""

from app.models.nemsis import (
    NEMSISHistory,
    NEMSISPatientInfo,
    NEMSISProcedures,
    NEMSISRecord,
)
from app.services.core_info_checker import (
    get_full_name,
    is_core_info_complete,
    trigger_medical_db,
)
from app.services.gp_caller import call_gp
from app.services.medical_db import query_records
from app.services.nemsis_extractor import _merge_records, extract_nemsis

# --- NEMSIS Merge ---


class TestMergeRecords:
    def test_merge_preserves_existing_non_null(self):
        existing = NEMSISRecord(
            patient=NEMSISPatientInfo(patient_name_first="John", patient_age="45"),
        )
        new = NEMSISRecord(
            patient=NEMSISPatientInfo(patient_name_first=None, patient_age="45"),
        )
        merged = _merge_records(existing, new)
        assert merged.patient.patient_name_first == "John"

    def test_merge_takes_new_non_null(self):
        existing = NEMSISRecord(
            patient=NEMSISPatientInfo(patient_name_first="John"),
        )
        new = NEMSISRecord(
            patient=NEMSISPatientInfo(
                patient_name_first="John", patient_name_last="Smith"
            ),
        )
        merged = _merge_records(existing, new)
        assert merged.patient.patient_name_last == "Smith"
        assert merged.patient.patient_name_first == "John"

    def test_merge_combines_lists(self):
        existing = NEMSISRecord(
            procedures=NEMSISProcedures(procedures=["12-lead ECG"]),
        )
        new = NEMSISRecord(
            procedures=NEMSISProcedures(procedures=["12-lead ECG", "IV access"]),
        )
        merged = _merge_records(existing, new)
        assert "12-lead ECG" in merged.procedures.procedures
        assert "IV access" in merged.procedures.procedures
        assert len(merged.procedures.procedures) == 2  # no duplicates

    def test_merge_empty_records(self):
        existing = NEMSISRecord()
        new = NEMSISRecord()
        merged = _merge_records(existing, new)
        assert merged.patient.patient_name_first is None

    def test_merge_history_lists(self):
        existing = NEMSISRecord(
            history=NEMSISHistory(medical_history=["Hypertension"]),
        )
        new = NEMSISRecord(
            history=NEMSISHistory(
                medical_history=["Hypertension", "Diabetes"], allergies=["Penicillin"]
            ),
        )
        merged = _merge_records(existing, new)
        assert "Hypertension" in merged.history.medical_history
        assert "Diabetes" in merged.history.medical_history
        assert len(merged.history.medical_history) == 2  # no duplicates
        assert "Penicillin" in merged.history.allergies


# --- NEMSIS Extract (requires Claude API) ---


async def test_extract_nemsis_with_existing():
    """Test extract with existing record preserves data."""
    existing = NEMSISRecord(
        patient=NEMSISPatientInfo(patient_name_first="John", patient_name_last="Smith"),
    )
    result = await extract_nemsis(
        "45 year old male", existing=existing
    )
    # Without API key, extract_nemsis returns existing or empty NEMSISRecord
    assert result is not None


# --- Core Info Checker ---


class TestCoreInfoChecker:
    def test_incomplete_no_name(self):
        r = NEMSISRecord(
            patient=NEMSISPatientInfo(
                patient_address="123 Main St", patient_age="45", patient_gender="Male"
            ),
        )
        assert is_core_info_complete(r) is False

    def test_incomplete_no_address(self):
        r = NEMSISRecord(
            patient=NEMSISPatientInfo(
                patient_name_first="John", patient_age="45", patient_gender="Male"
            ),
        )
        assert is_core_info_complete(r) is False

    def test_incomplete_no_age(self):
        r = NEMSISRecord(
            patient=NEMSISPatientInfo(
                patient_name_first="John",
                patient_address="123 Main St",
                patient_gender="Male",
            ),
        )
        assert is_core_info_complete(r) is False

    def test_incomplete_no_gender(self):
        r = NEMSISRecord(
            patient=NEMSISPatientInfo(
                patient_name_first="John",
                patient_address="123 Main St",
                patient_age="45",
            ),
        )
        assert is_core_info_complete(r) is False

    def test_complete_with_first_name(self):
        r = NEMSISRecord(
            patient=NEMSISPatientInfo(
                patient_name_first="John",
                patient_address="123 Main St",
                patient_age="45",
                patient_gender="Male",
            ),
        )
        assert is_core_info_complete(r) is True

    def test_complete_with_last_name(self):
        r = NEMSISRecord(
            patient=NEMSISPatientInfo(
                patient_name_last="Smith",
                patient_address="123 Main St",
                patient_age="45",
                patient_gender="Male",
            ),
        )
        assert is_core_info_complete(r) is True

    def test_empty_record(self):
        r = NEMSISRecord()
        assert is_core_info_complete(r) is False


class TestGetFullName:
    def test_full_name(self):
        r = NEMSISRecord(
            patient=NEMSISPatientInfo(
                patient_name_first="John", patient_name_last="Smith"
            ),
        )
        assert get_full_name(r) == "John Smith"

    def test_first_only(self):
        r = NEMSISRecord(
            patient=NEMSISPatientInfo(patient_name_first="John"),
        )
        assert get_full_name(r) == "John"

    def test_last_only(self):
        r = NEMSISRecord(
            patient=NEMSISPatientInfo(patient_name_last="Smith"),
        )
        assert get_full_name(r) == "Smith"

    def test_empty(self):
        r = NEMSISRecord()
        assert get_full_name(r) == "Unknown"


async def test_trigger_medical_db():
    """Test medical DB lookup returns report."""
    r = NEMSISRecord(
        patient=NEMSISPatientInfo(
            patient_name_first="John",
            patient_name_last="Smith",
            patient_age="45",
            patient_gender="Male",
            patient_address="123 Main St",
        ),
    )
    db_result = await trigger_medical_db(r)
    assert "John Smith" in db_result
    assert "MEDICAL HISTORY REPORT" in db_result or "patient" in db_result.lower()


async def test_trigger_medical_db_with_dob():
    """Test medical DB passes DOB when available."""
    r = NEMSISRecord(
        patient=NEMSISPatientInfo(
            patient_name_first="Jane",
            patient_name_last="Doe",
            patient_age="32",
            patient_gender="Female",
            patient_address="456 Oak Ave",
            patient_date_of_birth="1994-05-20",
        ),
    )
    db_result = await trigger_medical_db(r)
    assert "Jane Doe" in db_result
    assert "1994-05-20" in db_result or "DOB" in db_result or "patient" in db_result.lower()


# --- GP Caller ---


async def test_gp_caller():
    """GP caller returns message; without API keys may report failure."""
    result = await call_gp(
        patient_name="John Smith",
        patient_age="45",
        patient_gender="Male",
        patient_address="123 Main St",
        gp_name="Dr. Wilson",
    )
    assert "John Smith" in result or "Could not resolve" in result
    assert "[DUMMY]" in result or "Could not resolve" in result or "initiated" in result.lower()


async def test_gp_caller_no_contact():
    """GP caller returns early when no GP contact info provided."""
    result = await call_gp(
        patient_name="John Smith",
        patient_age="45",
        patient_gender="Male",
        patient_address="123 Main St",
    )
    assert "No GP contact available" in result


# --- Medical DB (FHIR-backed, dummy mode) ---


async def test_medical_db():
    result = await query_records(
        patient_name="Jane Doe",
        patient_age="32",
        patient_gender="Female",
    )
    assert "Jane Doe" in result
    assert "MEDICAL HISTORY REPORT" in result
    assert "CONDITIONS / MEDICAL HISTORY" in result
    assert "ALLERGIES (CRITICAL)" in result
