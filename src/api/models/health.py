"""Pydantic models for the /health liveness endpoint."""

from typing import Literal

from pydantic import BaseModel

HealthStatus = Literal["ok", "degraded", "stale"]
AICategorizationStatus = Literal["ok", "degraded"]


class HealthResponse(BaseModel):
    """Liveness + last-activity probe. Unauthenticated; no PII.

    Fields are all primitives so the payload is trivially cacheable and
    parseable by uptime monitors. Timestamps are ISO-8601 UTC strings
    (``YYYY-MM-DDTHH:MM:SSZ`` or with offset), or ``null`` when the
    underlying source has never been populated.
    """

    status: HealthStatus
    version: str
    backend: str  # "sqlite" | "dynamodb"
    imap_last_poll: str | None
    imap_poll_age_seconds: int | None
    last_transaction_at: str | None
    last_transaction_age_seconds: int | None
    # Count of emails quarantined in the last 7 days (template-drift signal).
    # ``None`` when the parse-failure store could not be read.
    parse_failures_7d: int | None
    # AI-categorization health, derived from recent transaction audits.
    # ``degraded`` when provider/transport errors (e.g. an exhausted OpenAI
    # quota) dominate recent categorization; ``ok`` otherwise; ``None`` when the
    # audits could not be read. ``ai_last_error_reason`` names the most recent
    # hard-error reason (``quota_exceeded``, ``auth_error``, …) when degraded.
    ai_categorization_status: AICategorizationStatus | None = None
    ai_last_error_reason: str | None = None
    # Count of institutions whose bank-alert cadence has gone quiet (ingestion
    # coverage). ``None`` when the coverage read was unavailable — the probe
    # stays fail-open and never blocks on it. A non-zero count raises ``ok`` to
    # ``degraded`` (soft signal), never downgrading ``stale``.
    quiet_institutions: int | None = None
    checked_at: str
    # Phase 4: SPA reads this on boot to choose between SetupBanner (false)
    # and LoginGate (true). Computed as `app_password_hash is not None`.
    auth_required: bool
