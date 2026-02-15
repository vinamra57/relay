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


# --- Lookup without API key ---


async def test_lookup_no_api_key_returns_none():
    """Without PERPLEXITY_API_KEY, lookup returns None."""
    result = await lookup_gp_phone(
        gp_name="Dr. Wilson",
        location="Springfield",
        practice_name="Greenfield Medical Center",
    )
    assert result is None
