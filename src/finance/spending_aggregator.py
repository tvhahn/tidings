"""Shared spending aggregation logic used by both DynamoDB and SQLite summary classes."""

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

SPENDING_TYPES = {"purchase", "withdrawal", "preauth", "e-transfer"}
DEPOSIT_TYPES = {"deposit"}


def aggregate(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate a list of transaction items (PascalCase keys) into a spending summary.

    Returns dict with total_spending, spending_count, deposit_total,
    deposit_count, by_category, by_company, deposits_by_company, and top_categories.
    """
    total_spending = Decimal(0)
    spending_count = 0
    deposit_total = Decimal(0)
    deposit_count = 0
    by_category: dict[str, dict[str, Any]] = {}
    by_company: dict[str, dict[str, Any]] = {}
    deposits_by_company: dict[str, dict[str, Any]] = {}

    for item in items:
        if item.get("DeletedAt"):
            continue
        if item.get("Ignored"):
            continue
        amount = item.get("Amount")
        txn_type = item.get("TransactionType")
        if amount is None or txn_type is None:
            continue

        amount = Decimal(str(amount))
        category = item.get("Category") or "miscellaneous"
        company = item.get("Company") or "Unknown"

        if txn_type in SPENDING_TYPES:
            total_spending += amount
            spending_count += 1

            if category not in by_category:
                by_category[category] = {"amount": Decimal(0), "count": 0}
            by_category[category]["amount"] += amount
            by_category[category]["count"] += 1

            if company not in by_company:
                by_company[company] = {"amount": Decimal(0), "count": 0, "category": category}
            by_company[company]["amount"] += amount
            by_company[company]["count"] += 1

        elif txn_type in DEPOSIT_TYPES:
            deposit_total += amount
            deposit_count += 1

            if company not in deposits_by_company:
                deposits_by_company[company] = {"amount": Decimal(0), "count": 0}
            deposits_by_company[company]["amount"] += amount
            deposits_by_company[company]["count"] += 1

    top_categories = sorted(by_category.items(), key=lambda x: x[1]["amount"], reverse=True)[:5]

    return {
        "total_spending": total_spending,
        "spending_count": spending_count,
        "deposit_total": deposit_total,
        "deposit_count": deposit_count,
        "by_category": by_category,
        "by_company": by_company,
        "deposits_by_company": deposits_by_company,
        "top_categories": top_categories,
    }
