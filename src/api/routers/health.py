"""Liveness and last-activity health probe.

Exposes ``GET /api/v1/health`` — unauthenticated, cheap, and safe to poll
from a frontend widget or external uptime monitor. Two tiny read queries
(IMAP heartbeat + most-recent transaction) drive the status field.

The probe deliberately does **not** call OpenAI, DynamoDB scans, or any
expensive aggregate — target < 50 ms end-to-end.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter

from src.api.dependencies import get_coverage_service, get_parse_failure_store, get_transactions_db
from src.api.models import HealthResponse, HealthStatus
from src.finance.app_config import get_config
from src.finance.app_timezone import get_app_timezone
from src.finance.category_audit import normalize_audit
from src.finance.imap_poller import get_imap_last_poll

if TYPE_CHECKING:
    from src.api.models.health import AICategorizationStatus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


# Thresholds (seconds). Tuned to the IMAP poller's default 60s cadence —
# anything past a few multiples of the tick is genuinely suspect.
_POLL_OK_MAX_SECONDS = 5 * 60  # 5 minutes
_POLL_DEGRADED_MAX_SECONDS = 30 * 60  # 30 minutes
_TX_STALE_SECONDS = 14 * 24 * 60 * 60  # 14 days — parser-break heuristic

# AI categorization: fallback reasons that mean the provider/transport failed
# (vs. intentionally disabled, or a one-off model hiccup). A run of these means
# new transactions are silently filing as Miscellaneous.
_AI_HARD_ERROR_REASONS = frozenset(
    {"quota_exceeded", "rate_limited", "auth_error", "api_error", "codex_error", "codex_timeout"}
)
# How many recent rows to sample, and the minimum hard-error count before we
# call it degraded (so a single transient blip doesn't flip the signal).
_AI_AUDIT_SAMPLE = 25
_AI_DEGRADED_MIN_ERRORS = 3

# Matches the DateFileName format produced by TransactionsDBLocal /
# TransactionsDB: ``YYYY.MM.DD_HH.MM_<file>`` (or statement-import variants
# that still lead with the ``YYYY.MM.DD_HH.MM`` prefix).
_DATE_FILE_NAME_RE = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})_(\d{2})\.(\d{2})")

# DateFileName timestamps are local to the configured app timezone —
# email_parser.py converts every incoming email date to that zone before
# transaction_db.py strftime's it (stripping the tz suffix). We interpret
# them back in the same zone, otherwise "age" is wrong by the UTC offset.


def _get_version() -> str:
    """Return the installed package version, falling back to the literal in pyproject."""
    try:
        return pkg_version("tidings")
    except PackageNotFoundError:
        return "0.0.0"


def _parse_iso(ts: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp. Returns a UTC-aware datetime or None."""
    if not ts:
        return None
    try:
        # Python's fromisoformat accepts the '+00:00' we write. Accept 'Z' too.
        normalised = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
        dt = datetime.fromisoformat(normalised)
    except ValueError:
        logger.debug("health: could not parse timestamp %r", ts)
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _date_file_name_to_dt(date_file_name: str | None) -> datetime | None:
    """Extract a UTC datetime from a ``YYYY.MM.DD_HH.MM_…`` key.

    The filename fields are local to the configured app timezone
    (email_parser.py converts every email date to that zone before
    transaction_db.py strftime's it and drops the tz suffix). We attach the
    configured zone on the way back, then convert to UTC so downstream age
    arithmetic against ``datetime.now(UTC)`` is correct across DST transitions.
    """
    if not date_file_name:
        return None
    m = _DATE_FILE_NAME_RE.match(date_file_name)
    if not m:
        return None
    try:
        y, mo, d, h, mi = (int(x) for x in m.groups())
        return datetime(y, mo, d, h, mi, tzinfo=get_app_timezone()).astimezone(UTC)
    except ValueError:
        return None


def _compute_ai_categorization(
    audits: list[dict[str, Any]] | None,
) -> tuple[AICategorizationStatus | None, str | None]:
    """Derive ``(status, last_error_reason)`` from recent transaction audits.

    ``degraded`` when hard provider/transport errors dominate recent AI activity
    — at least ``_AI_DEGRADED_MIN_ERRORS`` of them and no fewer than the AI
    successes in the sample (a sustained outage, not a transient blip).
    Override-categorized and intentionally-disabled rows are ignored: they say
    nothing about AI health. ``None`` when the audits could not be read.

    Audits are newest-first, so the first hard error encountered is the most
    recent — surfaced as ``last_error_reason`` to name *why* (quota, auth, …).
    """
    if audits is None:
        return None, None

    errors = 0
    successes = 0
    last_reason: str | None = None
    for item in audits:
        audit = normalize_audit(item.get("CategoryAudit")) or {}
        source = audit.get("source")
        if source == "ai":
            successes += 1
        elif source == "ai_fallback" and audit.get("fallback_reason") in _AI_HARD_ERROR_REASONS:
            errors += 1
            if last_reason is None:
                last_reason = audit.get("fallback_reason")

    if errors >= _AI_DEGRADED_MIN_ERRORS and errors >= successes:
        return "degraded", last_reason
    return "ok", None


def _compute_status(
    imap_age_seconds: int | None,
    tx_age_seconds: int | None,
    parse_failures_7d: int | None = None,
    ai_categorization_status: AICategorizationStatus | None = None,
    quiet_institutions: int | None = None,
) -> HealthStatus:
    """Apply the documented status rules.

    - ``stale`` wins: poll > 30 min OR no tx in 14 days.
    - ``degraded``: poll 5-30 min, OR one or more parse failures in the last
      7 days (template-drift signal), OR AI categorization degraded (provider
      outage filing transactions as Miscellaneous), OR one or more institutions
      whose bank-alert cadence has gone quiet (ingestion coverage).
    - ``ok`` otherwise (including "no IMAP configured", where ``imap_age_seconds``
      is ``None`` and we have no evidence of a stuck poller).

    The soft signals (parse failures, AI categorization, quiet institutions) are
    applied *last* and only ever raise ``ok`` to ``degraded`` — never downgrading
    a worse status, so a genuine ``stale`` poll/tx condition still wins.
    """
    if tx_age_seconds is not None and tx_age_seconds > _TX_STALE_SECONDS:
        return "stale"
    if imap_age_seconds is not None:
        if imap_age_seconds > _POLL_DEGRADED_MAX_SECONDS:
            return "stale"
        if imap_age_seconds > _POLL_OK_MAX_SECONDS:
            return "degraded"
    if parse_failures_7d is not None and parse_failures_7d > 0:
        return "degraded"
    if ai_categorization_status == "degraded":
        return "degraded"
    if quiet_institutions and quiet_institutions > 0:
        return "degraded"
    return "ok"


@router.get(
    "/health",
    response_model=HealthResponse,
    operation_id="getHealth",
    summary="Liveness probe with last-activity snapshot",
)
def get_health() -> HealthResponse:
    """Return liveness + last-activity snapshot. Unauthenticated.

    Reads three cheap signals — the IMAP heartbeat, the most-recent
    transaction, and the count of emails quarantined in the last 7 days — and
    folds them into ``status``. Every read is fail-open: a broken storage
    backend (including a missing parse-failures table on a fresh boot) is
    logged and degrades that field to ``None`` rather than 500-ing the probe.
    """
    now = datetime.now(UTC)

    # --- IMAP poller heartbeat (SQLite only; DynamoDB deployments don't run it) ---
    imap_last_poll_str = get_imap_last_poll()
    imap_dt = _parse_iso(imap_last_poll_str)
    imap_age_seconds: int | None = None
    if imap_dt is not None:
        imap_age_seconds = max(0, int((now - imap_dt).total_seconds()))

    # --- Most recent transaction ---
    last_tx_dt: datetime | None = None
    try:
        tx_db = get_transactions_db()
        latest_dfn = tx_db.get_latest_date_file_name()
        last_tx_dt = _date_file_name_to_dt(latest_dfn)
    except Exception:
        # A broken storage backend shouldn't crash the health probe itself.
        logger.exception("health: failed to query latest transaction")

    last_tx_age_seconds: int | None = None
    last_tx_iso: str | None = None
    if last_tx_dt is not None:
        last_tx_age_seconds = max(0, int((now - last_tx_dt).total_seconds()))
        # Serialise without microseconds, with Z suffix for consistency.
        last_tx_iso = last_tx_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # --- Recent parse failures (template-drift signal) ---
    parse_failures_7d: int | None = None
    try:
        parse_failures_7d = get_parse_failure_store().count_recent_quarantined(days=7)
    except Exception:
        # A missing/broken parse-failure store must not crash the probe — a
        # fresh boot with no parse_failures table should still return 200.
        logger.exception("health: failed to count recent parse failures")

    # --- AI categorization health (recent-audit signal) ---
    recent_audits: list[dict[str, Any]] | None = None
    try:
        recent_audits = get_transactions_db().get_recent_audits(limit=_AI_AUDIT_SAMPLE)
    except Exception:
        # A broken/empty backend must not crash the probe — leave the field None.
        logger.exception("health: failed to read recent audits")
    ai_categorization_status, ai_last_error_reason = _compute_ai_categorization(recent_audits)

    # --- Quiet-institution count (ingestion-coverage signal) ---
    # Reads the coverage service's own 1-hour TTL cache (one cache-fill per hour
    # is the accepted cost) — never a fresh scan on the probe's <50ms budget.
    quiet_institutions: int | None = None
    try:
        coverage = get_coverage_service().get_coverage()
        quiet_institutions = sum(1 for row in coverage["institutions"] if row["status"] == "quiet")
    except Exception:
        # Any failure leaves the field None and never blocks the other signals.
        logger.exception("health: failed to read coverage snapshot")

    status = _compute_status(
        imap_age_seconds,
        last_tx_age_seconds,
        parse_failures_7d,
        ai_categorization_status,
        quiet_institutions,
    )

    config = get_config()
    backend = str(config.get("storage", "sqlite"))

    return HealthResponse(
        status=status,
        version=_get_version(),
        backend=backend,
        imap_last_poll=imap_last_poll_str,
        imap_poll_age_seconds=imap_age_seconds,
        last_transaction_at=last_tx_iso,
        last_transaction_age_seconds=last_tx_age_seconds,
        parse_failures_7d=parse_failures_7d,
        ai_categorization_status=ai_categorization_status,
        ai_last_error_reason=ai_last_error_reason,
        quiet_institutions=quiet_institutions,
        checked_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        auth_required=get_config().get("app_password_hash") is not None,
    )
