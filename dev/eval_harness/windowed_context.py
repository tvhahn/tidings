"""Build a daily AI context as-of (year_month, day_n).

Production batches the whole month into one prompt, so every day sees every
other day's transactions. The harness optimizes the per-day case: at 19:00 on
day N, what would we want to know? `gather_as_of(month, N)` answers that by
windowing all queries to ``date_file_name <= "<year-month>.<day_n>"``.

Reuses production helpers verbatim:
- ``gather_context``           (insights_context.py:64) — monthly trend/anomalies/deltas
- ``gather_daily_contexts``    (daily_summary_context.py:8) — per-day enrichment
- ``SpendingSummaryBase``      (spending_summary_base.py) — get_summary_with_comparison via query_month

Only ``query_month`` is overridden; the base class composes ``aggregate``,
``get_summary``, and ``get_summary_with_comparison`` on top of it, so the
windowing is transparent everywhere.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from src.finance.daily_summary_context import gather_daily_contexts
from src.finance.insights_context import gather_context
from src.finance.spending_aggregator import SPENDING_TYPES
from src.finance.spending_summary_base import SpendingSummaryBase
from src.finance.storage import create_budget_service, create_spending_summary

if TYPE_CHECKING:
    from src.finance.protocols import IBudgetService, ISpendingSummary


class WindowedSpendingSummary(SpendingSummaryBase):
    """Wrap an ``ISpendingSummary`` and filter ``query_month`` to a cutoff.

    The cutoff is a date_file_name prefix like ``"2026.04.14"`` (10 chars).
    Production date_file_name format is ``YYYY.MM.DD_<suffix>``, so a
    string compare on the first 10 chars is exact.

    Earlier months pass through unchanged (their full row set is always
    ``<= cutoff``), so ``get_summary_with_comparison`` continues to return a
    correct prior-month total.
    """

    def __init__(self, wrapped: ISpendingSummary, cutoff_date_prefix: str) -> None:
        self._wrapped = wrapped
        self._cutoff = cutoff_date_prefix

    def query_month(
        self,
        year_month: str,
        projection: str | None = None,
        expression_names: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        items = self._wrapped.query_month(year_month, projection, expression_names)
        return [it for it in items if it.get("DateFileName", "")[:10] <= self._cutoff]


def _cutoff_prefix(year_month: str, day_n: int) -> str:
    return f"{year_month.replace('-', '.')}.{day_n:02d}"


async def gather_as_of(
    year_month: str,
    day_n: int,
    *,
    spending_summary: ISpendingSummary | None = None,
    budget_service: IBudgetService | None = None,
) -> dict[str, Any]:
    """Return the daily context dict for ``(year_month, day_n)``.

    Anomalies and category deltas are computed using only transactions
    through day_n; trend/historical_averages are unaffected (already
    prior-window). Returns the same 17-key dict shape that
    ``gather_daily_contexts`` produces in production.

    Raises ``LookupError`` when day_n has no transactions in the underlying
    storage — the caller decides whether to skip or surface.
    """
    if spending_summary is None:
        spending_summary = create_spending_summary()
    if budget_service is None:
        budget_service = create_budget_service()

    cutoff = _cutoff_prefix(year_month, day_n)
    windowed = WindowedSpendingSummary(spending_summary, cutoff)

    items = await asyncio.to_thread(windowed.query_month, year_month)
    active = [i for i in items if not i.get("DeletedAt") and not i.get("Ignored")]
    if not active:
        raise LookupError(f"No transactions for {year_month} through day {day_n} in this storage backend.")

    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in active:
        day_key = item["DateFileName"][:10].replace(".", "-")
        by_day[day_key].append(item)

    target_date = f"{year_month}-{day_n:02d}"
    if target_date not in by_day:
        raise LookupError(f"No transactions on {target_date} (storage has earlier days but not this one).")

    mtd = 0.0
    journal_days: list[dict[str, Any]] = []
    for day_key in sorted(by_day):
        day_items = by_day[day_key]
        day_spending = sum(float(i.get("Amount") or 0) for i in day_items if i.get("TransactionType") in SPENDING_TYPES)
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
        if day_key == target_date:
            break

    year = int(year_month.split("-", 1)[0])
    ceiling: float | None = None
    targets = await asyncio.to_thread(budget_service.get_targets, year)
    if targets:
        raw_ceiling = targets.get("Data", {}).get("spending_ceiling")
        if raw_ceiling:
            ceiling = round(float(raw_ceiling) / 12, 2)

    monthly_ctx: dict[str, Any] | None = None
    try:
        monthly_ctx = await gather_context(year_month, spending_summary=windowed, budget_service=budget_service)
    except Exception:
        monthly_ctx = None

    prev_month_total = 0.0
    if monthly_ctx and monthly_ctx.get("previous_month"):
        prev_month_total = float(monthly_ctx["previous_month"].get("total_spending") or 0)

    contexts = gather_daily_contexts(
        journal_days,
        budget_ceiling=ceiling,
        prev_month_total=prev_month_total,
        monthly_context=monthly_ctx,
    )
    return contexts[-1]


def gather_as_of_sync(year_month: str, day_n: int) -> dict[str, Any]:
    """Sync wrapper around ``gather_as_of`` for CLI / non-async callers."""
    return asyncio.run(gather_as_of(year_month, day_n))


__all__ = ["WindowedSpendingSummary", "gather_as_of", "gather_as_of_sync"]
