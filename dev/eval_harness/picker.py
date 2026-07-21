"""Pick a diverse set of days from a month for prompt evaluation.

Per spec §6, ``pick_diverse_days(month)`` returns up to 6 dates covering:
  1. Single-transaction day
  2. ≥3 transactions across ≥3 distinct categories
  3. Day with the largest single transaction
  4. Saturday/Sunday with ≥2 transactions
  5. Day containing a transaction in a category flagged by
     ``BudgetService.get_category_anomalies(month, 6)``
  6. Bottom-quartile ``day_total``

Empty result is fine — the dev container's empty finance.db produces ``[]``.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.finance.spending_aggregator import SPENDING_TYPES
from src.finance.storage import create_budget_service, create_spending_summary

if TYPE_CHECKING:
    from datetime import date

    from src.finance.protocols import IBudgetService, ISpendingSummary

logger = logging.getLogger(__name__)


def _group_by_day(items: list[dict[str, Any]]) -> dict[date, list[dict[str, Any]]]:
    by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for it in items:
        if it.get("DeletedAt") or it.get("Ignored"):
            continue
        if it.get("TransactionType") not in SPENDING_TYPES:
            # Anomaly check still wants e-transfers + purchases for "did anything
            # happen on this day", so don't drop them when the heuristics look at
            # transaction count. We do drop them from spending totals further down.
            pass
        dfn = it.get("DateFileName", "")
        if len(dfn) < 10:
            continue
        try:
            d = datetime.strptime(dfn[:10], "%Y.%m.%d").date()
        except ValueError:
            continue
        by_day[d].append(it)
    return by_day


def _day_spending_total(day_items: list[dict[str, Any]]) -> float:
    return sum(float(i.get("Amount") or 0) for i in day_items if i.get("TransactionType") in SPENDING_TYPES)


def pick_diverse_days(
    year_month: str,
    *,
    spending_summary: ISpendingSummary | None = None,
    budget_service: IBudgetService | None = None,
    limit: int = 6,
) -> list[date]:
    """Return up to ``limit`` distinct dates from ``year_month`` matching the
    six diversity heuristics. Empty list when the month has no transactions."""
    if spending_summary is None:
        spending_summary = create_spending_summary()
    if budget_service is None:
        budget_service = create_budget_service()

    items = spending_summary.query_month(year_month)
    by_day = _group_by_day(items)
    if not by_day:
        return []

    picks: list[date] = []

    def _add(d: date) -> None:
        if d not in picks and len(picks) < limit:
            picks.append(d)

    # 1. Single-transaction day (using all txn types)
    single_txn_days = sorted(d for d, txns in by_day.items() if len(txns) == 1)
    if single_txn_days:
        _add(single_txn_days[0])

    # 2. ≥3 transactions across ≥3 distinct categories
    diverse_days = sorted(
        (d for d, txns in by_day.items() if len(txns) >= 3 and len({t.get("Category") for t in txns}) >= 3),
        key=lambda d: -len({t.get("Category") for t in by_day[d]}),
    )
    if diverse_days:
        _add(diverse_days[0])

    # 3. Day with the largest single transaction (purchases only)
    largest_day: date | None = None
    largest_amount = -1.0
    for d, txns in by_day.items():
        for t in txns:
            if t.get("TransactionType") not in SPENDING_TYPES:
                continue
            amt = float(t.get("Amount") or 0)
            if amt > largest_amount:
                largest_amount = amt
                largest_day = d
    if largest_day:
        _add(largest_day)

    # 4. Weekend with ≥2 transactions
    weekend_days = sorted(
        (d for d, txns in by_day.items() if d.weekday() >= 5 and len(txns) >= 2),
        key=lambda d: -len(by_day[d]),
    )
    if weekend_days:
        _add(weekend_days[0])

    # 5. Day containing a transaction in an anomalous category
    try:
        anomalies = budget_service.get_category_anomalies(spending_summary, year_month, 6)
    except Exception:
        logger.exception("get_category_anomalies failed; skipping anomaly heuristic")
        anomalies = []
    anomaly_categories = {a.get("category") for a in anomalies if a.get("category")}
    if anomaly_categories:
        for d in sorted(by_day):
            if any(t.get("Category") in anomaly_categories for t in by_day[d]):
                _add(d)
                break

    # 6. Bottom-quartile day_total (among days with at least one purchase)
    purchase_days = [(d, _day_spending_total(by_day[d])) for d in by_day]
    purchase_days = [(d, t) for d, t in purchase_days if t > 0]
    if purchase_days:
        purchase_days.sort(key=lambda x: x[1])
        cutoff_idx = max(0, len(purchase_days) // 4 - 1)
        _add(purchase_days[cutoff_idx][0])

    return picks
