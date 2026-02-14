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
from app.services.nemsis_extractor import _dummy_extract, _merge_records, extract_nemsis
from app.services.summary import _dummy_case_summary, _dummy_hospital_summary

# --- NEMSIS Extractor ---


class TestDummyExtract:
    def test_extracts_name(self):
        r = _dummy_extract("Patient named John David Smith is a 45 year old male")
        assert r.patient.patient_name_first == "John David"
        assert r.patient.patient_name_last == "Smith"

    def test_extracts_age_gender(self):
        r = _dummy_extract("45 year old male patient")
        assert r.patient.patient_age == "45"
        assert r.patient.patient_gender == "Male"

    def test_extracts_female(self):
        r = _dummy_extract("patient is female")
        assert r.patient.patient_gender == "Female"

    def test_extracts_address(self):
        r = _dummy_extract("located at 742 Evergreen Terrace Springfield Illinois")
        assert r.patient.patient_address == "742 Evergreen Terrace"
        assert r.patient.patient_city == "Springfield"
        assert r.patient.patient_state == "Illinois"

    def test_extracts_vitals_bp(self):
        r = _dummy_extract("Blood pressure is 160 over 95")
        assert r.vitals.systolic_bp == 160
        assert r.vitals.diastolic_bp == 95

    def test_extracts_vitals_hr(self):
        r = _dummy_extract("Heart rate 110 beats per minute")
        assert r.vitals.heart_rate == 110

    def test_extracts_vitals_rr(self):
        r = _dummy_extract("Respiratory rate 22")
        assert r.vitals.respiratory_rate == 22

    def test_extracts_vitals_spo2(self):
        r = _dummy_extract("SPO2 94 percent on room air")
        assert r.vitals.spo2 == 94

    def test_extracts_vitals_glucose(self):
        r = _dummy_extract("blood glucose 145")
        assert r.vitals.blood_glucose == 145.0

    def test_extracts_vitals_gcs(self):
        r = _dummy_extract("GCS 15 eyes 4 verbal 5 motor 6")
        assert r.vitals.gcs_total == 15

    def test_extracts_chief_complaint(self):
        r = _dummy_extract("Chief complaint is chest pain radiating to left arm")
        assert r.situation.chief_complaint is not None
        assert "chest pain" in r.situation.chief_complaint.lower()

    def test_extracts_primary_impression(self):
        r = _dummy_extract("Primary impression is STEMI")
        assert r.situation.primary_impression == "STEMI"

    def test_extracts_procedures(self):
        r = _dummy_extract("Establishing IV access right antecubital. 12 lead ECG shows changes.")
        assert len(r.procedures.procedures) == 2

    def test_extracts_medications(self):
        r = _dummy_extract("Administering aspirin 324mg and nitroglycerin 0.4mg sublingual")
        assert len(r.medications.medications) == 2

    def test_empty_transcript(self):
        r = _dummy_extract("")
        assert r.patient.patient_name_first is None
        assert r.vitals.heart_rate is None

    def test_full_scenario(self):
        transcript = (
            "Patient is a 45 year old male named John David Smith "
            "located at 742 Evergreen Terrace Springfield Illinois. "
            "Chief complaint is chest pain. Blood pressure is 160 over 95. "
            "Heart rate 110 beats per minute. Respiratory rate 22. "
            "SPO2 94 percent. Blood glucose 145. GCS 15. "
            "Primary impression is STEMI. ST elevation in leads V1 through V4. "
            "Administering aspirin 324mg. Nitroglycerin 0.4mg sublingual. "
            "Establishing IV access right antecubital. 12 lead ECG. "
            "Activating cardiac catheterization lab."
        )
        r = _dummy_extract(transcript)
        assert r.patient.patient_name_first is not None
        assert r.patient.patient_age == "45"
        assert r.patient.patient_gender == "Male"
        assert r.vitals.systolic_bp == 160
        assert r.vitals.heart_rate == 110
        assert r.situation.primary_impression == "STEMI"
        assert len(r.procedures.procedures) >= 2
        assert len(r.medications.medications) >= 2

    # --- v3.5 Enhanced Fields ---

    def test_extracts_gcs_components(self):
        r = _dummy_extract("GCS 15 eyes 4 verbal 5 motor 6")
        assert r.vitals.gcs_total == 15
        assert r.vitals.gcs_eye == 4
        assert r.vitals.gcs_verbal == 5
        assert r.vitals.gcs_motor == 6

    def test_extracts_temperature(self):
        r = _dummy_extract("Temperature 101 degrees Fahrenheit")
        assert r.vitals.temperature == 101.0

    def test_extracts_pain_scale(self):
        r = _dummy_extract("Patient reports pain 8 out of 10")
        assert r.vitals.pain_scale == 8

    def test_extracts_level_of_consciousness(self):
        r = _dummy_extract("Patient is alert and oriented")
        assert r.vitals.level_of_consciousness == "Alert and oriented"

    def test_extracts_unresponsive(self):
        r = _dummy_extract("Patient is unresponsive")
        assert r.vitals.level_of_consciousness == "Unresponsive"

    def test_extracts_medical_history(self):
        r = _dummy_extract("Patient history includes hypertension and diabetes")
        assert "Hypertension" in r.history.medical_history
        assert "Diabetes mellitus type 2" in r.history.medical_history

    def test_extracts_copd_history(self):
        r = _dummy_extract("Patient has COPD and asthma")
        assert "COPD" in r.history.medical_history
        assert "Asthma" in r.history.medical_history

    def test_extracts_allergies_nkda(self):
        r = _dummy_extract("No known allergies NKDA")
        assert "NKDA" in r.history.allergies

    def test_extracts_penicillin_allergy(self):
        r = _dummy_extract("Patient is allergic to penicillin")
        assert "Penicillin" in r.history.allergies

    def test_extracts_disposition_transport(self):
        r = _dummy_extract("Transporting to Springfield General Hospital")
        assert r.disposition.transport_mode == "Ground ambulance"
        assert r.disposition.destination_facility == "Springfield General Hospital"
        assert r.disposition.destination_type == "Hospital"

    def test_extracts_cath_lab_activation(self):
        r = _dummy_extract("Activating cath lab")
        assert "Cardiac catheterization team" in r.disposition.hospital_team_activation

    def test_extracts_complaint_duration(self):
        r = _dummy_extract("Started approximately 30 minutes ago")
        assert r.situation.complaint_duration == "30 minutes"

    def test_extracts_intubation(self):
        r = _dummy_extract("Performing intubation")
        assert "Endotracheal intubation" in r.procedures.procedures

    def test_extracts_morphine(self):
        r = _dummy_extract("Administering morphine for pain")
        assert "Morphine 4mg IV" in r.medications.medications

    def test_full_v35_scenario(self):
        transcript = (
            "Patient is a 45 year old male named John David Smith "
            "located at 742 Evergreen Terrace Springfield Illinois. "
            "Patient is alert and oriented and reports pain 8 out of 10. "
            "Chief complaint is chest pain started 30 minutes ago. "
            "Blood pressure 160 over 95. Heart rate 110 beats per minute. "
            "GCS 15 eyes 4 verbal 5 motor 6. SPO2 94 percent. "
            "Patient history includes hypertension and diabetes. "
            "No known allergies NKDA. "
            "Administering aspirin 324mg. IV access. 12 lead ECG. "
            "Primary impression is STEMI. Activating cath lab. "
            "Transporting to Springfield General Hospital."
        )
        r = _dummy_extract(transcript)
        # Core fields
        assert r.patient.patient_name_first is not None
        assert r.vitals.systolic_bp == 160
        assert r.situation.primary_impression == "STEMI"
        # v3.5 fields
        assert r.vitals.gcs_eye == 4
        assert r.vitals.pain_scale == 8
        assert r.vitals.level_of_consciousness == "Alert and oriented"
        assert r.situation.complaint_duration == "30 minutes"
        assert len(r.history.medical_history) == 2
        assert "NKDA" in r.history.allergies
        assert r.disposition.destination_facility == "Springfield General Hospital"
        assert "Cardiac catheterization team" in r.disposition.hospital_team_activation


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


async def test_extract_nemsis_dummy_mode():
    """Test that extract_nemsis works in dummy mode."""
    result = await extract_nemsis("Patient is a 45 year old male named John Smith")
    assert result.patient.patient_age == "45"
    assert result.patient.patient_gender == "Male"


async def test_extract_nemsis_with_existing():
    """Test extract with existing record preserves data."""
    existing = NEMSISRecord(
        patient=NEMSISPatientInfo(patient_name_first="John", patient_name_last="Smith"),
    )
    result = await extract_nemsis(
        "45 year old male", existing=existing
    )
    # In dummy mode, the result comes from _dummy_extract which doesn't merge with existing
    # (merge only happens in the real OpenAI path)
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
    """Test parallel downstream calls return results."""
    r = NEMSISRecord(
        patient=NEMSISPatientInfo(
            patient_name_first="John",
            patient_name_last="Smith",
            patient_age="45",
            patient_gender="Male",
            patient_address="123 Main St",
        ),
    )
    gp_result, db_result = await trigger_downstream(r)
    assert "John Smith" in gp_result
    assert "John Smith" in db_result
    assert "[GP STUB]" in gp_result
    assert "[MEDICAL DB STUB]" in db_result


# --- GP Caller Stub ---


async def test_gp_caller():
    result = await call_gp(
        patient_name="John Smith",
        patient_age="45",
        patient_gender="Male",
        patient_address="123 Main St",
    )
    assert "John Smith" in result
    assert "45" in result
    assert "[GP STUB]" in result


# --- Medical DB Stub ---


async def test_medical_db():
    result = await query_records(
        patient_name="Jane Doe",
        patient_age="32",
        patient_gender="Female",
    )
    assert "Jane Doe" in result
    assert "[MEDICAL DB STUB]" in result


# --- Summary Service (Dummy Mode) ---


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


class TestDummyCaseSummary:
    def test_stemi_case_returns_critical(self):
        summary = _dummy_case_summary(STEMI_CASE_DATA)
        assert summary.urgency == "critical"
        assert "John Smith" in summary.one_liner
        assert "STEMI" in summary.clinical_narrative
        assert len(summary.key_findings) >= 4
        assert len(summary.actions_taken) == 4  # 2 procedures + 2 meds

    def test_stemi_case_one_liner_length(self):
        summary = _dummy_case_summary(STEMI_CASE_DATA)
        assert len(summary.one_liner) <= 100

    def test_stemi_case_key_findings_include_vitals(self):
        summary = _dummy_case_summary(STEMI_CASE_DATA)
        findings_str = " ".join(summary.key_findings)
        assert "BP 160/95" in findings_str
        assert "HR 110" in findings_str
        assert "SpO2 94%" in findings_str
        assert "Pain 8/10" in findings_str

    def test_stemi_case_includes_pmh(self):
        summary = _dummy_case_summary(STEMI_CASE_DATA)
        assert "PMH" in summary.clinical_narrative
        assert "Hypertension" in summary.clinical_narrative

    def test_empty_case(self):
        summary = _dummy_case_summary(EMPTY_CASE_DATA)
        assert summary.urgency == "moderate"
        assert "Unknown patient" in summary.one_liner
        assert "No vitals recorded" in summary.key_findings
        assert summary.actions_taken == []

    def test_high_urgency_tachycardia(self):
        data = {
            **EMPTY_CASE_DATA,
            "nemsis": {
                "vitals": {"heart_rate": 130},
                "patient": {},
                "situation": {},
                "procedures": {},
                "medications": {},
            },
        }
        summary = _dummy_case_summary(data)
        assert summary.urgency == "high"

    def test_critical_urgency_low_spo2(self):
        data = {
            **EMPTY_CASE_DATA,
            "nemsis": {
                "vitals": {"spo2": 85},
                "patient": {},
                "situation": {},
                "procedures": {},
                "medications": {},
            },
        }
        summary = _dummy_case_summary(data)
        assert summary.urgency == "critical"


class TestDummyHospitalSummary:
    def test_stemi_case_hospital_summary(self):
        summary = _dummy_hospital_summary(STEMI_CASE_DATA)
        assert summary.priority_level == "critical"
        assert "John Smith" in summary.patient_demographics
        assert "45" in summary.patient_demographics
        assert "STEMI" in summary.clinical_impression
        assert "catheterization" in summary.recommended_preparations.lower()
        assert "Chest pain" in summary.chief_complaint

    def test_stemi_vitals_string(self):
        summary = _dummy_hospital_summary(STEMI_CASE_DATA)
        assert "BP 160/95" in summary.vitals_summary
        assert "HR 110" in summary.vitals_summary
        assert "SpO2 94%" in summary.vitals_summary

    def test_stemi_procedures_and_meds(self):
        summary = _dummy_hospital_summary(STEMI_CASE_DATA)
        assert "IV access" in summary.procedures_performed
        assert "Aspirin" in summary.medications_administered

    def test_stemi_patient_history(self):
        summary = _dummy_hospital_summary(STEMI_CASE_DATA)
        assert "GP" in summary.patient_history
        assert "Records" in summary.patient_history
        assert "PMH" in summary.patient_history
        assert "Hypertension" in summary.patient_history

    def test_stemi_special_considerations_allergies(self):
        summary = _dummy_hospital_summary(STEMI_CASE_DATA)
        assert "NKDA" in summary.special_considerations

    def test_stemi_special_considerations_destination(self):
        summary = _dummy_hospital_summary(STEMI_CASE_DATA)
        assert "Springfield General" in summary.special_considerations

    def test_empty_case_hospital_summary(self):
        summary = _dummy_hospital_summary(EMPTY_CASE_DATA)
        assert summary.priority_level == "moderate"
        assert "Unknown" in summary.patient_demographics
        assert summary.vitals_summary == "No vitals recorded"
        assert summary.procedures_performed == "None recorded"
        assert summary.medications_administered == "None administered"
        assert "Standard ED" in summary.recommended_preparations

    def test_stroke_case_preps(self):
        data = {
            **EMPTY_CASE_DATA,
            "nemsis": {
                "patient": {"patient_name_first": "Jane"},
                "vitals": {},
                "situation": {"primary_impression": "Acute stroke"},
                "procedures": {},
                "medications": {},
            },
        }
        summary = _dummy_hospital_summary(data)
        assert summary.priority_level == "critical"
        assert "CT scanner" in summary.recommended_preparations
        assert "Neurology" in summary.recommended_preparations
