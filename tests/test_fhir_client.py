"""Tests for FHIR R4 client service - parsing and queries."""

from app.services.fhir_client import (
    _extract_display,
    _extract_entries,
    _get_patient_name,
    _split_name,
    parse_allergies,
    parse_conditions,
    parse_immunizations,
    parse_medications,
    parse_procedures_list,
    query_fhir_servers,
)

# --- Helper Functions ---


class TestExtractDisplay:
    def test_with_display(self):
        cc = {"coding": [{"system": "http://snomed.info/sct", "display": "Hypertension"}]}
        assert _extract_display(cc) == "Hypertension"

    def test_with_text_fallback(self):
        cc = {"text": "High blood pressure"}
        assert _extract_display(cc) == "High blood pressure"

    def test_with_multiple_codings(self):
        cc = {
            "coding": [
                {"system": "http://icd10", "code": "I10"},
                {"system": "http://snomed.info/sct", "display": "Essential hypertension"},
            ]
        }
        assert _extract_display(cc) == "Essential hypertension"

    def test_empty_codeable_concept(self):
        assert _extract_display({}) == "Unknown"

    def test_none_input(self):
        assert _extract_display(None) == "Unknown"

    def test_coding_without_display(self):
        cc = {"coding": [{"system": "http://snomed.info/sct", "code": "12345"}]}
        assert _extract_display(cc) == "Unknown"


class TestExtractEntries:
    def test_valid_bundle(self):
        bundle = {
            "resourceType": "Bundle",
            "type": "searchset",
            "entry": [
                {"resource": {"resourceType": "Patient", "id": "1"}},
                {"resource": {"resourceType": "Patient", "id": "2"}},
            ],
        }
        entries = _extract_entries(bundle)
        assert len(entries) == 2
        assert entries[0]["id"] == "1"
        assert entries[1]["id"] == "2"

    def test_empty_bundle(self):
        bundle = {"resourceType": "Bundle", "type": "searchset", "entry": []}
        assert _extract_entries(bundle) == []

    def test_no_entries(self):
        bundle = {"resourceType": "Bundle", "type": "searchset"}
        assert _extract_entries(bundle) == []

    def test_not_a_bundle(self):
        assert _extract_entries({"resourceType": "Patient"}) == []

    def test_none_input(self):
        assert _extract_entries(None) == []

    def test_entry_without_resource(self):
        bundle = {
            "resourceType": "Bundle",
            "type": "searchset",
            "entry": [
                {"fullUrl": "http://example.com/Patient/1"},
                {"resource": {"resourceType": "Patient", "id": "2"}},
            ],
        }
        entries = _extract_entries(bundle)
        assert len(entries) == 1
        assert entries[0]["id"] == "2"


class TestSplitName:
    def test_full_name(self):
        assert _split_name("John Smith") == ("John", "Smith")

    def test_single_name(self):
        assert _split_name("Madonna") == (None, "Madonna")

    def test_three_part_name(self):
        assert _split_name("Mary Jane Watson") == ("Mary Jane", "Watson")

    def test_empty_string(self):
        assert _split_name("") == (None, None)

    def test_whitespace_only(self):
        assert _split_name("   ") == (None, None)

    def test_extra_whitespace(self):
        given, family = _split_name("  John   Smith  ")
        assert family == "Smith"
        assert "John" in given


class TestGetPatientName:
    def test_full_name(self):
        patient = {"name": [{"given": ["John", "David"], "family": "Smith"}]}
        assert _get_patient_name(patient) == "John David Smith"

    def test_given_only(self):
        patient = {"name": [{"given": ["John"]}]}
        assert _get_patient_name(patient) == "John"

    def test_family_only(self):
        patient = {"name": [{"family": "Smith"}]}
        assert _get_patient_name(patient) == "Smith"

    def test_text_fallback(self):
        patient = {"name": [{"text": "Dr. John Smith"}]}
        assert _get_patient_name(patient) == "Dr. John Smith"

    def test_no_name(self):
        patient = {"name": []}
        assert _get_patient_name(patient) == "Unknown"

    def test_no_name_key(self):
        patient = {"id": "123"}
        assert _get_patient_name(patient) == "Unknown"


# --- FHIR Resource Parsers ---


class TestParseConditions:
    def test_active_condition(self):
        conditions = [
            {
                "resourceType": "Condition",
                "code": {
                    "coding": [{"display": "Essential hypertension"}],
                },
                "clinicalStatus": {
                    "coding": [{"code": "active"}],
                },
            }
        ]
        result = parse_conditions(conditions)
        assert result == ["Essential hypertension"]

    def test_resolved_condition(self):
        conditions = [
            {
                "resourceType": "Condition",
                "code": {"coding": [{"display": "Pneumonia"}]},
                "clinicalStatus": {"coding": [{"code": "resolved"}]},
            }
        ]
        result = parse_conditions(conditions)
        assert result == ["Pneumonia (resolved)"]

    def test_multiple_conditions(self):
        conditions = [
            {
                "resourceType": "Condition",
                "code": {"coding": [{"display": "Hypertension"}]},
                "clinicalStatus": {"coding": [{"code": "active"}]},
            },
            {
                "resourceType": "Condition",
                "code": {"coding": [{"display": "Diabetes"}]},
                "clinicalStatus": {"coding": [{"code": "active"}]},
            },
        ]
        result = parse_conditions(conditions)
        assert len(result) == 2
        assert "Hypertension" in result
        assert "Diabetes" in result

    def test_deduplication(self):
        conditions = [
            {
                "resourceType": "Condition",
                "code": {"coding": [{"display": "Hypertension"}]},
                "clinicalStatus": {"coding": [{"code": "active"}]},
            },
            {
                "resourceType": "Condition",
                "code": {"coding": [{"display": "Hypertension"}]},
                "clinicalStatus": {"coding": [{"code": "active"}]},
            },
        ]
        result = parse_conditions(conditions)
        assert len(result) == 1

    def test_unknown_display_skipped(self):
        conditions = [
            {
                "resourceType": "Condition",
                "code": {"coding": [{"code": "12345"}]},
                "clinicalStatus": {"coding": [{"code": "active"}]},
            }
        ]
        result = parse_conditions(conditions)
        assert result == []

    def test_empty_list(self):
        assert parse_conditions([]) == []

    def test_non_condition_skipped(self):
        items = [{"resourceType": "Patient", "id": "1"}]
        assert parse_conditions(items) == []


class TestParseAllergies:
    def test_high_criticality(self):
        allergies = [
            {
                "resourceType": "AllergyIntolerance",
                "code": {"coding": [{"display": "Penicillin"}]},
                "criticality": "high",
            }
        ]
        result = parse_allergies(allergies)
        assert result == ["Penicillin [high]"]

    def test_low_criticality_no_label(self):
        allergies = [
            {
                "resourceType": "AllergyIntolerance",
                "code": {"coding": [{"display": "Peanuts"}]},
                "criticality": "low",
            }
        ]
        result = parse_allergies(allergies)
        assert result == ["Peanuts"]

    def test_no_criticality(self):
        allergies = [
            {
                "resourceType": "AllergyIntolerance",
                "code": {"coding": [{"display": "Latex"}]},
            }
        ]
        result = parse_allergies(allergies)
        assert result == ["Latex"]

    def test_multiple_allergies(self):
        allergies = [
            {
                "resourceType": "AllergyIntolerance",
                "code": {"coding": [{"display": "Penicillin"}]},
                "criticality": "high",
            },
            {
                "resourceType": "AllergyIntolerance",
                "code": {"coding": [{"display": "Sulfa"}]},
                "criticality": "unable-to-assess",
            },
        ]
        result = parse_allergies(allergies)
        assert len(result) == 2
        assert "Penicillin [high]" in result
        assert "Sulfa [unable-to-assess]" in result

    def test_empty_list(self):
        assert parse_allergies([]) == []

    def test_deduplication(self):
        allergies = [
            {
                "resourceType": "AllergyIntolerance",
                "code": {"coding": [{"display": "Penicillin"}]},
                "criticality": "high",
            },
            {
                "resourceType": "AllergyIntolerance",
                "code": {"coding": [{"display": "Penicillin"}]},
                "criticality": "high",
            },
        ]
        result = parse_allergies(allergies)
        assert len(result) == 1


class TestParseMedications:
    def test_active_medication(self):
        meds = [
            {
                "resourceType": "MedicationRequest",
                "medicationCodeableConcept": {
                    "coding": [{"display": "Metformin 500mg"}],
                },
                "status": "active",
            }
        ]
        result = parse_medications(meds)
        assert result == ["Metformin 500mg"]

    def test_stopped_medication(self):
        meds = [
            {
                "resourceType": "MedicationRequest",
                "medicationCodeableConcept": {
                    "coding": [{"display": "Amoxicillin 250mg"}],
                },
                "status": "stopped",
            }
        ]
        result = parse_medications(meds)
        assert result == ["Amoxicillin 250mg (stopped)"]

    def test_multiple_medications(self):
        meds = [
            {
                "resourceType": "MedicationRequest",
                "medicationCodeableConcept": {"coding": [{"display": "Metformin 500mg"}]},
                "status": "active",
            },
            {
                "resourceType": "MedicationRequest",
                "medicationCodeableConcept": {"coding": [{"display": "Lisinopril 10mg"}]},
                "status": "active",
            },
        ]
        result = parse_medications(meds)
        assert len(result) == 2

    def test_empty_list(self):
        assert parse_medications([]) == []


class TestParseImmunizations:
    def test_with_date(self):
        imms = [
            {
                "resourceType": "Immunization",
                "vaccineCode": {"coding": [{"display": "Influenza seasonal"}]},
                "occurrenceDateTime": "2025-09-15T10:00:00Z",
            }
        ]
        result = parse_immunizations(imms)
        assert result == ["Influenza seasonal (2025-09-15)"]

    def test_without_date(self):
        imms = [
            {
                "resourceType": "Immunization",
                "vaccineCode": {"coding": [{"display": "Tetanus"}]},
            }
        ]
        result = parse_immunizations(imms)
        assert result == ["Tetanus"]

    def test_empty_list(self):
        assert parse_immunizations([]) == []


class TestParseProcedures:
    def test_with_date(self):
        procs = [
            {
                "resourceType": "Procedure",
                "code": {"coding": [{"display": "Appendectomy"}]},
                "performedDateTime": "2024-03-10T14:00:00Z",
            }
        ]
        result = parse_procedures_list(procs)
        assert result == ["Appendectomy (2024-03-10)"]

    def test_with_period(self):
        procs = [
            {
                "resourceType": "Procedure",
                "code": {"coding": [{"display": "Physical therapy"}]},
                "performedPeriod": {"start": "2024-01-01", "end": "2024-03-01"},
            }
        ]
        result = parse_procedures_list(procs)
        assert result == ["Physical therapy (2024-01-01)"]

    def test_without_date(self):
        procs = [
            {
                "resourceType": "Procedure",
                "code": {"coding": [{"display": "Blood draw"}]},
            }
        ]
        result = parse_procedures_list(procs)
        assert result == ["Blood draw"]

    def test_empty_list(self):
        assert parse_procedures_list([]) == []


# --- Integration: query_fhir_servers (live FHIR server) ---


async def test_query_fhir_servers_known_patient():
    """query_fhir_servers returns structured data for a known FHIR patient."""
    result = await query_fhir_servers("John Smith", "male")
    assert result is not None
    assert "patient_name" in result
    assert "conditions" in result
    assert isinstance(result["conditions"], list)


async def test_query_fhir_servers_unknown_patient():
    """query_fhir_servers returns None for a patient not in any FHIR server."""
    result = await query_fhir_servers("Zxywqp McFakerson", "male", "2099-01-01")
    assert result is None


async def test_query_fhir_servers_result_structure():
    """Verify the full structure of a FHIR query result."""
    result = await query_fhir_servers("John Smith", "male")
    if result is None:
        return  # FHIR server may be unavailable
    expected_keys = {
        "source", "fhir_patient_id", "patient_name", "patient_dob",
        "patient_gender", "conditions", "allergies", "medications",
        "immunizations", "procedures",
    }
    assert set(result.keys()) == expected_keys
