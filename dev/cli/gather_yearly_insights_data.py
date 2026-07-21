"""Gather yearly spending context for AI yearly review analysis.

Usage:
    uv run dev/cli/gather_yearly_insights_data.py 2025
    uv run dev/cli/gather_yearly_insights_data.py 2025 -o path/to/output.json

Also importable:
    from dev.cli.gather_yearly_insights_data import gather_yearly_context

Storage-agnostic: services come from the ``src.finance.storage`` factory
functions, so this runs identically on the DynamoDB and SQLite backends
(whichever ``data/config.json`` selects).
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from src.finance.income_statement_service import IncomeStatementService
from src.finance.merchant_normalizer import normalize_merchant
from src.finance.protocols import (
    IBudgetService,
    IMerchantAliasService,
    ISpendingSummary,
)
from src.finance.storage import (
    create_budget_service,
    create_merchant_alias_service,
    create_spending_summary,
)


class _DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


def _strip_decimals(obj):
    """Recursively convert Decimal values to float in-place."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _strip_decimals(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_decimals(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_strip_decimals(v) for v in obj)
    return obj


def gather_yearly_context(
    year: int,
    output_path: str | None = None,
    spending_summary: ISpendingSummary | None = None,
    budget_service: IBudgetService | None = None,
    merchant_alias_service: IMerchantAliasService | None = None,
) -> dict:
    """Gather all spending context for the given year.

    Returns the context dict and writes to file.
    """
    if spending_summary is None:
        spending_summary = create_spending_summary()
    if budget_service is None:
        budget_service = create_budget_service()

    # Load merchant aliases for normalization
    if merchant_alias_service is None:
        merchant_alias_service = create_merchant_alias_service()
    try:
        merchant_aliases = merchant_alias_service.get_aliases_map()
    except Exception:
        merchant_aliases = {}

    months = [f"{year}-{m:02d}" for m in range(1, 13)]

    # Query all 12 months of raw items + summaries
    monthly_summaries = []
    all_raw_items: dict[str, list[dict]] = {}
    for ym in months:
        raw_items = spending_summary.query_month(ym)
        all_raw_items[ym] = raw_items
        summary = spending_summary.aggregate(raw_items)
        summary["year_month"] = ym
        monthly_summaries.append(summary)

    # Build monthly_summaries output (category-level only, no by_company per-month)
    monthly_output = []
    total_spending = Decimal("0")
    total_count = 0
    for summary in monthly_summaries:
        total_spending += summary["total_spending"]
        total_count += summary["spending_count"]
        monthly_output.append(
            {
                "year_month": summary["year_month"],
                "total_spending": summary["total_spending"],
                "spending_count": summary["spending_count"],
                "by_category": summary["by_category"],
            }
        )

    # Top merchants (aggregated across all 12 months)
    merchant_agg: dict[str, dict] = {}
    for summary in monthly_summaries:
        for raw_company, info in summary.get("by_company", {}).items():
            company = normalize_merchant(raw_company, merchant_aliases)
            if company not in merchant_agg:
                merchant_agg[company] = {
                    "total": Decimal("0"),
                    "count": 0,
                    "category": info.get("category", "miscellaneous"),
                }
            merchant_agg[company]["total"] += info["amount"]
            merchant_agg[company]["count"] += info["count"]

    top_merchants = sorted(merchant_agg.items(), key=lambda x: x[1]["total"], reverse=True)[:20]
    top_merchants_output = [
        {"company": company, "total": info["total"], "count": info["count"], "category": info["category"]}
        for company, info in top_merchants
    ]

    # Budget targets & actuals
    budget = None
    targets_item = budget_service.get_targets(year)
    if targets_item is not None:
        data = targets_item.get("Data", {})
        budget_categories = {}
        budget_cat_config = data.get("categories", {})

        # Compute annual actuals per category
        annual_by_category: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for summary in monthly_summaries:
            for cat, info in summary.get("by_category", {}).items():
                annual_by_category[cat] += info["amount"]

        for cat, config in budget_cat_config.items():
            target = config.get("target", Decimal("0"))
            actual = annual_by_category.get(cat, Decimal("0"))
            variance = actual - target
            variance_pct = float(variance / target * 100) if target else 0.0
            budget_categories[cat] = {
                "target": target,
                "monthly_amount": config.get("monthly_amount", Decimal("0")),
                "category_type": config.get("category_type", "variable"),
                "actual": actual,
                "variance": variance,
                "variance_pct": round(variance_pct, 1),
            }

        budget = {
            "spending_ceiling": data.get("spending_ceiling", 0),
            "categories": budget_categories,
        }

    # Income & savings via IncomeStatementService
    income_service = IncomeStatementService(spending_summary, budget_service, merchant_aliases=merchant_aliases)
    income_stmt = income_service.get_income_statement(year)

    income = {
        "annual_total": income_stmt["income"]["annual_total"],
        "sources": income_stmt["income"]["companies"],
        "monthly_totals": income_stmt["income"]["monthly_totals"],
    }

    # Annual summary
    net_savings = income["annual_total"] - float(total_spending)
    savings_rate = None
    if income["annual_total"] > 0:
        savings_rate = round(net_savings / income["annual_total"] * 100, 1)

    # Committed floor (fixed expenses total)
    committed_floor = income_stmt.get("committed_floor", 0.0)

    annual_summary = {
        "total_spending": total_spending,
        "total_income": income["annual_total"],
        "net_savings": round(net_savings, 2),
        "savings_rate": savings_rate,
        "committed_floor": committed_floor,
        "transaction_count": total_count,
    }

    # Commented transactions across all 12 months
    commented_transactions = []
    for ym, items in all_raw_items.items():
        for item in items:
            if item.get("Comment") and not item.get("DeletedAt") and not item.get("Ignored"):
                commented_transactions.append(
                    {
                        "date": item.get("Date", ""),
                        "company": item.get("Company", ""),
                        "amount": item.get("Amount", 0),
                        "category": item.get("Category", ""),
                        "comment": item.get("Comment", ""),
                        "month": ym,
                    }
                )

    # Category types from budget config + historical inference
    category_types = _get_category_types(year, budget_service, spending_summary)

    context = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "year": year,
        "annual_summary": annual_summary,
        "monthly_summaries": monthly_output,
        "budget": budget,
        "income": income,
        "top_merchants": top_merchants_output,
        "commented_transactions": commented_transactions,
        "category_types": category_types,
    }

    # Strip all Decimal values for JSON serialization
    context = _strip_decimals(context)

    # Remove deposit data from monthly summaries (not spending)
    for summary in context["monthly_summaries"]:
        summary.pop("deposit_total", None)
        summary.pop("deposit_count", None)

    # Write output
    if output_path:
        out = Path(output_path)
    else:
        out = Path("data/insights/yearly") / str(year) / f"context_{year}.json"

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(context, f, indent=2, cls=_DecimalEncoder)
        f.write("\n")

    return context


def _get_category_types(
    year: int,
    budget_service: IBudgetService,
    spending_summary: ISpendingSummary,
) -> dict[str, str]:
    """Get category type mapping from budget config with historical fallback."""
    types: dict[str, str] = {}

    targets_item = budget_service.get_targets(year)
    if targets_item:
        data = targets_item.get("Data", {})
        for cat, config in data.get("categories", {}).items():
            types[cat] = config.get("category_type", "variable")

    try:
        hist = budget_service.get_historical_averages(spending_summary, months=6)
        for cat, info in hist.get("categories", {}).items():
            if cat not in types:
                types[cat] = info.get("suggested_type", "variable")
    except Exception:
        pass

    return types


def main():
    parser = argparse.ArgumentParser(description="Gather yearly spending context for insights")
    parser.add_argument(
        "year",
        type=int,
        help="Year to analyze (e.g. 2025)",
    )
    parser.add_argument("--output", "-o", help="Output file path")
    args = parser.parse_args()

    context = gather_yearly_context(args.year, output_path=args.output)
    out_path = args.output or f"data/insights/yearly/{args.year}/context_{args.year}.json"
    print(f"Context written to {out_path}")
    print(f"Year: {context['year']}")
    print(f"Total spending: ${context['annual_summary']['total_spending']:,.2f}")
    print(f"Total income: ${context['annual_summary']['total_income']:,.2f}")
    print(f"Net savings: ${context['annual_summary']['net_savings']:,.2f}")
    if context["annual_summary"]["savings_rate"] is not None:
        print(f"Savings rate: {context['annual_summary']['savings_rate']:.1f}%")
    print(f"Transactions: {context['annual_summary']['transaction_count']}")
    print(f"Top merchants: {len(context['top_merchants'])}")
    print(f"Commented transactions: {len(context['commented_transactions'])}")


if __name__ == "__main__":
    main()
