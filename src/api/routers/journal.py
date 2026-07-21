"""Journal endpoint: day-grouped transaction timeline with enrichment context."""

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Query

from src.api.dependencies import get_budget_service, get_spending_summary, run_sync
from src.api.models import JournalDay, JournalResponse
from src.api.serializers import PROJECTION_NAMES, TRANSACTION_LIST_PROJECTION, to_transaction_response
from src.api.utils import MONTH_PATTERN
from src.finance.protocols import IBudgetService, ISpendingSummary
from src.finance.spending_aggregator import SPENDING_TYPES

if TYPE_CHECKING:
    from collections.abc import Mapping

router = APIRouter(tags=["journal"])


@router.get(
    "/journal",
    response_model=JournalResponse,
    operation_id="getJournal",
    summary="Day-grouped transaction timeline for a month",
)
async def get_journal(
    month: str = Query(..., pattern=MONTH_PATTERN),
    summary: ISpendingSummary = Depends(get_spending_summary),
    budget_svc: IBudgetService = Depends(get_budget_service),
):
    items = await run_sync(summary.query_month, month, TRANSACTION_LIST_PROJECTION, PROJECTION_NAMES)

    # Journal is the end-user "daily read" view, so we show only actionable
    # spending rows: active (non-deleted/non-ignored), a spending-type txn, and
    # a positive amount. This keeps each day's transaction list consistent with
    # its day_total — non-spending (refunds, deposits, transfers) and $0
    # placeholder rows live on the Transactions page instead.
    active = [
        i
        for i in items
        if not i.get("DeletedAt")
        and not i.get("Ignored")
        and i.get("TransactionType") in SPENDING_TYPES
        and float(i.get("Amount") or 0) > 0
    ]

    # Group by day using DateFileName prefix (YYYY.MM.DD)
    by_day: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in active:
        day_key = item["DateFileName"][:10].replace(".", "-")
        by_day[day_key].append(item)

    # Build days ascending (for MTD accumulation), then reverse
    mtd = 0.0
    days: list[JournalDay] = []
    for day_key in sorted(by_day):
        day_items = by_day[day_key]
        day_items.sort(key=lambda x: x.get("DateFileName", ""), reverse=True)
        day_spending = sum(float(i.get("Amount", 0)) for i in day_items if i.get("TransactionType") in SPENDING_TYPES)
        mtd += day_spending
        days.append(
            JournalDay(
                date=day_key,
                day_total=round(day_spending, 2),
                count=len(day_items),
                mtd_total=round(mtd, 2),
                transactions=[to_transaction_response(i) for i in day_items],
            )
        )

    days.reverse()

    # Budget ceiling (optional) — spending_ceiling is annual, divide by 12
    year = int(month.split("-", maxsplit=1)[0])
    ceiling = None
    targets = await run_sync(budget_svc.get_targets, year)
    if targets:
        raw_ceiling = targets.get("Data", {}).get("spending_ceiling")
        if raw_ceiling:
            ceiling = round(float(raw_ceiling) / 12, 2)

    return JournalResponse(
        month=month,
        days=days,
        month_total=round(mtd, 2),
        transaction_count=len(active),
        budget_ceiling=ceiling,
    )
