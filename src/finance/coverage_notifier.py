"""Quiet-transition notifier for ingestion coverage (Decision D6).

Zero-ledger transition detection: a daily check notifies once, calmly, when an
institution *just* crossed from active into quiet — never on the standing quiet
state, never on ``dormant``/``irregular``/``active``. No persisted notification
state exists by design: ``data/config.json`` stays user-owned and a background
writer would race it. The transition window (``threshold < days_quiet ≤
threshold + 2``) plus an in-process 24h per-institution suppression dict are the
only throttles.

Entirely fail-open — every path logs and returns rather than raising, so a wire
into a scheduler or a Lambda can never take the process down.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Protocol

from src.finance import notification_service

logger = logging.getLogger(__name__)

# Self-hosted scheduler cadence: check once a day. Kept independent of the
# daily-summary scheduler so coverage runs even when summaries are disabled.
_DAILY_INTERVAL_SECONDS = 24 * 60 * 60

# Just-crossed window: notify only within ``threshold_gap_days + 2`` days of the
# threshold, so a standing-quiet institution isn't re-announced every run.
_TRANSITION_WINDOW_DAYS = 2

# In-process per-institution suppression: institution -> monotonic timestamp of
# the last send. Inert across process restarts (Lambda cold starts, API
# restarts) — deliberate: the transition window alone bounds re-notification.
_SUPPRESSION_SECONDS = 24 * 60 * 60
_suppression: dict[str, float] = {}


class _CoverageServiceLike(Protocol):
    def get_coverage(self) -> dict[str, Any]: ...


def reset_suppression() -> None:
    """Clear the in-process suppression dict. Mirrors ``reset_provider_cache``; used by tests."""
    _suppression.clear()


def _just_crossed_quiet(row: dict[str, Any]) -> bool:
    """True when the row is quiet and inside the just-crossed transition window."""
    if row.get("status") != "quiet":
        return False
    threshold = row.get("threshold_gap_days")
    days = row.get("days_since_last_seen")
    if threshold is None or days is None:
        return False
    return threshold < days <= threshold + _TRANSITION_WINDOW_DAYS


def check_quiet_notifications(coverage_service: _CoverageServiceLike) -> list[str]:
    """Notify on institutions that just went quiet; return the ones notified.

    Reads the coverage snapshot, sends a single ``send_raw`` note per institution
    that just crossed into quiet and isn't 24h-suppressed, records the send in the
    suppression dict, and returns the list of notified institutions (for logging
    and tests). Fail-open throughout.
    """
    notified: list[str] = []
    try:
        coverage = coverage_service.get_coverage()
    except Exception:
        logger.exception("coverage notifier: failed to read coverage snapshot")
        return notified

    now = time.monotonic()
    for row in coverage.get("institutions", []):
        try:
            if not _just_crossed_quiet(row):
                continue
            institution = row["institution"]
            last = _suppression.get(institution)
            if last is not None and (now - last) < _SUPPRESSION_SECONDS:
                continue
            days = row["days_since_last_seen"]
            threshold = row["threshold_gap_days"]
            notification_service.send_raw(
                title="Tidings",
                body=(
                    f"{institution} has been quiet for {days} days — you usually see a gap of no more than {threshold}"
                ),
            )
            _suppression[institution] = now
            notified.append(institution)
        except Exception:
            logger.exception("coverage notifier: failed to notify for a quiet institution")
            continue

    return notified


async def run_coverage_scheduler(shutdown: asyncio.Event) -> None:
    """Long-lived daily loop: wake once a day, run the quiet-transition check.

    A sibling of the daily-summary scheduler (spawned from the same FastAPI
    lifespan and keyed off the same shutdown event), deliberately independent of
    the summary provider's config so quiet detection runs regardless. Waits the
    interval before the first check so process restarts don't re-notify inside
    the 2-day transition window. Cancellation-safe and fail-open.
    """
    logger.info("Coverage quiet-check scheduler started")
    while not shutdown.is_set():
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=_DAILY_INTERVAL_SECONDS)
            return  # shutdown fired
        except TimeoutError:
            pass  # normal daily wake
        try:
            from src.api.dependencies import get_coverage_service

            notified = check_quiet_notifications(get_coverage_service())
            if notified:
                logger.info("Coverage quiet-check notified: %s", ", ".join(notified))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Coverage quiet-check scheduler loop error")
    logger.info("Coverage quiet-check scheduler stopped")
