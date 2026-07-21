"""Background scheduler that generates today's journal AI summary at a
user-configured local time.

Runs as a single ``asyncio.Task`` spawned from the FastAPI lifespan. Wakes
once per scheduled firing, reads ``daily_summary_schedule_time`` and
``timezone`` from ``data/config.json`` on each iteration so live edits take
effect without restart, and short-circuits when the provider is disabled or
the daily-summary toggle is off.

A startup catch-up runs once if the scheduled time has already passed today
and no summary has been written yet — handles the "laptop was asleep at
7pm" case without separate cron infrastructure.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta
from pathlib import Path

from src.finance.app_config import get_config
from src.finance.app_timezone import get_app_timezone

logger = logging.getLogger(__name__)

_SUMMARIES_DIR = Path("data/journal")
_DEFAULT_TIME = "19:00"
_FAILURE_BACKOFF_SECONDS = 300  # 5 min — avoid hot-looping on persistent failure
# Floor on each firing wait so a clock skew / past-due firing can't spin the
# loop hot. Named (not an inline literal) so scheduler tests can shrink it and
# drive the wake→fire→skip branches deterministically instead of sleeping.
_MIN_WAIT_SECONDS = 1.0


def _parse_schedule_time(raw: str | None) -> time:
    """Parse ``HH:MM`` from config; fall back to 19:00 on bad input."""
    if not raw:
        return time(19, 0)
    try:
        hh, mm = raw.split(":", 1)
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        logger.warning("Invalid daily_summary_schedule_time %r; defaulting to %s", raw, _DEFAULT_TIME)
        return time(19, 0)


def _next_firing(now: datetime, scheduled: time) -> datetime:
    """Return the next datetime (in the same tz as ``now``) at ``scheduled``.

    If ``now`` is already past today's scheduled time, returns tomorrow's.
    """
    today_firing = now.replace(hour=scheduled.hour, minute=scheduled.minute, second=0, microsecond=0)
    if now >= today_firing:
        return today_firing + timedelta(days=1)
    return today_firing


def _today_summary_exists(today_local: date) -> bool:
    month_dir = _SUMMARIES_DIR / today_local.strftime("%Y-%m")
    day_file = month_dir / f"{today_local.day:02d}.txt"
    return day_file.is_file()


async def _generate_for_today() -> None:
    """Invoke kick_off_generation for today's date in the configured timezone.

    Imports lazily to avoid circular imports at module load time (the router
    pulls FastAPI dependencies that pull this module via the lifespan).
    """
    from fastapi import HTTPException

    from src.api.dependencies import get_budget_service, get_spending_summary
    from src.api.routers.daily_summaries import kick_off_generation

    tz = get_app_timezone()
    now = datetime.now(tz)
    today = now.date()
    month = today.strftime("%Y-%m")
    date_str = today.strftime("%Y-%m-%d")

    try:
        result = await kick_off_generation(
            month=month,
            dates=[date_str],
            force=False,
            summary=get_spending_summary(),
            budget_svc=get_budget_service(),
        )
        logger.info(
            "Scheduled summary kicked off for %s: status=%s queued=%d",
            date_str,
            result.status,
            result.dates_queued,
        )
    except HTTPException as e:
        # Provider disabled / toggle off / already running — these are normal
        # operating states for the scheduler, not errors.
        logger.info("Scheduled summary skipped for %s: %s", date_str, e.detail)


async def run_scheduler(shutdown: asyncio.Event) -> None:
    """Long-lived loop: catch-up once at startup, then sleep until each firing.

    Cancellation-safe: ``asyncio.sleep`` raises CancelledError on shutdown,
    which propagates out of the loop cleanly.
    """
    logger.info("Daily summary scheduler started")

    # Startup catch-up: if today's firing is already past and no summary was
    # written, generate now.
    try:
        cfg = get_config()
        if cfg.get("daily_summary_provider", "disabled") != "disabled" and cfg.get("enable_daily_summaries", True):
            tz = get_app_timezone()
            now = datetime.now(tz)
            scheduled = _parse_schedule_time(cfg.get("daily_summary_schedule_time"))
            today_firing = now.replace(hour=scheduled.hour, minute=scheduled.minute, second=0, microsecond=0)
            if now >= today_firing and not _today_summary_exists(now.date()):
                logger.info("Startup catch-up: scheduled time has passed and no summary exists for today")
                await _generate_for_today()
    except Exception:
        logger.exception("Daily summary scheduler startup catch-up failed")

    while not shutdown.is_set():
        try:
            cfg = get_config()
            scheduled = _parse_schedule_time(cfg.get("daily_summary_schedule_time"))
            tz = get_app_timezone()
            now = datetime.now(tz)
            firing_at = _next_firing(now, scheduled)
            wait_seconds = max(_MIN_WAIT_SECONDS, (firing_at - now).total_seconds())
            logger.debug(
                "Daily summary scheduler sleeping %.0fs until %s",
                wait_seconds,
                firing_at.isoformat(),
            )

            try:
                await asyncio.wait_for(shutdown.wait(), timeout=wait_seconds)
                # shutdown fired — exit
                return
            except TimeoutError:
                pass  # normal: woke up at scheduled time

            cfg = get_config()
            if cfg.get("daily_summary_provider", "disabled") == "disabled":
                logger.debug("Daily summary scheduler firing skipped: provider disabled")
                continue
            if not cfg.get("enable_daily_summaries", True):
                logger.debug("Daily summary scheduler firing skipped: daily summaries off")
                continue

            await _generate_for_today()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Daily summary scheduler loop error; backing off")
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=_FAILURE_BACKOFF_SECONDS)
                return
            except TimeoutError:
                pass

    logger.info("Daily summary scheduler stopped")
