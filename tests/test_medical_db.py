"""Tests for medical database service - report building and formatting."""

from app.models.medical_history import MedicalHistoryReport, PatientMedicalHistory
from app.services.medical_db import (
    build_medical_history_report,
    format_medical_history_report,
    query_records,
)

# --- Model Tests ---


class TestPatientMedicalHistory:
    def test_defaults(self):
        h = PatientMedicalHistory()
        assert h.source == ""
        assert h.fhir_patient_id == ""
        assert h.conditions == []
        assert h.allergies == []
        assert h.medications == []
        assert h.immunizations == []
        assert h.procedures == []
        assert h.patient_dob is None
        assert h.patient_gender is None

    def test_full_history(self):
        h = PatientMedicalHistory(
            source="https://hapi.fhir.org/baseR4",
            fhir_patient_id="12345",
            patient_name="John Smith",
            patient_dob="1980-01-15",
            patient_gender="male",
            conditions=["Hypertension", "Diabetes"],
            allergies=["Penicillin [high]"],
            medications=["Metformin 500mg"],
            immunizations=["Influenza (2025-09-15)"],
            procedures=["Colonoscopy (2024-03-15)"],
        )
        assert h.patient_name == "John Smith"
        assert len(h.conditions) == 2
        assert len(h.allergies) == 1
        assert len(h.medications) == 1

    def test_independent_list_defaults(self):
        h1 = PatientMedicalHistory()
        h2 = PatientMedicalHistory()
        h1.conditions.append("Test")
        assert len(h2.conditions) == 0


class TestMedicalHistoryReport:
    def test_not_found(self):
        r = MedicalHistoryReport(found=False, report_text="No records found.")
        assert r.found is False
        assert r.report_text == "No records found."
        assert r.history.conditions == []

    def test_found(self):
        r = MedicalHistoryReport(
            found=True,
            history=PatientMedicalHistory(conditions=["Hypertension"]),
            report_text="Report here",
        )
        assert r.found is True
        assert len(r.history.conditions) == 1

    def test_defaults(self):
        r = MedicalHistoryReport()
        assert r.found is False
        assert r.report_text == ""


# --- Report Formatting ---


class TestFormatMedicalHistoryReport:
    def test_full_report(self):
        history = PatientMedicalHistory(
            source="https://hapi.fhir.org/baseR4",
            patient_dob="1980-01-15",
            conditions=["Essential hypertension", "Diabetes mellitus type 2"],
            allergies=["Penicillin [high]", "Sulfonamide antibiotics"],
            medications=["Metformin 500mg", "Lisinopril 10mg"],
            immunizations=["Influenza seasonal (2025-09-15)"],
            procedures=["Colonoscopy (2024-03-15)"],
        )
        report = format_medical_history_report(history, "John Smith", "45")
        assert "MEDICAL HISTORY REPORT: John Smith (Age 45)" in report
        assert "DOB: 1980-01-15" in report
        assert "Essential hypertension" in report
        assert "Diabetes mellitus type 2" in report
        assert "Penicillin [high]" in report
        assert "Metformin 500mg" in report
        assert "Influenza seasonal" in report
        assert "Colonoscopy" in report
        assert "END OF REPORT" in report

    def test_empty_history(self):
        history = PatientMedicalHistory(source="dummy://test")
        report = format_medical_history_report(history, "Unknown", "0")
        assert "No conditions on record" in report
        assert "No known allergies on record" in report
        assert "No medications on record" in report
        assert "No immunization records found" in report
        assert "No procedures on record" in report

    def test_conditions_section_marker(self):
        history = PatientMedicalHistory(
            source="test",
            conditions=["Hypertension"],
        )
        report = format_medical_history_report(history, "Jane", "30")
        assert "--- CONDITIONS / MEDICAL HISTORY ---" in report
        assert "* Hypertension" in report

    def test_allergies_critical_section(self):
        history = PatientMedicalHistory(
            source="test",
            allergies=["Penicillin [high]"],
        )
        report = format_medical_history_report(history, "Jane", "30")
        assert "--- ALLERGIES (CRITICAL) ---" in report
        assert "!! Penicillin [high]" in report

    def test_medications_section(self):
        history = PatientMedicalHistory(
            source="test",
            medications=["Metformin 500mg"],
        )
        report = format_medical_history_report(history, "Jane", "30")
        assert "--- CURRENT MEDICATIONS ---" in report
        assert "- Metformin 500mg" in report

    def test_no_dob_omitted(self):
        history = PatientMedicalHistory(source="test")
        report = format_medical_history_report(history, "Jane", "30")
        assert "DOB:" not in report

    def test_source_included(self):
        history = PatientMedicalHistory(source="https://hapi.fhir.org/baseR4")
        report = format_medical_history_report(history, "Test", "40")
        assert "Source: https://hapi.fhir.org/baseR4" in report


# --- query_records integration (dummy mode) ---


async def test_query_records_returns_report_text():
    """query_records returns a formatted text report in dummy mode."""
    result = await query_records(
        patient_name="John Smith",
        patient_age="45",
        patient_gender="Male",
    )
    assert isinstance(result, str)
    assert "MEDICAL HISTORY REPORT" in result
    assert "John Smith" in result
    assert "CONDITIONS / MEDICAL HISTORY" in result
    assert "ALLERGIES (CRITICAL)" in result
    assert "CURRENT MEDICATIONS" in result


async def test_query_records_with_dob():
    """query_records passes DOB through to FHIR query."""
    result = await query_records(
        patient_name="Jane Doe",
        patient_age="32",
        patient_gender="Female",
        patient_dob="1994-05-20",
    )
    assert "Jane Doe" in result
    assert "DOB: 1994-05-20" in result


async def test_query_records_without_dob():
    """query_records works without DOB (uses default)."""
    result = await query_records(
        patient_name="Test Patient",
        patient_age="50",
        patient_gender="Male",
    )
    assert "Test Patient" in result
    assert "MEDICAL HISTORY REPORT" in result


# --- build_medical_history_report integration (dummy mode) ---


async def test_build_report_returns_structured():
    """build_medical_history_report returns a MedicalHistoryReport."""
    report = await build_medical_history_report(
        patient_name="John Smith",
        patient_age="45",
        patient_gender="Male",
    )
    assert isinstance(report, MedicalHistoryReport)
    assert report.found is True
    assert report.history.patient_name == "John Smith"
    assert len(report.history.conditions) > 0
    assert len(report.history.allergies) > 0
    assert "MEDICAL HISTORY REPORT" in report.report_text


async def test_build_report_conditions():
    """Verify conditions are populated in dummy mode report."""
    report = await build_medical_history_report(
        patient_name="Test Patient",
        patient_age="40",
        patient_gender="Female",
    )
    assert len(report.history.conditions) >= 3
    assert all(isinstance(c, str) for c in report.history.conditions)


async def test_build_report_allergies():
    """Verify allergies are populated."""
    report = await build_medical_history_report(
        patient_name="Test Patient",
        patient_age="40",
        patient_gender="Female",
    )
    assert len(report.history.allergies) >= 1
    assert all(isinstance(a, str) for a in report.history.allergies)


async def test_build_report_medications():
    """Verify medications are populated."""
    report = await build_medical_history_report(
        patient_name="Test Patient",
        patient_age="40",
        patient_gender="Female",
    )
    assert len(report.history.medications) >= 2
    assert all(isinstance(m, str) for m in report.history.medications)


async def test_build_report_immunizations():
    """Verify immunizations are populated."""
    report = await build_medical_history_report(
        patient_name="Test",
        patient_age="30",
        patient_gender="Male",
    )
    assert len(report.history.immunizations) >= 2
    assert all(isinstance(i, str) for i in report.history.immunizations)


async def test_build_report_procedures():
    """Verify procedures are populated."""
    report = await build_medical_history_report(
        patient_name="Test",
        patient_age="30",
        patient_gender="Male",
    )
    assert len(report.history.procedures) >= 2
    assert all(isinstance(p, str) for p in report.history.procedures)


async def test_build_report_with_dob():
    """Verify DOB is included in report when provided."""
    report = await build_medical_history_report(
        patient_name="Test",
        patient_age="30",
        patient_gender="Male",
        patient_dob="1996-01-01",
    )
    assert report.history.patient_dob == "1996-01-01"
    assert "DOB: 1996-01-01" in report.report_text


async def test_build_report_source():
    """Verify source is set in dummy mode."""
    report = await build_medical_history_report(
        patient_name="Test",
        patient_age="30",
        patient_gender="Male",
    )
    assert report.history.source == "dummy://synthetic-fhir-server"
