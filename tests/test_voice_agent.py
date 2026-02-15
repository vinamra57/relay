"""Tests for voice agent service — ElevenLabs + Twilio outbound calls."""

from app.services.voice_agent import _dummy_call, place_gp_call

# --- Dummy Call ---


class TestDummyCall:
    def test_returns_expected_keys(self):
        result = _dummy_call("John Smith", "case-123")
        assert "call_sid" in result
        assert "conversation_id" in result
        assert "status" in result
        assert "transcript" in result

    def test_status_is_dummy(self):
        result = _dummy_call("Jane Doe", "case-456")
        assert result["status"] == "dummy"

    def test_transcript_contains_patient_name(self):
        result = _dummy_call("Alice Johnson", "case-789")
        assert "Alice Johnson" in result["transcript"]

    def test_call_sid_contains_case_id(self):
        result = _dummy_call("Test", "case-abc")
        assert "case-abc" in result["call_sid"]

    def test_conversation_id_contains_case_id(self):
        result = _dummy_call("Test", "case-abc")
        assert "case-abc" in result["conversation_id"]

    def test_no_case_id(self):
        result = _dummy_call("Test", None)
        assert result["call_sid"] is not None
        assert result["status"] == "dummy"


# --- Place GP Call (dummy mode) ---


async def test_place_gp_call_dummy_mode():
    """In dummy mode, place_gp_call returns synthetic result without API call."""
    result = await place_gp_call(
        phone_number="+1-555-0123",
        patient_name="John Smith",
        patient_dob="1980-01-15",
        hospital_callback="+1-555-0100",
        case_id="test-case-001",
    )
    assert result["status"] == "dummy"
    assert "John Smith" in result["transcript"]
    assert result["call_sid"] is not None
    assert result["conversation_id"] is not None


async def test_place_gp_call_dummy_no_dob():
    """Dummy mode works without DOB."""
    result = await place_gp_call(
        phone_number="+1-555-0123",
        patient_name="Jane Doe",
        patient_dob=None,
        case_id="test-case-002",
    )
    assert result["status"] == "dummy"
    assert "Jane Doe" in result["transcript"]


async def test_place_gp_call_dummy_transcript_has_medical_info():
    """Dummy transcript includes clinical information."""
    result = await place_gp_call(
        phone_number="+1-555-0123",
        patient_name="Test Patient",
        patient_dob="1990-01-01",
        case_id="test-case-003",
    )
    transcript = result["transcript"]
    # Dummy transcript should mention medications or allergies
    assert "medication" in transcript.lower() or "allerg" in transcript.lower()
