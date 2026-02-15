"""Tests for voice agent service — ElevenLabs + Twilio outbound calls."""

from app.services.voice_agent import place_gp_call


# --- Place GP Call (no ElevenLabs key in tests) ---


async def test_place_gp_call_no_api_key():
    """Without ELEVENLABS_API_KEY, place_gp_call returns error status."""
    result = await place_gp_call(
        phone_number="+1-555-0123",
        patient_name="John Smith",
        patient_dob="1980-01-15",
        hospital_callback="+1-555-0100",
        case_id="test-case-001",
    )
    assert result["status"] == "error"
    assert result["call_sid"] is None


async def test_place_gp_call_no_api_key_no_dob():
    """Without API key and no DOB, returns error gracefully."""
    result = await place_gp_call(
        phone_number="+1-555-0123",
        patient_name="Jane Doe",
        patient_dob=None,
        case_id="test-case-002",
    )
    assert result["status"] == "error"
