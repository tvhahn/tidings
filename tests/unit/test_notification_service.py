"""Tests for src/finance/notification_service.py.

Covers:
- Blocked-companies filter and unknown-type skip (ported from test_lambda_sms)
- Message formatting parity with the former lambda send_sms() output
- Provider auto-selection (SNS / Ntfy / log-only)
- SnsProvider boto3 call parity with the old Lambda
- Fail-open behavior when a provider raises
- send_raw() bypasses filter and formatter
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from src.finance import notification_service
from src.finance.notification_service import (
    LogOnlyProvider,
    NtfyProvider,
    SnsProvider,
    _format_transaction_body,
    _ordinal,
    _select_provider_name,
    reset_provider_cache,
    send,
    send_raw,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


def _make_transaction(
    company: str = "Tim Hortons",
    amount: float = 5.50,
    date: str = "01/15/2026 14:30 PST",
    transaction_type: str = "purchase",
    institution: str = "CIBC",
    category: str = "Restaurant/Dining",
    name: str = "Carlos",
) -> dict[str, Any]:
    return {
        "company": company,
        "amount": amount,
        "date": date,
        "transaction_type": transaction_type,
        "institution": institution,
        "category": category,
        "name": name,
    }


@pytest.fixture
def captured_provider(monkeypatch: pytest.MonkeyPatch) -> Iterator[MagicMock]:
    """Install a mock provider that captures (title, body, tags) on send()."""
    reset_provider_cache()
    provider = MagicMock()
    provider.send = MagicMock(name="send")
    monkeypatch.setattr(notification_service, "_provider_cache", provider)
    yield provider
    reset_provider_cache()


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Ensure each test starts with no notification env vars set."""
    for key in [
        "NOTIFICATION_PROVIDER",
        "NOTIFICATION_URL",
        "SNS_TOPIC_ARN",
        "AWS_REGION",
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_FROM_NUMBER",
        "TWILIO_TO_NUMBER",
    ]:
        monkeypatch.delenv(key, raising=False)
    reset_provider_cache()
    yield
    reset_provider_cache()


# ---------------------------------------------------------------------------
# Blocked-companies filter (ported from test_lambda_sms.py)
# ---------------------------------------------------------------------------


class TestBlockedCompanies:
    @pytest.fixture(autouse=True)
    def _synthetic_blocklist(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The shipped seed is empty (`blocked_companies.json` → `[]`), so the
        filter semantics are exercised against a synthetic, non-identifying list
        rather than any real subscription data."""
        monkeypatch.setattr(
            notification_service,
            "get_blocked_companies",
            lambda: ["StreamCo", "NewsHound", "VPNProvider", "TestBlocked Co"],
        )

    @pytest.mark.parametrize(
        "company",
        [
            "StreamCo",
            "StreamCo Premium",
            "NewsHound",
            "VPNProvider",
            "TestBlocked Co",
        ],
    )
    def test_blocked_company_skips_send(self, captured_provider: MagicMock, company: str) -> None:
        send(_make_transaction(company=company))
        captured_provider.send.assert_not_called()

    def test_blocked_company_case_insensitive(self, captured_provider: MagicMock) -> None:
        send(_make_transaction(company="streamco premium"))
        captured_provider.send.assert_not_called()

    def test_blocked_company_partial_match(self, captured_provider: MagicMock) -> None:
        send(_make_transaction(company="NewsHound Digital Ltd"))
        captured_provider.send.assert_not_called()

    def test_normal_company_sends(self, captured_provider: MagicMock) -> None:
        send(_make_transaction(company="Tim Hortons"))
        captured_provider.send.assert_called_once()


class TestUnknownType:
    def test_unknown_type_skips_send(self, captured_provider: MagicMock) -> None:
        send(_make_transaction(transaction_type="Unknown"))
        captured_provider.send.assert_not_called()

    def test_none_type_skips_send(self, captured_provider: MagicMock) -> None:
        details = _make_transaction()
        details["transaction_type"] = None
        send(details)
        captured_provider.send.assert_not_called()

    def test_purchase_type_sends(self, captured_provider: MagicMock) -> None:
        send(_make_transaction(transaction_type="purchase"))
        captured_provider.send.assert_called_once()

    def test_e_transfer_type_sends(self, captured_provider: MagicMock) -> None:
        send(_make_transaction(transaction_type="e-transfer"))
        captured_provider.send.assert_called_once()


# ---------------------------------------------------------------------------
# Message formatting — golden-master parity with former send_sms()
# ---------------------------------------------------------------------------


def _captured_body(provider: MagicMock) -> str:
    call_kwargs = provider.send.call_args.kwargs
    return call_kwargs["body"]


class TestMessageContent:
    def test_body_contains_transaction_details(self, captured_provider: MagicMock) -> None:
        send(
            _make_transaction(
                company="Starbucks",
                amount=12.50,
                institution="RBC",
                category="Restaurant/Dining",
                name="Demo User",
            )
        )
        body = _captured_body(captured_provider)
        assert "Starbucks" in body
        assert "12.5" in body
        assert "RBC" in body
        assert "Demo User" in body

    def test_body_handles_none_values(self, captured_provider: MagicMock) -> None:
        details = {
            "company": "Test Co",
            "amount": None,
            "date": None,
            "transaction_type": "purchase",
            "institution": None,
            "category": None,
            "name": None,
        }
        send(details)
        body = _captured_body(captured_provider)
        assert "Unknown" in body

    def test_budget_line_with_context(self, captured_provider: MagicMock) -> None:
        context = {
            "category_month_total": 340,
            "category_budget_target": 400,
            "category_budget_pct": 85,
            "merchant_month_count": 1,
        }
        send(_make_transaction(), context=context)
        body = _captured_body(captured_provider)
        assert "$340/$400 (85%)" in body
        assert "\U0001f4ca" in body

    def test_category_line_without_budget(self, captured_provider: MagicMock) -> None:
        context = {"category_month_total": 100, "merchant_month_count": 1}
        send(_make_transaction(), context=context)
        body = _captured_body(captured_provider)
        assert "Category:" in body
        assert "\U0001f4c2" in body

    def test_merchant_frequency_line(self, captured_provider: MagicMock) -> None:
        context = {"category_month_total": 50, "merchant_month_count": 3}
        send(_make_transaction(), context=context)
        body = _captured_body(captured_provider)
        assert "3rd visit this month" in body
        assert "\U0001f504" in body

    def test_no_frequency_for_first_visit(self, captured_provider: MagicMock) -> None:
        context = {"category_month_total": 10, "merchant_month_count": 1}
        send(_make_transaction(), context=context)
        body = _captured_body(captured_provider)
        assert "visit this month" not in body

    def test_fallback_without_context(self, captured_provider: MagicMock) -> None:
        send(_make_transaction(), context=None)
        body = _captured_body(captured_provider)
        assert "Category:" in body

    def test_title_is_transaction(self, captured_provider: MagicMock) -> None:
        send(_make_transaction())
        call_kwargs = captured_provider.send.call_args.kwargs
        assert call_kwargs["title"] == "Transaction"


class TestOrdinal:
    def test_ordinal_formatting(self) -> None:
        assert _ordinal(1) == "1st"
        assert _ordinal(2) == "2nd"
        assert _ordinal(3) == "3rd"
        assert _ordinal(4) == "4th"
        assert _ordinal(11) == "11th"
        assert _ordinal(12) == "12th"
        assert _ordinal(13) == "13th"
        assert _ordinal(21) == "21st"
        assert _ordinal(22) == "22nd"
        assert _ordinal(23) == "23rd"


class TestFormatterByteLevelParity:
    """Locks the emoji-formatted body to its exact byte layout.

    This is the golden master for the live AWS Lambda path — if these assertions
    break, the user's SMS on their phone will look different after the migration.
    """

    def test_full_body_with_budget_and_repeat_visit(self) -> None:
        body = _format_transaction_body(
            _make_transaction(
                company="Starbucks",
                amount=4.50,
                date="01/15/2026 09:12 PST",
                transaction_type="purchase",
                institution="RBC",
                category="Restaurant/Dining",
                name="Demo User",
            ),
            context={
                "category_month_total": 340,
                "category_budget_target": 400,
                "category_budget_pct": 85,
                "merchant_month_count": 2,
            },
        )
        expected = (
            "\U0001f4b8 Transaction \U0001f4b8\n"
            "\U0001f3e2 Company: Starbucks\n"
            "\U0001f4b5 Amount: $4.5\n"
            "\U0001f4c5 Date: 01/15/2026 09:12 PST\n"
            "\U0001f4b3 Type: purchase\n"
            "\U0001f3e6 Institution: RBC\n"
            "\U0001f4ca Restaurant/Dining \u2014 $340/$400 (85%)\n"
            "\U0001f464 Person: Demo User \U0001f60a"
            "\n\U0001f504 2nd visit this month"
        )
        assert body == expected

    def test_full_body_without_context(self) -> None:
        body = _format_transaction_body(_make_transaction(), context=None)
        expected = (
            "\U0001f4b8 Transaction \U0001f4b8\n"
            "\U0001f3e2 Company: Tim Hortons\n"
            "\U0001f4b5 Amount: $5.5\n"
            "\U0001f4c5 Date: 01/15/2026 14:30 PST\n"
            "\U0001f4b3 Type: purchase\n"
            "\U0001f3e6 Institution: CIBC\n"
            "\U0001f4c2 Category: Restaurant/Dining\n"
            "\U0001f464 Person: Carlos \U0001f60a"
        )
        assert body == expected


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------


class TestProviderSelection:
    def test_explicit_provider_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOTIFICATION_PROVIDER", "ntfy")
        monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:us-west-2:1:topic")
        assert _select_provider_name() == "ntfy"

    def test_autodetect_sns_when_topic_arn_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:us-west-2:1:topic")
        assert _select_provider_name() == "sns"

    def test_autodetect_ntfy_when_only_url_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOTIFICATION_URL", "https://ntfy.sh/my-topic")
        assert _select_provider_name() == "ntfy"

    def test_sns_takes_precedence_in_autodetect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Existing AWS users have SNS_TOPIC_ARN set — don't surprise them."""
        monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:us-west-2:1:topic")
        monkeypatch.setenv("NOTIFICATION_URL", "https://ntfy.sh/my-topic")
        assert _select_provider_name() == "sns"

    def test_defaults_to_log_only(self) -> None:
        assert _select_provider_name() == "log"

    def test_unknown_provider_falls_back_to_log_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOTIFICATION_PROVIDER", "carrierpigeon")
        reset_provider_cache()
        provider = notification_service._get_provider()
        assert isinstance(provider, LogOnlyProvider)


# ---------------------------------------------------------------------------
# SnsProvider — boto3 call parity with the old Lambda send_sms()
# ---------------------------------------------------------------------------


class TestSnsProvider:
    def test_publishes_with_topic_arn_and_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:us-west-2:1:my-topic")
        mock_boto_client = MagicMock(name="boto_client")
        mock_sns = MagicMock(name="sns")
        mock_sns.publish.return_value = {"MessageId": "test-id-123"}
        mock_boto_client.return_value = mock_sns

        with patch("boto3.client", mock_boto_client):
            provider = SnsProvider()
            provider.send(title="Transaction", body="the body")

        mock_boto_client.assert_called_once_with("sns", region_name="us-west-2")
        mock_sns.publish.assert_called_once_with(
            TopicArn="arn:aws:sns:us-west-2:1:my-topic",
            Message="the body",
        )

    def test_uses_custom_aws_region(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:1:t")
        monkeypatch.setenv("AWS_REGION", "us-east-1")
        mock_boto_client = MagicMock(name="boto_client")
        mock_boto_client.return_value = MagicMock()

        with patch("boto3.client", mock_boto_client):
            SnsProvider()

        mock_boto_client.assert_called_once_with("sns", region_name="us-east-1")

    def test_logs_message_id_on_success(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("SNS_TOPIC_ARN", "arn")
        mock_sns = MagicMock()
        mock_sns.publish.return_value = {"MessageId": "abc-123"}
        mock_boto_client = MagicMock(return_value=mock_sns)

        with patch("boto3.client", mock_boto_client):
            provider = SnsProvider()
            with caplog.at_level("INFO", logger="src.finance.notification_service"):
                provider.send(title="t", body="b")

        assert "SMS sent: abc-123" in caplog.text


# ---------------------------------------------------------------------------
# Fail-open behavior
# ---------------------------------------------------------------------------


class TestFailOpen:
    def test_send_swallows_provider_error(self, captured_provider: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
        captured_provider.send.side_effect = RuntimeError("boom")
        with caplog.at_level("ERROR", logger="src.finance.notification_service"):
            send(_make_transaction())
        assert "Error sending notification" in caplog.text
        assert "boom" in caplog.text

    def test_send_raw_swallows_provider_error(
        self, captured_provider: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        captured_provider.send.side_effect = RuntimeError("kaboom")
        with caplog.at_level("ERROR", logger="src.finance.notification_service"):
            send_raw(title="t", body="b")
        assert "Error sending notification" in caplog.text
        assert "kaboom" in caplog.text


# ---------------------------------------------------------------------------
# send_raw — bypasses filter and formatter
# ---------------------------------------------------------------------------


class TestSendRaw:
    def test_passes_title_body_tags_to_provider(self, captured_provider: MagicMock) -> None:
        send_raw(title="Monthly Summary", body="Spent $500", tags=["chart"])
        captured_provider.send.assert_called_once_with(title="Monthly Summary", body="Spent $500", tags=["chart"])

    def test_does_not_apply_blocked_companies_filter(self, captured_provider: MagicMock) -> None:
        """send_raw is for pre-formatted messages — no filtering."""
        send_raw(title="Monthly Summary", body="YouTube Premium spent $20")
        captured_provider.send.assert_called_once()


# ---------------------------------------------------------------------------
# NtfyProvider — initialization guard
# ---------------------------------------------------------------------------


class TestNtfyProvider:
    def test_requires_notification_url(self) -> None:
        # Env is cleared by _clear_env fixture
        with pytest.raises(RuntimeError, match="NOTIFICATION_URL is required"):
            NtfyProvider()

    def test_posts_body_and_title(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOTIFICATION_URL", "https://ntfy.sh/my-topic")
        mock_response = MagicMock(status_code=200)
        with patch("requests.post", return_value=mock_response) as mock_post:
            provider = NtfyProvider()
            provider.send(title="Transaction", body="hello", tags=["money"])

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "https://ntfy.sh/my-topic"
        assert kwargs["data"] == b"hello"
        assert kwargs["headers"]["Title"] == "Transaction"
        assert kwargs["headers"]["Tags"] == "money"
