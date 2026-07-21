import pytest

from src.finance.email_pipeline import _detect_institution_by_sender, parse_email_body


class TestDetectInstitutionBySender:
    """Tests for the sender-domain detection helper."""

    @pytest.mark.parametrize(
        ("from_email", "expected"),
        [
            ("alerts@cibc.com", "CIBC"),
            ("noreply@alerts.rbc.com", "RBC"),
            ("alerts@mbna.ca", "MBNA"),
            ("noreply@pcfinancial.ca", "PC Financial"),
        ],
    )
    def test_known_domains(self, from_email: str, expected: str) -> None:
        assert _detect_institution_by_sender(from_email) == expected

    def test_interac_returns_none(self):
        """Interac domain is ambiguous (RBC, Simplii, etc.) — should fall through."""
        assert _detect_institution_by_sender("notify@payments.interac.ca") is None

    def test_unknown_domain_returns_none(self):
        assert _detect_institution_by_sender("user@gmail.com") is None

    def test_empty_string_returns_none(self):
        assert _detect_institution_by_sender("") is None

    def test_none_returns_none(self):
        assert _detect_institution_by_sender(None) is None

    def test_case_insensitive(self):
        assert _detect_institution_by_sender("Alerts@CIBC.COM") == "CIBC"


class TestParseEmailBodySenderRouting:
    """Tests that parse_email_body uses sender domain when available."""

    def test_sender_domain_routes_to_cibc(self):
        """CIBC sender domain should route to CIBC parser even without CIBC in body."""
        body = (
            "Dear Carlos,\n"
            "      You've recently made a purchase with your "
            "credit card ending in 2210 for $50.00 at Tim Hortons.\n"
            "You can sign on to your Online or Mobile Banking "
            "to view more details about this transaction."
            "Sincerely,\nYour Bank"
        )
        email_details = {"from_email": "alerts@cibc.com"}
        result = parse_email_body(body, email_details)
        assert result.get("institution") == "CIBC"

    def test_sender_domain_takes_priority_over_body_text(self):
        """When sender is CIBC but body mentions RBC, sender should win."""
        body = (
            "Dear Carlos,\n"
            "      You've recently made a purchase with your CIBC Costco World "
            "Mastercard ending in 2210 for $75.00 at RBC Insurance.\n"
            "You can sign on to your CIBC Online or Mobile Banking to view more "
            "details about this transaction.Sincerely,\nCIBC"
        )
        email_details = {"from_email": "alerts@cibc.com"}
        result = parse_email_body(body, email_details)
        assert result.get("institution") == "CIBC"

    def test_interac_sender_falls_back_to_body_rbc(self):
        """Interac sender should fall through to body-text detection for RBC."""
        body = (
            "Hi Robert,\n\n"
            "The $100.00 (CAD) you sent to JANE DOE has been "
            "successfully deposited.\n\n"
            "Reference Number: X1Y2Z3\n\n"
            "This email was sent to you by Interac Corp., on behalf of RBC Royal Bank."
        )
        email_details = {"from_email": "notify@payments.interac.ca"}
        result = parse_email_body(body, email_details)
        assert result.get("institution") == "RBC"

    def test_interac_sender_falls_back_to_body_simplii(self):
        """Interac sender should fall through to body-text detection for Simplii."""
        body = (
            "Hi Jennifer,\n\n"
            "The $50.00 (CAD) you sent to ALEX SMITH has been "
            "successfully deposited.\n\n"
            "Reference Number: A1B2C3\n\n"
            "This email was sent to you by Interac Corp., "
            "on behalf of Simplii Financial."
        )
        email_details = {"from_email": "notify@payments.interac.ca"}
        result = parse_email_body(body, email_details)
        assert result.get("institution") == "Simplii"

    def test_empty_from_email_falls_back_to_body_text(self):
        """Empty from_email (e.g. tests, notebooks) should use body-text matching."""
        body = (
            "MBNA Alert\n\n"
            "A purchase of $25.00 from Coffee Shop was made on your MBNA Mastercard "
            "card ending in 5678.\n"
        )
        result = parse_email_body(body, {})
        assert result.get("institution") == "MBNA"

    def test_missing_from_email_key_falls_back_to_body_text(self):
        """email_details without from_email key should use body-text matching."""
        body = (
            "Hi [CARDHOLDER_NAME],\n\n"
            "A purchase of $10.00 was made on your PC ® Mastercard ® card.\n\n"
            "The PC Financial ® team"
        )
        result = parse_email_body(body, {"subject": "Transaction Alert"})
        assert result.get("institution") == "PC Financial"
