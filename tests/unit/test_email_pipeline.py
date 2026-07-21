"""Smoke tests for the full email parsing pipeline (parse_email end-to-end).

These tests call parse_email() with raw email bytes and a mocked OpenAI client,
exercising the complete extraction → detection → parsing → categorization flow
through email_pipeline.py.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.finance import app_config
from src.finance.email_pipeline import parse_email


@pytest.fixture(autouse=True)
def _enable_ai_categorization(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the privacy gate at categorizer.py:115 open so the mocked
    OpenAI client is reached. CI runs without OPENAI_API_KEY, so the
    auto-detected default is False and would short-circuit the pipeline
    to "Miscellaneous" before any test assertion can reach the mock.
    """
    monkeypatch.setattr(app_config, "_cache", {"ai_categorization_enabled": True})


def _build_raw_email(
    from_addr: str,
    to_addr: str,
    subject: str,
    body: str,
    x_forwarded_to: str | None = None,
) -> bytes:
    """Construct raw email bytes from parts."""
    headers = [
        f"From: {from_addr}",
        f"To: {to_addr}",
        f"Subject: {subject}",
        "Date: Mon, 21 Oct 2024 15:00:00 -0700",
        'Content-Type: text/plain; charset="utf-8"',
    ]
    if x_forwarded_to:
        headers.append(f"X-Forwarded-To: {x_forwarded_to}")
    return ("\r\n".join(headers) + "\r\n\r\n" + body).encode("utf-8")


def _mock_api_client(category: str = "Groceries") -> MagicMock:
    """Build a mock OpenAI client that returns a fixed category."""
    client = MagicMock()
    client.chat.return_value = MagicMock(
        choices=[
            MagicMock(
                message=MagicMock(
                    tool_calls=[
                        MagicMock(
                            function=MagicMock(
                                name="categorize_transaction",
                                arguments=f'{{"category": "{category}"}}',
                            )
                        )
                    ]
                )
            )
        ]
    )
    return client


class TestPipelineSmoke:
    """End-to-end smoke tests through parse_email()."""

    @patch("src.finance.email_parser.get_user_id", return_value="testuser")
    def test_cibc_purchase_pipeline(self, _mock_user_id: MagicMock) -> None:
        raw = _build_raw_email(
            from_addr="alerts@cibc.com",
            to_addr="user@example.com",
            subject="Transaction Alert",
            body=(
                "Dear Carlos,\n"
                "      You've recently made a purchase with your CIBC Costco World Mastercard "
                "ending in 2210 for $42.99 at LOBLAWS GROCERY.\n"
                "You can sign on to your CIBC Online or Mobile Banking to view more details "
                "about this transaction.Sincerely,\nCIBC"
            ),
            x_forwarded_to="user@example.com",
        )
        client = _mock_api_client("Groceries")
        result = parse_email(raw, file_name="emails/test.eml", api_client=client)

        assert result["institution"] == "CIBC"
        assert result["amount"] == 42.99
        assert result["company"] == "LOBLAWS GROCERY"
        assert result["transaction_type"] == "purchase"
        assert result["category"] == "Groceries"
        assert result.get("file_name") == "emails/test.eml"

    @patch("src.finance.email_parser.get_user_id", return_value="testuser")
    def test_rbc_purchase_pipeline(self, _mock_user_id: MagicMock) -> None:
        raw = _build_raw_email(
            from_addr="alerts@alerts.rbc.com",
            to_addr="user@example.com",
            subject="You made a purchase.",
            body=(
                "Hello,\n\n"
                "As requested, we're letting you know that a purchase of $87.50 was made on\n"
                "your RBC Royal Bank credit card account ************5678 on February 24, 2026\n"
                "towards Costco Wholesale.\n\n"
                "If you don't recognize this transaction, please call us at 1-800-769-2512\n"
                "(available 24/7) and we'll be happy to help.\n\n"
                "Thank you!"
            ),
            x_forwarded_to="user@example.com",
        )
        client = _mock_api_client("Groceries")
        result = parse_email(raw, file_name="emails/rbc_test.eml", api_client=client)

        assert result["institution"] == "RBC"
        assert result["amount"] == 87.50
        assert result["company"] == "Costco Wholesale"
        assert result["transaction_type"] == "purchase"
        assert result["name"] == "Demo User"

    @patch("src.finance.email_parser.get_user_id", return_value="testuser")
    def test_pipeline_without_api_client_skips_categorization(self, _mock_user_id: MagicMock) -> None:
        raw = _build_raw_email(
            from_addr="alerts@cibc.com",
            to_addr="user@example.com",
            subject="Transaction Alert",
            body=(
                "Dear Carlos,\n"
                "      You've recently made a purchase with your CIBC Costco World Mastercard "
                "ending in 2210 for $10.00 at SHOPPERS DRUG MART.\n"
                "You can sign on to your CIBC Online or Mobile Banking to view more details "
                "about this transaction.Sincerely,\nCIBC"
            ),
            x_forwarded_to="user@example.com",
        )
        result = parse_email(raw, file_name="emails/test.eml", api_client=None)

        assert result["institution"] == "CIBC"
        assert result["amount"] == 10.00
        assert "category" not in result

    @patch("src.finance.email_parser.get_user_id", return_value="testuser")
    def test_unrecognized_email_returns_basic_details(self, _mock_user_id: MagicMock) -> None:
        raw = _build_raw_email(
            from_addr="noreply@unknown.com",
            to_addr="user@example.com",
            subject="Welcome!",
            body="Thank you for signing up.",
            x_forwarded_to="user@example.com",
        )
        result = parse_email(raw, file_name="emails/unknown.eml")

        assert "institution" not in result
        assert result.get("file_name") == "emails/unknown.eml"
        assert result.get("body") == "Thank you for signing up."
