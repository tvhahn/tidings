"""Tests for IncomeStatementService — aggregation, category type classification, projection."""

from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

from src.finance.income_statement_service import IncomeStatementService


def _make_month_summary(
    year_month: str,
    spending: float = 0,
    spending_count: int = 0,
    deposit: float = 0,
    deposit_count: int = 0,
    by_category: dict[str, Any] | None = None,
    by_company: dict[str, Any] | None = None,
    deposits_by_company: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "year_month": year_month,
        "total_spending": Decimal(str(spending)),
        "spending_count": spending_count,
        "deposit_total": Decimal(str(deposit)),
        "deposit_count": deposit_count,
        "by_category": by_category or {},
        "by_company": by_company or {},
        "deposits_by_company": deposits_by_company or {},
        "top_categories": [],
    }


def _summaries_for(month_data: dict[str, Any] | None, year: int = 2026) -> list[dict[str, Any]]:
    """Build the 12 pre-fetched month summaries (Jan..Dec) the service now expects.

    Mirrors what the router gathers via ``asyncio.gather`` before delegating to
    ``get_income_statement``; months absent from ``month_data`` fall back to an
    empty summary, exactly as ``spending_summary.get_summary`` would return.
    """
    data = month_data or {}
    return [data.get(f"{year}-{m:02d}", _make_month_summary(f"{year}-{m:02d}")) for m in range(1, 13)]


def _make_service(
    month_data: dict[str, Any] | None = None,
    targets: dict[str, Any] | None = None,
    hist_categories: dict[str, Any] | None = None,
    aliases: dict[str, str] | None = None,
) -> IncomeStatementService:
    """Build an IncomeStatementService with mocked dependencies."""
    spending_summary = MagicMock()
    budget_service = MagicMock()

    # Map month strings to their summaries
    summaries = month_data or {}
    spending_summary.get_summary.side_effect = lambda ym: summaries.get(
        ym,
        _make_month_summary(ym),
    )

    # Budget targets
    budget_service.get_targets.return_value = targets

    # Historical averages (for type inference fallback)
    hist = {"categories": hist_categories or {}}
    budget_service.get_historical_averages.return_value = hist

    return IncomeStatementService(spending_summary, budget_service, merchant_aliases=aliases)


class TestGetIncomeStatement:
    def test_empty_year(self) -> None:
        svc = _make_service()
        result = svc.get_income_statement(2026, _summaries_for(None))

        assert result["year"] == 2026
        assert len(result["months"]) == 12
        assert result["income"]["annual_total"] == 0.0
        assert result["total_expenses_annual"] == 0.0
        assert result["net_annual"] == 0.0
        assert result["savings_rate_annual"] is None
        assert result["projection"]["months_elapsed"] == 0

    def test_income_tracked_by_company(self) -> None:
        data = {
            "2026-01": _make_month_summary(
                "2026-01",
                deposit=3000,
                deposit_count=1,
                deposits_by_company={"Regional Health": {"amount": Decimal(3000), "count": 1}},
            ),
            "2026-02": _make_month_summary(
                "2026-02",
                deposit=3000,
                deposit_count=1,
                deposits_by_company={"Regional Health": {"amount": Decimal(3000), "count": 1}},
            ),
        }
        svc = _make_service(month_data=data)
        result = svc.get_income_statement(2026, _summaries_for(data))

        assert result["income"]["annual_total"] == 6000.0
        assert len(result["income"]["companies"]) == 1
        assert result["income"]["companies"][0]["company"] == "Regional Health"
        assert result["income"]["companies"][0]["total"] == 6000.0

    def test_expenses_grouped_by_category_type(self) -> None:
        targets = {
            "Data": {
                "categories": {
                    "rent": {"category_type": "fixed", "target": 12000, "monthly_amount": 1000},
                    "groceries": {"category_type": "variable", "target": 6000, "monthly_amount": 500},
                }
            }
        }
        data = {
            "2026-01": _make_month_summary(
                "2026-01",
                spending=1500,
                spending_count=5,
                by_category={
                    "rent": {"amount": Decimal(1000), "count": 1},
                    "groceries": {"amount": Decimal(500), "count": 4},
                },
                by_company={
                    "Landlord": {"amount": Decimal(1000), "count": 1, "category": "rent"},
                    "Safeway": {"amount": Decimal(500), "count": 4, "category": "groceries"},
                },
            ),
        }
        svc = _make_service(month_data=data, targets=targets)
        result = svc.get_income_statement(2026, _summaries_for(data))

        type_names = [s["type_name"] for s in result["expense_sections"]]
        assert "fixed" in type_names
        assert "variable" in type_names

        fixed_section = next(s for s in result["expense_sections"] if s["type_name"] == "fixed")
        assert fixed_section["annual_total"] == 1000.0
        assert fixed_section["categories"][0]["category"] == "rent"

    def test_net_and_savings_rate(self) -> None:
        data = {
            "2026-01": _make_month_summary(
                "2026-01",
                spending=800,
                spending_count=5,
                deposit=2000,
                deposit_count=1,
                by_category={"groceries": {"amount": Decimal(800), "count": 5}},
                by_company={"Store": {"amount": Decimal(800), "count": 5, "category": "groceries"}},
                deposits_by_company={"Employer": {"amount": Decimal(2000), "count": 1}},
            ),
        }
        svc = _make_service(month_data=data)
        result = svc.get_income_statement(2026, _summaries_for(data))

        assert result["income"]["annual_total"] == 2000.0
        assert result["total_expenses_annual"] == 800.0
        assert result["net_annual"] == 1200.0
        assert result["savings_rate_annual"] == 60.0

    def test_projection_calculation(self) -> None:
        # 3 months with data
        data = {}
        for i, m in enumerate(["2026-01", "2026-02", "2026-03"], 1):
            data[m] = _make_month_summary(
                m,
                spending=1000,
                spending_count=10,
                deposit=2000,
                deposit_count=1,
                by_category={"groceries": {"amount": Decimal(1000), "count": 10}},
                by_company={"Store": {"amount": Decimal(1000), "count": 10, "category": "groceries"}},
                deposits_by_company={"Employer": {"amount": Decimal(2000), "count": 1}},
            )
        svc = _make_service(month_data=data)
        result = svc.get_income_statement(2026, _summaries_for(data))

        proj = result["projection"]
        assert proj["months_elapsed"] == 3
        # 3 months of $2000 income = $6000 YTD → annualized = $24,000
        assert proj["annualized_income"] == 24000.0
        assert proj["annualized_expenses"] == 12000.0
        assert proj["annualized_net"] == 12000.0

    def test_committed_floor(self) -> None:
        targets = {
            "Data": {
                "categories": {
                    "rent": {"category_type": "fixed", "target": 12000, "monthly_amount": 1000},
                    "insurance": {"category_type": "fixed", "target": 1200, "monthly_amount": 100},
                    "groceries": {"category_type": "variable", "target": 6000, "monthly_amount": 500},
                }
            }
        }
        data = {
            "2026-01": _make_month_summary(
                "2026-01",
                spending=1600,
                spending_count=3,
                by_category={
                    "rent": {"amount": Decimal(1000), "count": 1},
                    "insurance": {"amount": Decimal(100), "count": 1},
                    "groceries": {"amount": Decimal(500), "count": 1},
                },
                by_company={
                    "Landlord": {"amount": Decimal(1000), "count": 1, "category": "rent"},
                    "Insurer": {"amount": Decimal(100), "count": 1, "category": "insurance"},
                    "Store": {"amount": Decimal(500), "count": 1, "category": "groceries"},
                },
            ),
        }
        svc = _make_service(month_data=data, targets=targets)
        result = svc.get_income_statement(2026, _summaries_for(data))
        # Fixed = rent ($1000) + insurance ($100) = $1100
        assert result["committed_floor"] == 1100.0

    def test_category_type_fallback_to_historical(self) -> None:
        """When category not in budget targets, falls back to historical inference."""
        hist_cats = {
            "subscriptions": {"suggested_type": "lumpy", "monthly_avg": 50},
        }
        data = {
            "2026-01": _make_month_summary(
                "2026-01",
                spending=50,
                spending_count=1,
                by_category={"subscriptions": {"amount": Decimal(50), "count": 1}},
                by_company={"Netflix": {"amount": Decimal(50), "count": 1, "category": "subscriptions"}},
            ),
        }
        svc = _make_service(month_data=data, hist_categories=hist_cats)
        result = svc.get_income_statement(2026, _summaries_for(data))

        type_names = [s["type_name"] for s in result["expense_sections"]]
        assert "lumpy" in type_names

    def test_merchant_alias_grouping(self) -> None:
        """Merchant aliases should group different raw names under one canonical name."""
        aliases = {"safeway #1234": "Safeway", "safeway #5678": "Safeway"}
        data = {
            "2026-01": _make_month_summary(
                "2026-01",
                spending=200,
                spending_count=2,
                by_category={"groceries": {"amount": Decimal(200), "count": 2}},
                by_company={
                    "Safeway #1234": {"amount": Decimal(100), "count": 1, "category": "groceries"},
                    "Safeway #5678": {"amount": Decimal(100), "count": 1, "category": "groceries"},
                },
            ),
        }
        svc = _make_service(month_data=data, aliases=aliases)
        result = svc.get_income_statement(2026, _summaries_for(data))

        # Both should be grouped under "Safeway"
        variable_section = next(s for s in result["expense_sections"] if s["type_name"] == "variable")
        groceries = next(c for c in variable_section["categories"] if c["category"] == "groceries")
        assert len(groceries["companies"]) == 1
        assert groceries["companies"][0]["company"] == "Safeway"
        assert groceries["companies"][0]["total"] == 200.0
