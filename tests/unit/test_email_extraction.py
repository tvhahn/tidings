"""Tests for timezone conversion and user-mapping edge cases.

Covers extract_basic_details() timezone handling and
get_user_id() / load_user_mappings().
"""

from email.message import EmailMessage
from unittest.mock import patch

from src.finance.email_parser import extract_basic_details
from src.finance.user_mapping import get_user_id, load_user_mappings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_email(
    from_addr: str = "alerts@rbc.com",
    to_addr: str = "user@example.com",
    subject: str = "Test",
    date: str | None = None,
    forwarded_to: str | None = None,
) -> EmailMessage:
    """Build a minimal EmailMessage for testing extract_basic_details."""
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    if date:
        msg["Date"] = date
    if forwarded_to:
        msg["X-Forwarded-To"] = forwarded_to
    return msg


# ---------------------------------------------------------------------------
# Timezone conversion tests
# ---------------------------------------------------------------------------


class TestTimezoneConversion:
    """extract_basic_details() should normalize all dates to Pacific Time."""

    def test_utc_date_converts_to_pacific(self):
        """UTC date should convert to PST/PDT."""
        msg = _build_email(date="Tue, 15 Jan 2026 20:30:00 +0000")
        result = extract_basic_details(msg)
        # UTC 20:30 in January (PST = UTC-8) → 12:30 PST
        assert result["date"] == "01/15/2026 12:30 PST"

    def test_est_date_converts_to_pacific(self):
        """EST (-0500) date should convert to PST."""
        msg = _build_email(date="Wed, 15 Jan 2026 15:30:00 -0500")
        result = extract_basic_details(msg)
        # EST 15:30 → PST 12:30
        assert result["date"] == "01/15/2026 12:30 PST"

    def test_pdt_summer_date_stays_pacific(self):
        """PDT date during summer should remain Pacific (PDT)."""
        msg = _build_email(date="Mon, 15 Jun 2026 14:30:00 -0700")
        result = extract_basic_details(msg)
        assert result["date"] == "06/15/2026 14:30 PDT"

    def test_missing_date_returns_none(self):
        """When no Date header is present, date should be None."""
        msg = _build_email(date=None)
        result = extract_basic_details(msg)
        assert result["date"] is None

    def test_unparseable_date_returns_none(self):
        """When the date string is garbage, date should be None."""
        msg = _build_email(date="not-a-date")
        result = extract_basic_details(msg)
        assert result["date"] is None


# ---------------------------------------------------------------------------
# User-mapping / forwarded-to tests
# ---------------------------------------------------------------------------


class TestUserMapping:
    """get_user_id() and load_user_mappings() edge cases."""

    def test_cache_hit(self):
        """Known forwarded_to address returns the correct UserId."""
        # load_user_mappings populates the cache from the CSV
        load_user_mappings()
        result = get_user_id("demo@example.com")
        assert result == "default"

    def test_cache_miss_returns_none(self):
        """Unknown forwarded_to address returns None."""
        load_user_mappings()
        result = get_user_id("unknown@example.com")
        assert result is None

    def test_empty_cache_returns_none(self):
        """Before loading, get_user_id returns None."""
        # conftest autouse fixture clears the cache before each test
        result = get_user_id("unknown@example.com")
        assert result is None

    def test_missing_csv_does_not_raise(self):
        """Missing CSV logs error but doesn't raise."""
        with patch("builtins.open", side_effect=FileNotFoundError("no file")):
            load_user_mappings()  # should not raise
        # Cache should remain empty
        assert get_user_id("anything") is None


class TestForwardedToExtraction:
    """extract_basic_details() should use X-Forwarded-To when available."""

    def test_uses_x_forwarded_to_header(self):
        msg = _build_email(
            to_addr="to@example.com",
            forwarded_to="forwarded@example.com",
        )
        result = extract_basic_details(msg)
        assert result["forwarded_to"] == "forwarded@example.com"

    def test_falls_back_to_to_header(self):
        msg = _build_email(to_addr="to@example.com")
        result = extract_basic_details(msg)
        assert result["forwarded_to"] == "to@example.com"

    def test_multi_address_forwarded_to_prefers_known_csv_address(self):
        """When Gmail joins multiple forwards, pick the one in user_mappings.csv."""
        load_user_mappings()
        msg = _build_email(
            to_addr="to@example.com",
            forwarded_to="unknown@example.com, demo@example.com",
        )
        result = extract_basic_details(msg)
        assert result["forwarded_to"] == "demo@example.com"

    def test_multi_address_forwarded_to_falls_back_to_first(self):
        """If no address matches the CSV, use the first parsed address."""
        load_user_mappings()
        msg = _build_email(
            to_addr="to@example.com",
            forwarded_to="first@example.com, second@example.com",
        )
        result = extract_basic_details(msg)
        assert result["forwarded_to"] == "first@example.com"

    def test_multi_address_to_header_is_split(self):
        """A comma-joined To header (no X-Forwarded-To) is split like X-Forwarded-To."""
        load_user_mappings()
        msg = _build_email(to_addr="unknown@example.com, demo@example.com")
        result = extract_basic_details(msg)
        assert result["forwarded_to"] == "demo@example.com"
