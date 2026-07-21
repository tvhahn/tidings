"""Per-institution bank-alert cadence modeling ("ingestion coverage").

Models each institution's email-arrival cadence from its own history and detects
when one goes quiet — a card reissue that silently reset alert enrollment, a
broken forwarding filter, a sender-domain change the user's rule misses. The
email-first pipeline's one blind spot (emails that never arrive are invisible)
becomes a detected condition instead of a silent undercount.

Read-only derivation on the ``MerchantIntelligenceService`` template: reads a
trailing 12-month window via the summary pair's ``query_month``, a 1-hour
in-memory cache, no new storage and no migration. Safe under both DynamoDB and
SQLite backends because it consumes only the storage-agnostic protocols.

Cadence events are per-institution email-arrival days parsed from raw
``DateFileName`` keys (``YYYY.MM.DD_HH.MM_…``, already configured-local calendar
dates — day-level math throughout, no timezone conversion). Statement-imported
rows (``_00.00_stmt_``) and manually-added rows (``_00.00_manual_``) carry
synthetic timestamps and are excluded; quarantined arrivals extend ``last_seen``
so parser drift never reads as silence. The passive capture rate comes from
statement reconciliation via :meth:`StatementStore.capture_summary`.
"""

from __future__ import annotations

import logging
import math
import re
import statistics
import time
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from dateutil.relativedelta import relativedelta

from src.finance.category_audit import now_local_iso
from src.finance.demo_clock import app_today

if TYPE_CHECKING:
    from src.finance.protocols import IParseFailureStore, ISpendingSummary
    from src.finance.statement_store import StatementStore

logger = logging.getLogger(__name__)

# --- Cadence model constants (Decisions D1/D2 — LOCKED in the spec) ---------
_WINDOW_MONTHS = 12
_CACHE_TTL_SECONDS = 3600.0
# Only project the two attributes the cadence model reads. Neither ``DateFileName``
# nor ``Institution`` is a DynamoDB reserved word, so no ExpressionAttributeNames
# are needed (the query_month impl accepts them if that ever changes).
_PROJECTION = "DateFileName, Institution"

# Eligibility bar: below this an institution has no meaningful cadence and is
# reported ``irregular`` (never flagged, never degraded, never notified).
_MIN_EVENT_DAYS = 8
_MIN_SPAN_DAYS = 60

# Threshold / cutoff floors.
_MIN_THRESHOLD_DAYS = 7
_MIN_DORMANT_CUTOFF_DAYS = 45

# Matches the email-receipt DateFileName format ``YYYY.MM.DD_HH.MM_<file>``.
# A row whose key does not match (or carries a synthetic marker below) is not a
# real email arrival and is skipped.
_DATE_FILE_NAME_RE = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})_(\d{2})\.(\d{2})")
# Statement-imported rows and manually-added rows both synthesize a ``00.00``
# time with a distinguishing filename token — neither proves an email arrived.
_STATEMENT_MARKER = "_00.00_stmt_"
_MANUAL_MARKER = "_00.00_manual_"

# Sort priority: quiet (the actionable state) first, then active, then the
# descriptive dormant/irregular tails; alphabetical within each group.
_STATUS_ORDER = {"quiet": 0, "active": 1, "dormant": 2, "irregular": 3}


def _event_day(date_file_name: str | None) -> date | None:
    """Return the calendar day of a real email arrival, or None to skip the row.

    Skips statement-imported / manually-added rows (synthetic markers) and any
    key that does not match the ``YYYY.MM.DD_HH.MM_…`` email-receipt format. The
    ``YYYY.MM.DD`` prefix is already a configured-local calendar date, so it is
    read directly — no timezone conversion.
    """
    if not date_file_name:
        return None
    if _STATEMENT_MARKER in date_file_name or _MANUAL_MARKER in date_file_name:
        return None
    match = _DATE_FILE_NAME_RE.match(date_file_name)
    if not match:
        return None
    year, month, day, _hour, _minute = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _iso_to_date(value: str | None) -> date | None:
    """Parse the date part of an ISO timestamp (``received_at``), tolerantly."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None


class CoverageService:
    """Per-institution cadence + passive capture rate.

    Read-only over ``ISpendingSummary`` and ``IParseFailureStore`` (both
    dual-backend-safe protocols) plus the SQLite-only ``StatementStore`` for the
    capture rate, which is optional — ``None`` on the DynamoDB path where no
    statement store exists.
    """

    def __init__(
        self,
        spending_summary: ISpendingSummary,
        parse_failure_store: IParseFailureStore,
        statement_store: StatementStore | None = None,
    ) -> None:
        self._summary = spending_summary
        self._parse_failures = parse_failure_store
        self._statements = statement_store
        self._cache: dict[str, Any] | None = None
        self._cache_time: float = 0.0

    def get_coverage(self) -> dict[str, Any]:
        """Return the coverage snapshot, cached in memory for 1 hour."""
        now = time.time()
        if self._cache is not None and (now - self._cache_time) < _CACHE_TTL_SECONDS:
            return self._cache
        result = self._compute()
        self._cache = result
        self._cache_time = now
        return result

    def invalidate_cache(self) -> None:
        self._cache = None
        self._cache_time = 0.0

    # ------------------------------------------------------------------
    # Core computation
    # ------------------------------------------------------------------

    def _compute(self) -> dict[str, Any]:
        today = app_today()
        target = date(today.year, today.month, 1)
        # Trailing 12 months including the current month, oldest first.
        window_keys = [(target - relativedelta(months=i)).strftime("%Y-%m") for i in range(_WINDOW_MONTHS - 1, -1, -1)]

        # Distinct email-arrival days per institution across the window.
        event_days_by_institution: dict[str, set[date]] = {}
        for year_month in window_keys:
            for row in self._summary.query_month(year_month, _PROJECTION):
                institution = row.get("Institution")
                if not institution:
                    continue
                day = _event_day(row.get("DateFileName"))
                if day is None:
                    continue
                event_days_by_institution.setdefault(institution, set()).add(day)

        quarantine = self._latest_quarantine()

        # Only institutions with parsed email history are listed; quarantine
        # evidence merely extends last_seen for those, never introduces new rows.
        institutions = [
            self._classify(institution, days, quarantine, today)
            for institution, days in event_days_by_institution.items()
        ]
        institutions.sort(key=lambda row: (_STATUS_ORDER[row["status"]], row["institution"]))

        return {
            "institutions": institutions,
            "capture": self._capture(),
            "window_months": _WINDOW_MONTHS,
            "checked_at": now_local_iso(),
        }

    def _classify(
        self,
        institution: str,
        day_set: set[date],
        quarantine: dict[str, str],
        today: date,
    ) -> dict[str, Any]:
        event_days = sorted(day_set)
        first_day = event_days[0]
        last_event_day = event_days[-1]
        event_count = len(event_days)

        # Quarantine (any arrival evidence) can only push last_seen forward.
        last_seen_day = last_event_day
        quarantine_day = _iso_to_date(quarantine.get(institution))
        if quarantine_day is not None and quarantine_day > last_seen_day:
            last_seen_day = quarantine_day
        days_since_last_seen = (today - last_seen_day).days

        eligible = event_count >= _MIN_EVENT_DAYS and (last_event_day - first_day).days >= _MIN_SPAN_DAYS
        if not eligible:
            return {
                "institution": institution,
                "status": "irregular",
                "last_seen_at": last_seen_day.isoformat(),
                "days_since_last_seen": days_since_last_seen,
                "median_gap_days": None,
                "threshold_gap_days": None,
                "dormant_cutoff_days": None,
                "event_days": event_count,
            }

        gaps = [(event_days[i] - event_days[i - 1]).days for i in range(1, event_count)]
        median_gap = float(statistics.median(gaps))
        sorted_gaps = sorted(gaps)
        p95 = sorted_gaps[min(len(sorted_gaps) - 1, math.ceil(0.95 * len(sorted_gaps)) - 1)]
        threshold = max(math.ceil(1.5 * p95), _MIN_THRESHOLD_DAYS)
        dormant_cutoff = max(_MIN_DORMANT_CUTOFF_DAYS, 3 * threshold)

        if days_since_last_seen <= threshold:
            status = "active"
        elif days_since_last_seen <= dormant_cutoff:
            status = "quiet"
        else:
            status = "dormant"

        return {
            "institution": institution,
            "status": status,
            "last_seen_at": last_seen_day.isoformat(),
            "days_since_last_seen": days_since_last_seen,
            "median_gap_days": median_gap,
            "threshold_gap_days": threshold,
            "dormant_cutoff_days": dormant_cutoff,
            "event_days": event_count,
        }

    # ------------------------------------------------------------------
    # Fail-open reads
    # ------------------------------------------------------------------

    def _latest_quarantine(self) -> dict[str, str]:
        """Latest arrival per institution from the parse-failure store (fail-open)."""
        try:
            return self._parse_failures.latest_received_by_institution()
        except Exception:
            logger.exception("coverage: failed to read quarantine arrival evidence")
            return {}

    def _capture(self) -> dict[str, Any] | None:
        """Passive capture rate from statement reconciliation (fail-open).

        ``None`` when no statement store is wired (DynamoDB path) or the read
        raises — absence of data, never an error surfaced to the caller.
        """
        if self._statements is None:
            return None
        try:
            return self._statements.capture_summary()
        except Exception:
            logger.exception("coverage: failed to read capture summary")
            return None
