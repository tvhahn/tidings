"""Tests for income statement API endpoint."""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from tests.asserts import assert_ok, assert_problem


def _mock_income_statement_result() -> dict[str, Any]:
    return {
        "year": 2026,
        "months": [f"2026-{m:02d}" for m in range(1, 13)],
        "income": {
            "companies": [
                {"company": "Employer", "months": [3000] + [0] * 11, "total": 3000},
            ],
            "monthly_totals": [3000] + [0] * 11,
            "annual_total": 3000,
        },
        "expense_sections": [
            {
                "type_name": "variable",
                "display_name": "Variable expenses",
                "categories": [
                    {
                        "category": "groceries",
                        "months": [500] + [0] * 11,
                        "total": 500,
                        "companies": [{"company": "Safeway", "months": [500] + [0] * 11, "total": 500}],
                    }
                ],
                "monthly_totals": [500] + [0] * 11,
                "annual_total": 500,
            }
        ],
        "total_expenses_monthly": [500] + [0] * 11,
        "total_expenses_annual": 500,
        "net_monthly": [2500] + [0] * 11,
        "net_annual": 2500,
        "savings_rate_monthly": [83.3] + [None] * 11,
        "savings_rate_annual": 83.3,
        "projection": {
            "annualized_income": 36000,
            "annualized_expenses": 6000,
            "annualized_net": 30000,
            "months_elapsed": 1,
        },
        "committed_floor": 0,
    }


@pytest.mark.parametrize("mock_run_sync", ["income_statement"], indirect=True)
def test_get_income_statement_success(mock_run_sync: AsyncMock, api_client: TestClient) -> None:
    """Endpoint returns 200 with properly structured data."""
    mock_run_sync.side_effect = [
        {},  # alias_svc.get_aliases_map
        *([{}] * 12),  # summary.get_summary for each of the 12 months (gathered)
        _mock_income_statement_result(),  # svc.get_income_statement
    ]

    resp = api_client.get("/api/v1/income-statement?year=2026")
    assert_ok(resp)

    data = resp.json()
    assert data["year"] == 2026
    assert len(data["months"]) == 12
    assert data["income"]["annual_total"] == 3000
    assert len(data["expense_sections"]) == 1
    assert data["net_annual"] == 2500
    assert data["projection"]["months_elapsed"] == 1


@pytest.mark.parametrize("mock_run_sync", ["income_statement"], indirect=True)
def test_get_income_statement_year_validation(mock_run_sync: AsyncMock, api_client: TestClient) -> None:
    """Year must be between 2020 and 2099."""
    resp = api_client.get("/api/v1/income-statement?year=1999")
    assert_problem(resp, 422)

    resp = api_client.get("/api/v1/income-statement?year=2100")
    assert_problem(resp, 422)


def test_get_income_statement_missing_year(api_client: TestClient) -> None:
    """Year parameter is required."""
    resp = api_client.get("/api/v1/income-statement")
    assert_problem(resp, 422)
