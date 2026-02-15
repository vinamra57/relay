"""Tests for GP lookup service — Perplexity Sonar API integration."""

from app.services.gp_lookup import _validate_phone, lookup_gp_phone

# --- Phone Validation ---


class TestValidatePhone:
    def test_valid_us_number(self):
        assert _validate_phone("+1-555-0123") == "+1-555-0123"

    def test_valid_digits_only(self):
        assert _validate_phone("5550123456") == "5550123456"

    def test_valid_e164(self):
        assert _validate_phone("+15550123456") == "+15550123456"

    def test_valid_formatted(self):
        assert _validate_phone("(555) 012-3456") == "(555) 012-3456"

    def test_too_short(self):
        assert _validate_phone("123") is None

    def test_empty(self):
        assert _validate_phone("") is None

    def test_none(self):
        assert _validate_phone(None) is None

    def test_no_digits(self):
        assert _validate_phone("not a number") is None


# --- Dummy Mode Lookup ---


async def test_lookup_dummy_mode_returns_result():
    """In dummy mode, lookup returns synthetic GP contact."""
    result = await lookup_gp_phone(
        gp_name="Dr. Wilson",
        location="Springfield",
        practice_name="Greenfield Medical Center",
    )
    assert result is not None
    assert "phone" in result
    assert "practice_name" in result
    assert "address" in result
    assert "source" in result
    assert result["source"] == "dummy://perplexity"


async def test_lookup_dummy_mode_with_practice_name():
    """Dummy mode includes practice name if provided."""
    result = await lookup_gp_phone(
        gp_name="Dr. Smith",
        location="Chicago",
        practice_name="Smith Family Practice",
    )
    assert result is not None
    assert result["practice_name"] == "Smith Family Practice"


async def test_lookup_dummy_mode_without_practice_name():
    """Dummy mode generates practice name from GP name."""
    result = await lookup_gp_phone(
        gp_name="Dr. Jones",
        location="New York",
    )
    assert result is not None
    assert "Dr. Jones" in result["practice_name"]


async def test_lookup_dummy_mode_phone_valid():
    """Dummy mode returns a validatable phone number."""
    result = await lookup_gp_phone(
        gp_name="Dr. Wilson",
        location="Springfield",
    )
    assert result is not None
    phone = _validate_phone(result["phone"])
    assert phone is not None
