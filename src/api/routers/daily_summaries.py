"""Daily summary endpoints: generate, status, and retrieve AI day summaries."""

import asyncio
import logging
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import get_budget_service, get_spending_summary, get_upcoming_service, run_sync
from src.api.models.daily_summary import (
    DaySummariesResponse,
    DaySummaryGenerateRequest,
    DaySummaryGenerateResponse,
    DaySummaryStatusResponse,
)
from src.api.serializers import PROJECTION_NAMES, TRANSACTION_LIST_PROJECTION
from src.api.utils import MONTH_PATTERN
from src.finance.app_config import get_config
from src.finance.daily_summary_context import gather_daily_contexts
from src.finance.insights_context import gather_context as gather_insights_context
from src.finance.protocols import IBudgetService, ISpendingSummary
from src.finance.spending_aggregator import SPENDING_TYPES

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

_WORD_COUNT_WARN_THRESHOLD = 35  # ~10 words slack over the 25-word target

router = APIRouter(tags=["daily-summaries"])

# --- Background generation state (single-user, single slot) ---

_generation_state: dict[str, Any] = {"status": "idle"}
_generation_task: asyncio.Task[None] | None = None

_SUMMARIES_DIR = Path("data/journal")


def _summaries_dir(month: str) -> Path:
    return _SUMMARIES_DIR / month


def _read_saved_summaries(month: str) -> dict[str, str]:
    """Read all saved daily summaries for a month."""
    d = _summaries_dir(month)
    if not d.is_dir():
        return {}
    summaries: dict[str, str] = {}
    for f in d.glob("*.txt"):
        date_str = f"{month}-{f.stem}"  # stem is DD, e.g. "15"
        summaries[date_str] = f.read_text().strip()
    return summaries


@router.get(
    "/journal/summaries",
    response_model=DaySummariesResponse,
    operation_id="listDaySummaries",
    summary="List saved AI day summaries for a month",
)
async def get_summaries(month: str = Query(..., pattern=MONTH_PATTERN)):
    return DaySummariesResponse(month=month, summaries=_read_saved_summaries(month))


@router.get(
    "/journal/summaries/status",
    response_model=DaySummaryStatusResponse,
    operation_id="getDaySummaryGenerationStatus",
    summary="Background generation status (idle/running/error)",
)
async def get_status() -> dict[str, Any]:
    return _generation_state


@router.post(
    "/journal/summaries/generate",
    status_code=202,
    response_model=DaySummaryGenerateResponse,
    operation_id="generateDaySummaries",
    summary="Kick off background AI generation of day summaries for a month",
)
async def generate_summaries(
    body: DaySummaryGenerateRequest,
    summary: ISpendingSummary = Depends(get_spending_summary),
    budget_svc: IBudgetService = Depends(get_budget_service),
):
    return await kick_off_generation(
        month=body.month,
        dates=body.dates,
        force=body.force,
        summary=summary,
        budget_svc=budget_svc,
        # Manual, user-initiated request: the auto-generate toggle only governs
        # the background scheduler, so an on-demand Summarize click must work
        # regardless of whether daily summaries are set to auto-generate.
        enforce_daily_toggle=False,
    )


async def kick_off_generation(
    *,
    month: str,
    dates: list[str] | None,
    force: bool,
    summary: ISpendingSummary,
    budget_svc: IBudgetService,
    enforce_daily_toggle: bool = True,
) -> DaySummaryGenerateResponse:
    """Validate config, build contexts, spawn background generation.

    Pure async — callable from the HTTP handler and from the scheduler. Raises
    HTTPException on user-facing errors (provider disabled, summaries off,
    generation already running) so the HTTP layer surfaces them unchanged.

    ``enforce_daily_toggle`` gates the ``enable_daily_summaries`` check. The
    scheduler passes ``True`` (that toggle governs *automatic* generation); the
    HTTP handler passes ``False`` so an explicit user-initiated Summarize click
    works even when auto-generation is off — the toggle only controls the
    scheduler, not on-demand requests.
    """
    global _generation_task, _generation_state

    if _generation_state["status"] == "running":
        raise HTTPException(409, "Generation already in progress")
    # Claim the slot BEFORE the first await — two concurrent kickoffs must not
    # both pass the check (single event loop: no await between check and set).
    # Every early exit below resets the slot to idle first; the enclosing
    # try/except releases it on any raised HTTPException too.
    _generation_state = {"status": "running", "month": month, "completed": 0, "total": 0}
    try:
        config = get_config()
        provider_name = config.get("daily_summary_provider", "disabled")
        if provider_name == "disabled":
            raise HTTPException(400, "No daily summary provider is configured. Choose one in Settings → Intelligence.")
        model = config.get("daily_summary_model")
        reasoning_effort = config.get("daily_summary_reasoning_effort")
        if enforce_daily_toggle and not config.get("enable_daily_summaries", True):
            raise HTTPException(400, "Daily journal summaries are turned off in Settings.")

        items = await run_sync(summary.query_month, month, TRANSACTION_LIST_PROJECTION, PROJECTION_NAMES)
        active = [i for i in items if not i.get("DeletedAt") and not i.get("Ignored")]

        by_day: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for item in active:
            day_key = item["DateFileName"][:10].replace(".", "-")
            by_day[day_key].append(item)

        if not by_day:
            _generation_state = {"status": "idle"}
            return DaySummaryGenerateResponse(status="idle", month=month, dates_queued=0)

        mtd = 0.0
        journal_days = []
        for day_key in sorted(by_day):
            day_items = by_day[day_key]
            day_spending = sum(
                float(i.get("Amount") or 0) for i in day_items if i.get("TransactionType") in SPENDING_TYPES
            )
            mtd += day_spending
            journal_days.append(
                {
                    "date": day_key,
                    "day_total": round(day_spending, 2),
                    "count": len(day_items),
                    "mtd_total": round(mtd, 2),
                    "transactions": [
                        {
                            "company": i.get("Company") or "Unknown",
                            "amount": float(i.get("Amount") or 0),
                            "category": i.get("Category") or "Miscellaneous",
                        }
                        for i in day_items
                    ],
                }
            )

        year = int(month.split("-", 1)[0])
        ceiling = None
        targets = await run_sync(budget_svc.get_targets, year)
        if targets:
            raw_ceiling = targets.get("Data", {}).get("spending_ceiling")
            if raw_ceiling:
                ceiling = round(float(raw_ceiling) / 12, 2)

        # Best-effort enrichment with the monthly insights context (6-month trend,
        # anomalies, category deltas). Falls back to thin context on any failure
        # so a transient query error doesn't sink the whole generation.
        monthly_ctx: dict[str, Any] | None = None
        try:
            monthly_ctx = await gather_insights_context(month, spending_summary=summary, budget_service=budget_svc)
        except Exception:
            logger.exception("Failed to gather monthly insights context for %s; using thin context", month)

        # Day-before heads-up map (L15): expected charges keyed by landing date,
        # from the upcoming service. Fail-open — a derivation error simply drops
        # the ``upcoming_tomorrow`` line, never sinking generation.
        upcoming_by_date: dict[str, list[dict[str, Any]]] | None = None
        try:
            upcoming = await run_sync(get_upcoming_service().get_upcoming, month)
            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for charge in upcoming.charges:
                # Only charges that haven't posted yet are a genuine heads-up.
                if charge.status not in ("upcoming", "assumed"):
                    continue
                key = f"{month}-{charge.expected_day:02d}"
                # ``display_name`` is already title-cased by the upcoming service
                # (the ``_display_company`` convention), so it is prompt-ready.
                grouped[key].append(
                    {
                        "display_name": charge.display_name,
                        "amount_estimate": charge.amount_estimate,
                        "channel": charge.channel,
                        "expected_day": charge.expected_day,
                    }
                )
            upcoming_by_date = dict(grouped)
        except Exception:
            logger.exception("Upcoming-charge derivation failed for %s; omitting day-before heads-up", month)

        contexts = gather_daily_contexts(
            journal_days,
            budget_ceiling=ceiling,
            monthly_context=monthly_ctx,
            upcoming_by_date=upcoming_by_date,
        )

        saved = _read_saved_summaries(month)
        if dates:
            target_dates = set(dates)
        else:
            target_dates = {ctx["date"] for ctx in contexts}

        if not force:
            target_dates -= set(saved.keys())

        if not target_dates:
            _generation_state = {"status": "idle"}
            return DaySummaryGenerateResponse(status="idle", month=month, dates_queued=0)

        to_generate = [ctx for ctx in contexts if ctx["date"] in target_dates]

        _generation_state = {
            "status": "running",
            "month": month,
            "completed": 0,
            "total": len(to_generate),
        }
        _generation_task = asyncio.create_task(
            _run_generation(month, to_generate, provider_name, model, reasoning_effort)
        )
        return DaySummaryGenerateResponse(status="running", month=month, dates_queued=len(to_generate))
    except BaseException:
        _generation_state = {"status": "idle"}
        raise


async def _run_generation(
    month: str,
    day_contexts: list[dict[str, Any]],
    provider_name: str,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> None:
    global _generation_state
    try:
        from src.finance.summary_provider import create_summary_provider

        provider = create_summary_provider(provider_name, model, reasoning_effort)
        if provider is None:
            _generation_state = {
                "status": "error",
                "month": month,
                "error": f"Provider '{provider_name}' is not available. Check configuration.",
            }
            return

        def on_complete(date: str, text: str):
            word_count = len(text.split())
            if word_count > _WORD_COUNT_WARN_THRESHOLD:
                logger.warning(
                    "Daily summary for %s exceeded word target (%d words): %r",
                    date,
                    word_count,
                    text[:120],
                )
            _save_summary(month, date, text)
            _generation_state["completed"] = _generation_state.get("completed", 0) + 1

        await provider.generate_summaries(day_contexts, on_complete=on_complete)
        _generation_state = {"status": "idle"}
        logger.info("Daily summary generation complete for %s", month)

    except Exception as e:
        logger.exception("Daily summary generation error")
        _generation_state = {
            "status": "error",
            "month": month,
            "error": str(e)[:200],
        }


def _save_summary(month: str, date: str, text: str) -> None:
    """Save a single day's summary to disk."""
    d = _summaries_dir(month)
    d.mkdir(parents=True, exist_ok=True)
    day = date.split("-")[2]  # "15" from "2026-04-15"
    filepath = d / f"{day}.txt"
    filepath.write_text(text)
    logger.debug("Saved summary for %s to %s", date, filepath)
