"""Summary endpoints: monthly overview and multi-month trend."""

import asyncio
import logging
from datetime import date
from typing import TYPE_CHECKING, Any, cast

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, Query

from src.api.dependencies import (
    get_forecast_service,
    get_merchant_alias_service,
    get_spending_summary,
    get_upcoming_service,
    run_sync,
)
from src.api.models import (
    CategorySummary,
    CompanySummary,
    DepositSourceSummary,
    MonthPaceInfo,
    MonthSummary,
    SummaryComparisonResponse,
    TopCategory,
    TrendMonthEntry,
    TrendResponse,
)
from src.api.utils import MONTH_PATTERN
from src.finance import forecast_service
from src.finance.demo_clock import app_today
from src.finance.forecast_service import ForecastService, ForecastTables
from src.finance.merchant_normalizer import normalize_merchant
from src.finance.protocols import ISpendingSummary, TransactionItem

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

router = APIRouter(tags=["summary"])


def _convert_by_category(raw: dict[str, Any]) -> dict[str, CategorySummary]:
    """Convert raw by_category dict (with Decimals) to CategorySummary models."""
    return {
        k: CategorySummary(amount=float(v["amount"]), count=v["count"]) for k, v in raw.get("by_category", {}).items()
    }


def _to_month_summary(raw: dict[str, Any]) -> MonthSummary:
    """Convert a raw SpendingSummary dict (with Decimals) to a MonthSummary model."""
    by_category = _convert_by_category(raw)
    by_company = {
        k: CompanySummary(amount=float(v["amount"]), count=v["count"], category=v.get("category", ""))
        for k, v in raw.get("by_company", {}).items()
    }
    deposits_by_company = {
        k: DepositSourceSummary(amount=float(v["amount"]), count=v["count"])
        for k, v in raw.get("deposits_by_company", {}).items()
    }
    # top_categories comes as list of (name, {amount, count}) tuples
    top_categories = [
        TopCategory(name=name, amount=float(info["amount"]), count=info["count"])
        for name, info in raw.get("top_categories", [])
    ]

    return MonthSummary(
        year_month=raw["year_month"],
        total_spending=float(raw["total_spending"]),
        spending_count=raw["spending_count"],
        deposit_total=float(raw["deposit_total"]),
        deposit_count=raw["deposit_count"],
        by_category=by_category,
        by_company=by_company,
        deposits_by_company=deposits_by_company,
        top_categories=top_categories,
    )


@router.get(
    "/summary",
    response_model=SummaryComparisonResponse,
    operation_id="getMonthlySummary",
    summary="Monthly spending summary with previous-month comparison",
)
async def get_summary(
    month: str = Query(..., pattern=MONTH_PATTERN),
    summary: ISpendingSummary = Depends(get_spending_summary),
    forecast_svc: ForecastService = Depends(get_forecast_service),
):
    raw = await run_sync(summary.get_summary_with_comparison, month)
    current = _to_month_summary(raw["current"])
    response = SummaryComparisonResponse(
        current=current,
        previous=_to_month_summary(raw["previous"]),
        delta_amount=float(raw["delta_amount"]),
        delta_percent=float(raw["delta_percent"]),
    )

    # Mid-month pace — only for the current month, and fail-open: any error
    # leaves ``pace`` None with the rest of the response intact (mirrors
    # budget.py's forecast block). Past/future months issue no forecast queries.
    today = app_today()
    if month == today.strftime("%Y-%m"):
        try:
            keys = forecast_service.month_keys(today)
            window = forecast_service.window_key(keys)
            window_results: list[list[TransactionItem]] | None = None

            def _build_tables() -> forecast_service.ForecastTables:
                nonlocal window_results
                results = [summary.query_month(ym, forecast_service.FORECAST_PROJECTION) for ym in keys]
                window_results = results
                return forecast_service.build_tables(dict(zip(keys, results, strict=True)))

            # Single-flight: get_or_build runs on a worker thread (via run_sync),
            # so its threading.Lock never blocks the event loop, and concurrent
            # cold-cache requests build the window at most once. The builder
            # queries months synchronously inside that one worker call; when this
            # request wins the build, the raw rows are kept (window_results) so
            # _commitment_pace can derive the discretionary tables without
            # re-querying the window. Losers leave it None and fall back to the
            # disc cache or a re-query there.
            tables = await run_sync(forecast_svc.get_or_build, window, _build_tables)
            fields = forecast_service.compute_month_pace(tables, current.total_spending, current.spending_count, today)
            response.pace = MonthPaceInfo(**fields) if fields is not None else None

            # Commitment-aware upgrade (L6). Inner fail-open: any error here
            # leaves the curve-only pace above intact (pace non-null, breakdown
            # null) — the upcoming derivation must never sink the summary.
            try:
                response.pace = (
                    await _commitment_pace(
                        month, today, keys, window, current, tables, window_results, summary, forecast_svc
                    )
                    or response.pace
                )
            except Exception:
                logger.exception("Commitment-aware pace failed — falling back to curve-only pace")
        except Exception:
            logger.exception("Pace computation failed — returning summary without pace")
            response.pace = None

    return response


async def _commitment_pace(
    month: str,
    today: date,
    keys: list[str],
    window: str,
    current: MonthSummary,
    tables: ForecastTables,
    window_results: list[list[TransactionItem]] | None,
    summary: ISpendingSummary,
    forecast_svc: ForecastService,
) -> MonthPaceInfo | None:
    """Build the commitment-aware ``MonthPaceInfo`` (L5/L6), or ``None`` to keep
    the curve-only pace.

    ``UpcomingService`` and the alias service are synchronous — a cache miss on
    the former fans out 14 storage queries — so both are driven through
    ``run_sync`` off the event loop (src/api/CLAUDE.md). Fail-open: any error
    propagates to the caller's inner try/except, which keeps the curve-only
    pace. The discretionary tables reuse the already-fetched window rows (or a
    cached build) so only one extra current-month query is issued per request.
    """
    upcoming = await run_sync(get_upcoming_service().get_upcoming, month)
    if not upcoming.charges:
        return None

    disc_tables = forecast_svc.get_cached_discretionary(window)
    if disc_tables is None:
        if window_results is None:
            window_results = list(
                await asyncio.gather(
                    *[run_sync(summary.query_month, ym, forecast_service.FORECAST_PROJECTION) for ym in keys]
                )
            )
        aliases = await run_sync(get_merchant_alias_service().get_aliases_map)
        disc_by_month = {
            ym: [
                row
                for row in rows
                if normalize_merchant(str(row.get("Company") or ""), aliases) not in upcoming.recurring_merchants
            ]
            for ym, rows in zip(keys, window_results, strict=True)
        }
        disc_tables = forecast_service.build_tables(disc_by_month)
        forecast_svc.store_discretionary(window, disc_tables)

    current_items = await run_sync(summary.query_month, month, forecast_service.FORECAST_PROJECTION)
    fields = forecast_service.compute_commitment_pace(
        tables,
        disc_tables,
        upcoming,
        current.total_spending,
        current.spending_count,
        cast("list[Mapping[str, Any]]", current_items),
        today,
    )
    return MonthPaceInfo(**fields) if fields is not None else None


@router.get(
    "/summary/trend",
    response_model=TrendResponse,
    operation_id="getSpendingTrend",
    summary="Multi-month spending trend (2-12 months)",
)
async def get_trend(
    months: int = Query(6, ge=2, le=12),
    end_month: str | None = Query(None, pattern=MONTH_PATTERN),
    summary: ISpendingSummary = Depends(get_spending_summary),
):
    # Build month keys backwards from end_month (or today), oldest-first
    if end_month:
        y, m = end_month.split("-")
        current = date(int(y), int(m), 1)
    else:
        today = app_today()
        current = date(today.year, today.month, 1)
    month_keys = []
    for i in range(months - 1, -1, -1):
        d = current - relativedelta(months=i)
        month_keys.append(d.strftime("%Y-%m"))

    # Fetch all summaries concurrently
    results = await asyncio.gather(*[run_sync(summary.get_summary, ym) for ym in month_keys])

    entries = [
        TrendMonthEntry(
            year_month=raw["year_month"],
            total_spending=float(raw["total_spending"]),
            spending_count=raw["spending_count"],
            by_category=_convert_by_category(raw),
        )
        for raw in results
    ]

    return TrendResponse(months=entries)
