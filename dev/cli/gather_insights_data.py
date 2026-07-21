"""Gather spending context for AI insights analysis and write it to disk.

Usage:
    uv run dev/cli/gather_insights_data.py [YYYY-MM]

The heavy lifting lives in ``src.finance.insights_context`` — the pure
``gather_context`` core plus the ``gather_context_to_file`` persistence
wrapper (which the API's generation worker also uses). This script is a thin
CLI wrapper that adds argparse. Importable for backward compatibility —
existing callers (including tests) that pass ``output_path`` continue to work
unchanged.
"""

import argparse
from datetime import date

from src.finance.budget_service import BudgetService
from src.finance.insights_context import gather_context_to_file
from src.finance.spending_summary import SpendingSummary


def gather_context(
    year_month: str,
    output_path: str | None = None,
    spending_summary: SpendingSummary | None = None,
    budget_service: BudgetService | None = None,
) -> dict:
    """Backward-compatible alias for ``insights_context.gather_context_to_file``."""
    return gather_context_to_file(
        year_month,
        output_path,
        spending_summary=spending_summary,
        budget_service=budget_service,
    )


def main():
    parser = argparse.ArgumentParser(description="Gather spending context for insights")
    parser.add_argument(
        "month",
        nargs="?",
        default=date.today().strftime("%Y-%m"),
        help="Month in YYYY-MM format (default: current month)",
    )
    parser.add_argument("--output", "-o", help="Output file path")
    args = parser.parse_args()

    context = gather_context(args.month, output_path=args.output)
    out_path = args.output or f"data/insights/context_{args.month}.json"
    print(f"Context written to {out_path}")
    print(f"Month: {context['month']}")
    print(f"Current spending: ${context['current_month']['total_spending']:,.2f}")
    print(f"Delta: {context['delta']['percent']:+.1f}%")


if __name__ == "__main__":
    main()
