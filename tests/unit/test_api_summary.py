"""Tests for summary API endpoints."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from src.finance import demo_clock
from src.finance.upcoming_service import ExpectedCharge, UpcomingResult
from tests.asserts import assert_ok, assert_problem

# The router's ``app_today()`` (src.finance.demo_clock.app_today) reads the app
# timezone in demo_clock's own namespace, so freezing that module pins "today".
# Noon Pacific on 2026-06-15 → local date exactly 2026-06-15.
_PINNED_NOW = datetime(2026, 6, 15, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles"))


def _make_summary(year_month: str = "2026-02", **overrides: Any) -> dict[str, Any]:
    """Build a fake SpendingSummary.get_summary() result."""
    base: dict[str, Any] = {
        "year_month": year_month,
        "total_spending": Decimal("1500.00"),
        "spending_count": 25,
        "deposit_total": Decimal("200.00"),
        "deposit_count": 2,
        "by_category": {
            "groceries": {"amount": Decimal("400.00"), "count": 10},
            "restaurant/dining": {"amount": Decimal("250.00"), "count": 8},
        },
        "by_company": {
            "Safeway": {"amount": Decimal("300.00"), "count": 6, "category": "groceries"},
        },
        "deposits_by_company": {
            "Acme Payroll": {"amount": Decimal("200.00"), "count": 2},
        },
        "top_categories": [
            ("groceries", {"amount": Decimal("400.00"), "count": 10}),
            ("restaurant/dining", {"amount": Decimal("250.00"), "count": 8}),
        ],
    }
    base.update(overrides)
    return base


def _make_comparison(year_month: str = "2026-02") -> dict[str, Any]:
    """Build a fake SpendingSummary.get_summary_with_comparison() result."""
    current = _make_summary(year_month)
    previous = _make_summary(
        "2026-01",
        total_spending=Decimal("1200.00"),
        spending_count=20,
    )
    return {
        "current": current,
        "previous": previous,
        "delta_amount": Decimal("300.00"),
        "delta_percent": 25.0,
    }


# ---------------------------------------------------------------------------
# GET /api/v1/summary
# ---------------------------------------------------------------------------


class TestGetSummary:
    @pytest.mark.parametrize("mock_run_sync", ["summary"], indirect=True)
    def test_returns_correct_shape(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        mock_run_sync.return_value = _make_comparison()

        resp = api_client.get("/api/v1/summary?month=2026-02")
        assert_ok(resp)

        data = resp.json()
        assert "current" in data
        assert "previous" in data
        assert "delta_amount" in data
        assert "delta_percent" in data

    @pytest.mark.parametrize("mock_run_sync", ["summary"], indirect=True)
    def test_decimal_to_float_conversion(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        mock_run_sync.return_value = _make_comparison()

        resp = api_client.get("/api/v1/summary?month=2026-02")
        data = resp.json()

        assert isinstance(data["current"]["total_spending"], float)
        assert data["current"]["total_spending"] == 1500.0
        assert isinstance(data["delta_amount"], float)
        assert data["delta_amount"] == 300.0

    @pytest.mark.parametrize("mock_run_sync", ["summary"], indirect=True)
    def test_top_categories_as_objects(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        mock_run_sync.return_value = _make_comparison()

        resp = api_client.get("/api/v1/summary?month=2026-02")
        top = resp.json()["current"]["top_categories"]

        assert isinstance(top, list)
        assert len(top) == 2
        assert top[0]["name"] == "groceries"
        assert top[0]["amount"] == 400.0
        assert top[0]["count"] == 10

    @pytest.mark.parametrize("mock_run_sync", ["summary"], indirect=True)
    def test_by_category_structure(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        mock_run_sync.return_value = _make_comparison()

        resp = api_client.get("/api/v1/summary?month=2026-02")
        by_cat = resp.json()["current"]["by_category"]

        assert "groceries" in by_cat
        assert by_cat["groceries"]["amount"] == 400.0
        assert by_cat["groceries"]["count"] == 10

    @pytest.mark.parametrize("mock_run_sync", ["summary"], indirect=True)
    def test_by_company_structure(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        mock_run_sync.return_value = _make_comparison()

        resp = api_client.get("/api/v1/summary?month=2026-02")
        by_co = resp.json()["current"]["by_company"]

        assert "Safeway" in by_co
        assert by_co["Safeway"]["category"] == "groceries"

    @pytest.mark.parametrize("mock_run_sync", ["summary"], indirect=True)
    def test_deposits_by_company_structure(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        mock_run_sync.return_value = _make_comparison()

        resp = api_client.get("/api/v1/summary?month=2026-02")
        deposits = resp.json()["current"]["deposits_by_company"]

        assert "Acme Payroll" in deposits
        assert deposits["Acme Payroll"]["amount"] == 200.0
        assert deposits["Acme Payroll"]["count"] == 2
        assert "category" not in deposits["Acme Payroll"]

    def test_missing_month_returns_422(self, api_client: TestClient) -> None:
        resp = api_client.get("/api/v1/summary")
        assert_problem(resp, 422)

    def test_invalid_month_format_returns_422(self, api_client: TestClient) -> None:
        resp = api_client.get("/api/v1/summary?month=Feb-2026")
        assert_problem(resp, 422)


# ---------------------------------------------------------------------------
# GET /api/v1/summary — pace (current-month only)
# ---------------------------------------------------------------------------

_PACE_KEYS = {
    "day_of_month",
    "days_in_month",
    "previous_to_date",
    "typical_to_date",
    "projected_month_total",
    "projected_lower",
    "projected_upper",
    "forecast_quality",
    "breakdown",
}


def _forecast_items(year_month: str) -> list[dict[str, Any]]:
    """Six spending transactions for one forecast-window month (groceries)."""
    prefix = year_month.replace("-", ".")
    return [
        {
            "DateFileName": f"{prefix}.{day:02d}_10.00_test.json",
            "Amount": Decimal(str(amount)),
            "TransactionType": "purchase",
            "Category": "groceries",
            "Company": "SAFEWAY",
        }
        for day, amount in ((5, 300), (15, 400), (25, 300))
    ]


class TestGetSummaryPace:
    @pytest.fixture(autouse=True)
    def _fresh_forecast_cache(self):
        # Reset the ForecastService singleton around each test so a stored
        # window from one test can't mask another's mocked query calls.
        from src.api.dependencies import get_forecast_service

        get_forecast_service().invalidate_cache()
        yield
        get_forecast_service().invalidate_cache()

    @pytest.mark.parametrize("mock_run_sync", ["summary"], indirect=True)
    def test_summary_pace_null_for_past_month(
        self, mock_run_sync: AsyncMock, api_client: TestClient, freeze_clock
    ) -> None:
        freeze_clock(demo_clock, at=_PINNED_NOW)  # router's app_today() → 2026-06-15
        # Requested month != current month → no forecast, no extra queries.
        mock_run_sync.return_value = _make_comparison("2026-01")

        resp = api_client.get("/api/v1/summary?month=2026-01")
        assert_ok(resp)
        assert resp.json()["pace"] is None
        # Only the comparison call — no forecast query_month calls issued.
        assert mock_run_sync.call_count == 1

    @pytest.mark.parametrize("mock_run_sync", ["summary"], indirect=True)
    def test_summary_pace_present_for_current_month(
        self, mock_run_sync: AsyncMock, api_client: TestClient, freeze_clock
    ) -> None:
        freeze_clock(demo_clock, at=_PINNED_NOW)  # router's app_today() → 2026-06-15
        from src.finance.forecast_service import build_tables, month_keys

        keys = month_keys(date(2026, 6, 15))
        # The router single-flights the whole build in one run_sync call
        # (get_or_build), so the mock returns pre-built tables, not per-month
        # query results. No penciled charges → curve-only pace, breakdown null:
        # the commitment path short-circuits on the empty result (run_sync'd)
        # before any discretionary/current-month query.
        tables = build_tables({ym: _forecast_items(ym) for ym in keys})
        mock_run_sync.side_effect = [
            _make_comparison("2026-06"),
            tables,
            UpcomingResult(charges=[], recurring_merchants=set()),
        ]

        resp = api_client.get("/api/v1/summary?month=2026-06")
        assert_ok(resp)
        pace = resp.json()["pace"]
        assert pace is not None
        assert set(pace.keys()) == _PACE_KEYS
        assert pace["day_of_month"] == 15
        assert pace["days_in_month"] == 30
        assert pace["breakdown"] is None
        assert isinstance(pace["previous_to_date"], float)
        # comparison + one single-flight get_or_build + the (empty) upcoming derivation.
        assert mock_run_sync.call_count == 3

    @pytest.mark.parametrize("mock_run_sync", ["summary"], indirect=True)
    def test_summary_pace_breakdown_terms_sum_to_projection(
        self, mock_run_sync: AsyncMock, api_client: TestClient, freeze_clock
    ) -> None:
        freeze_clock(demo_clock, at=_PINNED_NOW)  # 2026-06-15
        from src.finance.forecast_service import build_tables, month_keys

        keys = month_keys(date(2026, 6, 15))
        upcoming = UpcomingResult(
            charges=[
                ExpectedCharge(
                    merchant="rent",
                    display_name="Rent",
                    amount_estimate=2000.0,
                    expected_day=25,
                    status="upcoming",
                    channel="statement",
                    cadence="monthly",
                    category="rent",
                )
            ],
            recurring_merchants={"rent"},
        )
        # run_sync call order: comparison, single-flight get_or_build (returns
        # pre-built tables, so window_results stays None), upcoming derivation,
        # 6 forecast-window re-queries (discretionary build), aliases map,
        # current-month query.
        tables = build_tables({ym: _forecast_items(ym) for ym in keys})
        mock_run_sync.side_effect = [
            _make_comparison("2026-06"),
            tables,
            upcoming,
            *[_forecast_items(ym) for ym in keys],
            {},  # aliases map
            [],  # current_items — no _stmt_ rows to subtract
        ]

        resp = api_client.get("/api/v1/summary?month=2026-06")
        assert_ok(resp)
        pace = resp.json()["pace"]
        assert pace is not None
        b = pace["breakdown"]
        assert b is not None
        assert b["observed_mtd"] == 1500.0  # comparison current total
        assert b["upcoming_committed"] == 2000.0
        assert b["assumed_committed"] == 0.0
        assert len(b["charges"]) == 1
        assert b["charges"][0]["merchant"] == "rent"
        # The four breakdown terms reconstruct the projected total (L5).
        terms = b["observed_mtd"] + b["assumed_committed"] + b["upcoming_committed"] + b["everyday_remainder"]
        assert abs(terms - pace["projected_month_total"]) < 0.02
        # comparison + get_or_build + upcoming + 6 windows + aliases + current-month.
        assert mock_run_sync.call_count == 3 + len(keys) + 2

    @pytest.mark.parametrize("mock_run_sync", ["summary"], indirect=True)
    def test_summary_pace_breakdown_null_when_upcoming_raises(
        self, mock_run_sync: AsyncMock, api_client: TestClient, freeze_clock
    ) -> None:
        freeze_clock(demo_clock, at=_PINNED_NOW)  # 2026-06-15
        from src.finance.forecast_service import build_tables, month_keys

        keys = month_keys(date(2026, 6, 15))
        # The upcoming derivation (run_sync'd, right after the single-flight
        # build) raises → inner fail-open → curve-only pace, breakdown null.
        tables = build_tables({ym: _forecast_items(ym) for ym in keys})
        mock_run_sync.side_effect = [
            _make_comparison("2026-06"),
            tables,
            RuntimeError("upcoming boom"),
        ]

        resp = api_client.get("/api/v1/summary?month=2026-06")
        assert_ok(resp)
        pace = resp.json()["pace"]
        assert pace is not None
        assert pace["breakdown"] is None
        assert pace["projected_month_total"] is not None

    @pytest.mark.parametrize("mock_run_sync", ["summary"], indirect=True)
    def test_summary_pace_fail_open(self, mock_run_sync: AsyncMock, api_client: TestClient, freeze_clock) -> None:
        freeze_clock(demo_clock, at=_PINNED_NOW)  # router's app_today() → 2026-06-15
        # Forecast query blows up → 200, pace None, everything else intact.
        mock_run_sync.side_effect = [_make_comparison("2026-06"), RuntimeError("dynamo down")]

        resp = api_client.get("/api/v1/summary?month=2026-06")
        assert_ok(resp)
        data = resp.json()
        assert data["pace"] is None
        assert data["current"]["total_spending"] == 1500.0
        assert data["delta_amount"] == 300.0
        assert data["delta_percent"] == 25.0


# ---------------------------------------------------------------------------
# GET /api/v1/summary/trend
# ---------------------------------------------------------------------------


class TestGetTrend:
    @pytest.mark.parametrize("mock_run_sync", ["summary"], indirect=True)
    def test_returns_n_months_oldest_first(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        # run_sync is called N times via asyncio.gather
        mock_run_sync.side_effect = [_make_summary(f"2025-{str(i).zfill(2)}") for i in range(9, 15)]

        resp = api_client.get("/api/v1/summary/trend?months=6")
        assert_ok(resp)

        data = resp.json()
        assert len(data["months"]) == 6
        # Verify oldest-first ordering
        months = [m["year_month"] for m in data["months"]]
        assert months == sorted(months)

    @pytest.mark.parametrize("mock_run_sync", ["summary"], indirect=True)
    def test_trend_includes_by_category(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        mock_run_sync.side_effect = [_make_summary(f"2026-0{i}") for i in range(1, 3)]

        resp = api_client.get("/api/v1/summary/trend?months=2")
        entry = resp.json()["months"][0]

        assert "by_category" in entry
        assert "groceries" in entry["by_category"]

    def test_months_below_minimum_returns_422(self, api_client: TestClient) -> None:
        resp = api_client.get("/api/v1/summary/trend?months=1")
        assert_problem(resp, 422)

    def test_months_above_maximum_returns_422(self, api_client: TestClient) -> None:
        resp = api_client.get("/api/v1/summary/trend?months=13")
        assert_problem(resp, 422)

    @pytest.mark.parametrize("mock_run_sync", ["summary"], indirect=True)
    def test_end_month_returns_months_ending_at_specified(
        self, mock_run_sync: AsyncMock, api_client: TestClient
    ) -> None:
        # end_month=2025-06 with months=6 should return Jan-Jun 2025
        mock_run_sync.side_effect = [_make_summary(f"2025-{str(i).zfill(2)}") for i in range(1, 7)]

        resp = api_client.get("/api/v1/summary/trend?months=6&end_month=2025-06")
        assert_ok(resp)

        data = resp.json()
        months = [m["year_month"] for m in data["months"]]
        assert months == ["2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06"]

    @pytest.mark.parametrize("mock_run_sync", ["summary"], indirect=True)
    def test_end_month_omitted_uses_current_month(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        mock_run_sync.side_effect = [_make_summary(f"2026-0{i}") for i in range(1, 3)]

        resp = api_client.get("/api/v1/summary/trend?months=2")
        assert_ok(resp)
        assert len(resp.json()["months"]) == 2

    def test_invalid_end_month_format_returns_422(self, api_client: TestClient) -> None:
        resp = api_client.get("/api/v1/summary/trend?end_month=Jun-2025")
        assert_problem(resp, 422)
