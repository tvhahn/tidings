"""Income statement service: annual income vs. expenses view."""

import logging
from decimal import Decimal
from typing import Any

from src.finance.merchant_normalizer import normalize_merchant
from src.finance.protocols import IBudgetService, ISpendingSummary

logger = logging.getLogger(__name__)

MONTH_LABELS = [f"{m:02d}" for m in range(1, 13)]

SPENDING_TYPE_DISPLAY = {
    "fixed": "Fixed expenses",
    "variable": "Variable expenses",
    "lumpy": "Irregular / one-time",
}

SPENDING_TYPE_ORDER = ["fixed", "variable", "lumpy"]


class IncomeStatementService:
    """Compose SpendingSummary + BudgetService to build annual income statement."""

    def __init__(
        self,
        spending_summary: ISpendingSummary,
        budget_service: IBudgetService,
        merchant_aliases: dict[str, str] | None = None,
    ):
        self.spending_summary = spending_summary
        self.budget_service = budget_service
        self.merchant_aliases = merchant_aliases or {}

    def get_income_statement(self, year: int, monthly_summaries: list[dict[str, Any]]) -> dict[str, Any]:
        """Build the full annual income statement for the given year.

        ``monthly_summaries`` is the 12 pre-fetched month summaries in calendar
        order (Jan..Dec). The router gathers them concurrently (one ``run_sync``
        per month) so the DynamoDB month queries don't run sequentially inside a
        single worker thread; the service keeps the aggregation order intact.
        """
        months = [f"{year}-{m:02d}" for m in range(1, 13)]

        # Get category type classification
        category_types = self._get_category_types(year)

        # Build income section
        income = self._build_income_section(monthly_summaries, months)

        # Build expense sections grouped by type
        expense_sections = self._build_expense_sections(monthly_summaries, months, category_types)

        # Compute totals
        total_expenses_monthly = [float(Decimal(0))] * 12
        for section in expense_sections:
            for i, val in enumerate(section["monthly_totals"]):
                total_expenses_monthly[i] += val
        total_expenses_annual = sum(total_expenses_monthly)

        net_monthly = [income["monthly_totals"][i] - total_expenses_monthly[i] for i in range(12)]
        net_annual = income["annual_total"] - total_expenses_annual

        savings_rate_monthly = []
        for i in range(12):
            inc = income["monthly_totals"][i]
            if inc > 0:
                savings_rate_monthly.append(round(net_monthly[i] / inc * 100, 1))
            else:
                savings_rate_monthly.append(None)

        savings_rate_annual = None
        if income["annual_total"] > 0:
            savings_rate_annual = round(net_annual / income["annual_total"] * 100, 1)

        # Projection
        projection = self._compute_projection(income, total_expenses_annual, net_annual, monthly_summaries)

        # Committed floor (sum of fixed expense totals)
        committed_floor = 0.0
        for section in expense_sections:
            if section["type_name"] == "fixed":
                committed_floor = section["annual_total"]
                break

        return {
            "year": year,
            "months": months,
            "income": income,
            "expense_sections": expense_sections,
            "total_expenses_monthly": [round(v, 2) for v in total_expenses_monthly],
            "total_expenses_annual": round(total_expenses_annual, 2),
            "net_monthly": [round(v, 2) for v in net_monthly],
            "net_annual": round(net_annual, 2),
            "savings_rate_monthly": savings_rate_monthly,
            "savings_rate_annual": savings_rate_annual,
            "projection": projection,
            "committed_floor": round(committed_floor, 2),
        }

    def _get_category_types(self, year: int) -> dict[str, str]:
        """Get category type mapping from budget config, with fallback to inference."""
        types: dict[str, str] = {}

        # Try budget targets first
        targets_item = self.budget_service.get_targets(year)
        if targets_item:
            data = targets_item.get("Data", {})
            categories = data.get("categories", {})
            for cat, config in categories.items():
                ct = config.get("category_type", "variable")
                types[cat] = ct

        # Fallback: use historical averages for categories not in budget
        try:
            hist = self.budget_service.get_historical_averages(self.spending_summary, months=6)
            for cat, info in hist.get("categories", {}).items():
                if cat not in types:
                    types[cat] = info.get("suggested_type", "variable")
        except Exception:
            logger.exception("Failed to get historical averages for type inference")

        return types

    def _build_income_section(self, summaries: list[dict[str, Any]], months: list[str]) -> dict[str, Any]:
        """Build income section with per-company breakdown."""
        company_data: dict[str, list[float]] = {}
        monthly_totals = []

        for i, summary in enumerate(summaries):
            deposit_total = float(summary.get("deposit_total", Decimal(0)))
            monthly_totals.append(round(deposit_total, 2))

            for raw_company, info in summary.get("deposits_by_company", {}).items():
                company = normalize_merchant(raw_company, self.merchant_aliases)
                if company not in company_data:
                    company_data[company] = [0.0] * 12
                company_data[company][i] += round(float(info["amount"]), 2)

        companies = []
        for company, month_vals in sorted(company_data.items(), key=lambda x: sum(x[1]), reverse=True):
            companies.append(
                {
                    "company": company,
                    "months": month_vals,
                    "total": round(sum(month_vals), 2),
                }
            )

        return {
            "companies": companies,
            "monthly_totals": monthly_totals,
            "annual_total": round(sum(monthly_totals), 2),
        }

    def _build_expense_sections(
        self,
        summaries: list[dict[str, Any]],
        months: list[str],
        category_types: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Build expense sections grouped by spending type (fixed/variable/lumpy)."""
        # Aggregate category + company data across months
        cat_monthly: dict[str, list[float]] = {}
        cat_companies: dict[str, dict[str, list[float]]] = {}

        for i, summary in enumerate(summaries):
            for cat, info in summary.get("by_category", {}).items():
                if cat not in cat_monthly:
                    cat_monthly[cat] = [0.0] * 12
                cat_monthly[cat][i] = round(float(info["amount"]), 2)

            for raw_company, info in summary.get("by_company", {}).items():
                company = normalize_merchant(raw_company, self.merchant_aliases)
                cat = info.get("category", "miscellaneous")
                if cat not in cat_companies:
                    cat_companies[cat] = {}
                if company not in cat_companies[cat]:
                    cat_companies[cat][company] = [0.0] * 12
                cat_companies[cat][company][i] += round(float(info["amount"]), 2)

        # Group categories by type
        sections = []
        for type_name in SPENDING_TYPE_ORDER:
            categories = []
            for cat, month_vals in sorted(cat_monthly.items(), key=lambda x: sum(x[1]), reverse=True):
                cat_type = category_types.get(cat, "variable")
                if cat_type != type_name:
                    continue

                # Build company sub-rows
                companies = []
                for comp, comp_vals in sorted(
                    cat_companies.get(cat, {}).items(),
                    key=lambda x: sum(x[1]),
                    reverse=True,
                ):
                    companies.append(
                        {
                            "company": comp,
                            "months": comp_vals,
                            "total": round(sum(comp_vals), 2),
                        }
                    )

                categories.append(
                    {
                        "category": cat,
                        "months": month_vals,
                        "total": round(sum(month_vals), 2),
                        "companies": companies,
                    }
                )

            if not categories:
                continue

            section_monthly = [0.0] * 12
            for cat_row in categories:
                for i, val in enumerate(cat_row["months"]):
                    section_monthly[i] += val

            sections.append(
                {
                    "type_name": type_name,
                    "display_name": SPENDING_TYPE_DISPLAY.get(type_name, type_name),
                    "categories": categories,
                    "monthly_totals": [round(v, 2) for v in section_monthly],
                    "annual_total": round(sum(section_monthly), 2),
                }
            )

        return sections

    def _compute_projection(
        self,
        income: dict[str, Any],
        total_expenses_annual: float,
        net_annual: float,
        summaries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Compute YTD annualized projection."""
        # Count months with at least one transaction
        months_with_data = 0
        for summary in summaries:
            has_spending = summary.get("spending_count", 0) > 0
            has_deposits = summary.get("deposit_count", 0) > 0
            if has_spending or has_deposits:
                months_with_data += 1

        if months_with_data == 0:
            return {
                "annualized_income": 0.0,
                "annualized_expenses": 0.0,
                "annualized_net": 0.0,
                "months_elapsed": 0,
            }

        factor = 12 / months_with_data
        return {
            "annualized_income": round(income["annual_total"] * factor, 2),
            "annualized_expenses": round(total_expenses_annual * factor, 2),
            "annualized_net": round(net_annual * factor, 2),
            "months_elapsed": months_with_data,
        }
