"""Unified notification service.

Single entry point used by both the AWS Lambda (`docker/email_parsing/lambda_function.py`,
`docker/email_parsing/summary_handler.py`) and the self-hosted IMAP daemon
(`src/finance/imap_poller.py`). Selects a transport provider from three built-ins:

- ``sns``   — AWS SNS (``boto3``); preserves the existing Lambda path.
- ``ntfy``  — ntfy.sh HTTP POST; default for self-hosters.
- ``twilio``— Twilio SMS (lazy import of the ``twilio`` SDK).

Provider is chosen via the ``NOTIFICATION_PROVIDER`` env var. When unset,
auto-detects from whichever provider-specific env vars are configured:
``SNS_TOPIC_ARN`` → ``sns``; ``NOTIFICATION_URL`` → ``ntfy``; otherwise log-only.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Protocol

from src.finance.config_loader import get_blocked_companies

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider Protocol + implementations
# ---------------------------------------------------------------------------


class NotificationProvider(Protocol):
    def send(self, title: str, body: str, tags: list[str] | None = None) -> None: ...


class LogOnlyProvider:
    """Fallback — writes to logger only. Used when no provider is configured."""

    def send(self, title: str, body: str, tags: list[str] | None = None) -> None:
        logger.info("NOTIFY [%s]: %s", title, body.replace("\n", " | "))


class SnsProvider:
    """AWS SNS SMS — thin wrapper around ``boto3.client('sns').publish``."""

    def __init__(self) -> None:
        import boto3

        from src.finance.aws_region import get_aws_region

        self._client = boto3.client("sns", region_name=get_aws_region())
        self._topic_arn = os.environ.get("SNS_TOPIC_ARN", "")

    def send(self, title: str, body: str, tags: list[str] | None = None) -> None:
        response = self._client.publish(TopicArn=self._topic_arn, Message=body)
        logger.info("SMS sent: %s", response["MessageId"])


class NtfyProvider:
    """ntfy.sh — HTTP POST to ``NOTIFICATION_URL``."""

    def __init__(self) -> None:
        self._url = os.environ.get("NOTIFICATION_URL", "").rstrip("/")
        if not self._url:
            raise RuntimeError("NOTIFICATION_URL is required for the ntfy provider")

    def send(self, title: str, body: str, tags: list[str] | None = None) -> None:
        import requests

        headers = {"Title": title}
        if tags:
            headers["Tags"] = ",".join(tags)
        response = requests.post(
            self._url,
            data=body.encode("utf-8"),
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        logger.info("ntfy sent to %s (status %d)", self._url, response.status_code)


class TwilioProvider:
    """Twilio SMS — lazy import of the Twilio SDK."""

    def __init__(self) -> None:
        from twilio.rest import Client

        sid = os.environ["TWILIO_ACCOUNT_SID"]
        token = os.environ["TWILIO_AUTH_TOKEN"]
        self._from = os.environ["TWILIO_FROM_NUMBER"]
        self._to = os.environ["TWILIO_TO_NUMBER"]
        self._client = Client(sid, token)

    def send(self, title: str, body: str, tags: list[str] | None = None) -> None:
        message_body = f"{title}\n{body}" if title else body
        message = self._client.messages.create(
            body=message_body,
            from_=self._from,
            to=self._to,
        )
        logger.info("Twilio sent: %s", message.sid)


# ---------------------------------------------------------------------------
# Provider selection + caching
# ---------------------------------------------------------------------------


_PROVIDER_REGISTRY = {
    "sns": SnsProvider,
    "ntfy": NtfyProvider,
    "twilio": TwilioProvider,
    "log": LogOnlyProvider,
}

_provider_cache: NotificationProvider | None = None


def _select_provider_name() -> str:
    explicit = os.environ.get("NOTIFICATION_PROVIDER", "").strip().lower()
    if explicit:
        return explicit
    if os.environ.get("SNS_TOPIC_ARN"):
        return "sns"
    if os.environ.get("NOTIFICATION_URL"):
        return "ntfy"
    return "log"


def _get_provider() -> NotificationProvider:
    global _provider_cache
    if _provider_cache is None:
        name = _select_provider_name()
        cls = _PROVIDER_REGISTRY.get(name)
        if cls is None:
            logger.warning("Unknown NOTIFICATION_PROVIDER=%s — falling back to log-only", name)
            _provider_cache = LogOnlyProvider()
        else:
            _provider_cache = cls()
    assert _provider_cache is not None  # noqa: S101 — type-narrowing; both branches set the cache
    return _provider_cache


def reset_provider_cache() -> None:
    """Reset the cached provider so env-var changes take effect. Used by tests."""
    global _provider_cache
    _provider_cache = None


# ---------------------------------------------------------------------------
# Message formatting — parity with the previous send_sms() in lambda_function.py
# ---------------------------------------------------------------------------


def _ordinal(n: int) -> str:
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _value_or_default(details: dict[str, Any], key: str, default: str = "Unknown") -> Any:
    value = details.get(key)
    return value if value is not None else default


def _format_transaction_body(transaction_details: dict[str, Any], context: dict[str, Any] | None) -> str:
    company = _value_or_default(transaction_details, "company")
    amount = _value_or_default(transaction_details, "amount")
    date = _value_or_default(transaction_details, "date")
    transaction_type = _value_or_default(transaction_details, "transaction_type")
    institution = _value_or_default(transaction_details, "institution")
    category = _value_or_default(transaction_details, "category")
    person = _value_or_default(transaction_details, "name")

    if context and "category_budget_target" in context:
        total = context["category_month_total"]
        target = context["category_budget_target"]
        pct = context["category_budget_pct"]
        category_line = f"\U0001f4ca {category} \u2014 ${total:,.0f}/${target:,.0f} ({pct:.0f}%)"
    else:
        category_line = f"\U0001f4c2 Category: {category}"

    merchant_line = ""
    if context and context.get("merchant_month_count", 0) > 1:
        count = context["merchant_month_count"]
        merchant_line = f"\n\U0001f504 {_ordinal(count)} visit this month"

    return (
        f"\U0001f4b8 Transaction \U0001f4b8\n"
        f"\U0001f3e2 Company: {company}\n"
        f"\U0001f4b5 Amount: ${amount}\n"
        f"\U0001f4c5 Date: {date}\n"
        f"\U0001f4b3 Type: {transaction_type}\n"
        f"\U0001f3e6 Institution: {institution}\n"
        f"{category_line}\n"
        f"\U0001f464 Person: {person} \U0001f60a"
        f"{merchant_line}"
    )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def send(transaction_details: dict[str, Any], context: dict[str, Any] | None = None) -> None:
    """Send a transaction notification.

    Applies blocked-companies filter, skips unknown transaction types, formats the
    body, and dispatches to the configured provider. Fail-open: any error is
    logged, never re-raised.
    """
    try:
        company = transaction_details.get("company") or "Unknown"
        transaction_type = transaction_details.get("transaction_type") or "Unknown"

        blocked = get_blocked_companies()
        if any(b.lower() in company.lower() for b in blocked):
            logger.info("Notification skipped for blocked company: %s", company)
            return

        if transaction_type == "Unknown":
            logger.info("Notification skipped for unknown transaction type")
            return

        body = _format_transaction_body(transaction_details, context)
        _get_provider().send(title="Transaction", body=body)
    except Exception as exc:
        logger.exception("Error sending notification: %s", exc)


def send_raw(title: str, body: str, tags: list[str] | None = None) -> None:
    """Send a pre-formatted message directly to the provider.

    Bypasses the blocked-companies filter and transaction formatter — for callers
    that have already composed the full message (e.g. ``summary_handler.py``'s
    monthly summary). Fail-open.
    """
    try:
        _get_provider().send(title=title, body=body, tags=tags)
    except Exception as exc:
        logger.exception("Error sending notification: %s", exc)
