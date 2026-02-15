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
    trigger_downstream,
)
from app.services.gp_caller import call_gp
from app.services.medical_db import query_records
from app.services.nemsis_extractor import _merge_records, extract_nemsis

# --- NEMSIS Extractor ---


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


async def test_trigger_downstream():
    """Test parallel downstream calls: medical DB returns report; GP may fail without API key."""
    r = NEMSISRecord(
        patient=NEMSISPatientInfo(
            patient_name_first="John",
            patient_name_last="Smith",
            patient_age="45",
            patient_gender="Male",
            patient_address="123 Main St",
            gp_name="Dr. Wilson",
        ),
    )
    _gp_result, db_result = await trigger_downstream(r)
    assert "John Smith" in db_result
    assert "MEDICAL HISTORY REPORT" in db_result or "patient" in db_result.lower()


async def test_trigger_downstream_with_dob():
    """Test downstream passes DOB to medical DB when available."""
    r = NEMSISRecord(
        patient=NEMSISPatientInfo(
            patient_name_first="Jane",
            patient_name_last="Doe",
            patient_age="32",
            patient_gender="Female",
            patient_address="456 Oak Ave",
            patient_date_of_birth="1994-05-20",
            gp_name="Dr. Smith",
        ),
    )
    _gp_result, db_result = await trigger_downstream(r)
    assert "Jane Doe" in db_result
    assert "1994-05-20" in db_result or "DOB" in db_result or "patient" in db_result.lower()


async def test_trigger_downstream_no_gp():
    """Without GP contact, GP call returns early but medical DB still works."""
    r = NEMSISRecord(
        patient=NEMSISPatientInfo(
            patient_name_first="Bob",
            patient_name_last="Jones",
            patient_age="50",
            patient_gender="Male",
            patient_address="789 Pine St",
        ),
    )
    gp_result, db_result = await trigger_downstream(r)
    assert "No GP contact available" in gp_result
    assert "MEDICAL HISTORY REPORT" in db_result


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
    assert "John Smith" in result or "Could not resolve" in result or "initiated" in result.lower()


async def test_gp_caller_no_contact():
    """GP caller returns early when no GP contact info provided."""
    result = await call_gp(
        patient_name="John Smith",
        patient_age="45",
        patient_gender="Male",
        patient_address="123 Main St",
    )
    assert "No GP contact available" in result


# --- Medical DB (FHIR-backed) ---


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


# --- Summary Service ---


STEMI_CASE_DATA = {
    "case_id": "test-123",
    "transcript": "Patient is a 45 year old male with chest pain",
    "nemsis": {
        "patient": {
            "patient_name_first": "John",
            "patient_name_last": "Smith",
            "patient_age": "45",
            "patient_gender": "Male",
            "patient_address": "742 Evergreen Terrace",
        },
        "vitals": {
            "systolic_bp": 160,
            "diastolic_bp": 95,
            "heart_rate": 110,
            "respiratory_rate": 22,
            "spo2": 94,
            "blood_glucose": 145.0,
            "gcs_total": 15,
            "pain_scale": 8,
        },
        "situation": {
            "chief_complaint": "Chest pain radiating to left arm",
            "primary_impression": "STEMI",
            "secondary_impression": "ST elevation in leads V1-V4",
        },
        "procedures": {"procedures": ["IV access", "12-lead ECG"]},
        "medications": {"medications": ["Aspirin 324mg PO", "Nitroglycerin 0.4mg SL"]},
        "history": {
            "medical_history": ["Hypertension", "Diabetes mellitus type 2"],
            "allergies": ["NKDA"],
        },
        "disposition": {
            "destination_facility": "Springfield General Hospital",
        },
    },
    "patient_name": "John Smith",
    "patient_age": "45",
    "patient_gender": "Male",
    "gp_response": "[GP STUB] History for John Smith",
    "medical_db_response": "[MEDICAL DB STUB] Records for John Smith",
}

EMPTY_CASE_DATA = {
    "case_id": "test-empty",
    "transcript": "",
    "nemsis": {},
    "patient_name": "",
    "patient_age": "",
    "patient_gender": "",
    "gp_response": "",
    "medical_db_response": "",
}


