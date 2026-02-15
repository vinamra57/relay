"""Tests for GP caller orchestrator — integration tests without API keys."""

from app.services.gp_caller import call_gp

# --- Precondition Checks ---


async def test_call_gp_no_contact_returns_early():
    """call_gp returns early when no GP name or phone provided."""
    result = await call_gp(
        patient_name="John Smith",
        patient_age="45",
        patient_gender="Male",
        patient_address="742 Evergreen Terrace",
        gp_name=None,
        gp_phone=None,
    )
    assert "No GP contact available" in result


async def test_call_gp_no_name_no_phone():
    """Both gp_name and gp_phone are None — should not trigger call."""
    result = await call_gp(
        patient_name="Test Patient",
        patient_age="30",
        patient_gender="Female",
        patient_address="123 Main St",
    )
    assert "No GP contact available" in result


# --- GP Name Only (no Perplexity key in tests) ---


async def test_call_gp_with_name_no_api_key():
    """Without PERPLEXITY_API_KEY, GP lookup fails gracefully."""
    result = await call_gp(
        patient_name="John Smith",
        patient_age="45",
        patient_gender="Male",
        patient_address="742 Evergreen Terrace, Springfield",
        gp_name="Dr. Wilson",
        gp_practice_name="Greenfield Medical Center",
    )
    assert "Could not resolve" in result


# --- Confirmed GP Phone (no ElevenLabs key in tests) ---


async def test_call_gp_with_confirmed_phone():
    """With confirmed phone but no ElevenLabs key, call fails gracefully."""
    result = await call_gp(
        patient_name="Bob Williams",
        patient_age="60",
        patient_gender="Male",
        patient_address="789 Pine St",
        gp_phone="+1-555-9999",
    )
    # Without ElevenLabs key, place_gp_call returns error
    assert "failed" in result.lower() or "error" in result.lower()


async def test_call_gp_with_both_name_and_phone():
    """When both GP name and phone provided, phone takes precedence (skips lookup)."""
    result = await call_gp(
        patient_name="Test Patient",
        patient_age="40",
        patient_gender="Male",
        patient_address="100 Test St",
        gp_name="Dr. Test",
        gp_phone="+1-555-8888",
    )
    # Skips lookup, goes straight to call (which fails without ElevenLabs key)
    assert "Could not resolve" not in result
