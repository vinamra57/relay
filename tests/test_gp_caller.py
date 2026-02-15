"""Tests for GP caller orchestrator — dummy mode integration."""

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


# --- Dummy Mode with GP Name ---


async def test_call_gp_with_name_dummy_mode():
    """call_gp resolves phone via lookup in dummy mode and places call."""
    result = await call_gp(
        patient_name="John Smith",
        patient_age="45",
        patient_gender="Male",
        patient_address="742 Evergreen Terrace, Springfield",
        gp_name="Dr. Wilson",
        gp_practice_name="Greenfield Medical Center",
    )
    assert "[DUMMY]" in result
    assert "John Smith" in result


async def test_call_gp_with_name_contains_phone():
    """Dummy mode result mentions the resolved phone number."""
    result = await call_gp(
        patient_name="Jane Doe",
        patient_age="32",
        patient_gender="Female",
        patient_address="456 Oak Ave",
        gp_name="Dr. Smith",
    )
    assert "[DUMMY]" in result
    assert "+1-555-0123" in result


# --- Dummy Mode with Confirmed GP Phone ---


async def test_call_gp_with_confirmed_phone():
    """call_gp uses confirmed GP phone directly, skips lookup."""
    result = await call_gp(
        patient_name="Bob Williams",
        patient_age="60",
        patient_gender="Male",
        patient_address="789 Pine St",
        gp_phone="+1-555-9999",
    )
    assert "[DUMMY]" in result
    assert "+1-555-9999" in result


async def test_call_gp_with_both_name_and_phone():
    """When both GP name and phone provided, phone takes precedence."""
    result = await call_gp(
        patient_name="Test Patient",
        patient_age="40",
        patient_gender="Male",
        patient_address="100 Test St",
        gp_name="Dr. Test",
        gp_phone="+1-555-8888",
    )
    assert "+1-555-8888" in result


# --- With DOB ---


async def test_call_gp_with_dob():
    """call_gp passes DOB through to voice agent."""
    result = await call_gp(
        patient_name="John Smith",
        patient_age="45",
        patient_gender="Male",
        patient_address="742 Evergreen Terrace",
        gp_name="Dr. Wilson",
        patient_dob="1980-01-15",
    )
    assert "[DUMMY]" in result


# --- With Case ID ---


async def test_call_gp_with_case_id():
    """call_gp logs audit and updates case when case_id provided."""
    result = await call_gp(
        patient_name="John Smith",
        patient_age="45",
        patient_gender="Male",
        patient_address="742 Evergreen Terrace",
        gp_name="Dr. Wilson",
        case_id="test-case-gp-001",
    )
    assert "[DUMMY]" in result
