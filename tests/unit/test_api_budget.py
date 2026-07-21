"""Tests for budget API endpoints."""

from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.finance import demo_clock
from src.finance.exceptions import VersionConflictError
from src.finance.upcoming_service import ExpectedCharge, UpcomingResult
from tests.asserts import assert_ok, assert_problem
from tests.factories import make_budget_targets_item, make_groups_item

# The instant conftest's ``freeze_clock`` default pins to (2026-05-07). Freezing
# ``demo_clock`` makes the budget router's ``app_today()`` return this date, so
# "current month" is deterministically May and these tests can drop the old
# ``date.today().month if date.today().year == 2026 else 12`` wall-clock guard —
# a year-dependent hack that would silently change the summary count after 2026.
_FROZEN_TODAY = date(2026, 5, 7)
_CURRENT_MONTH_NUM = _FROZEN_TODAY.month  # 5 — number of YTD month summaries the router reads

# Tests in this file assert on a large-budget shape ($96K ceiling, groceries
# target $18K, rent target $35.4K) and must override the factory defaults.
_ANNUAL_CEILING = 96000
_BIG_CATEGORIES = {
    "groceries": {
        "target": Decimal(18000),
        "input_mode": "monthly",
        "monthly_amount": Decimal(1500),
        "category_type": "variable",
    },
    "rent": {
        "target": Decimal(35400),
        "input_mode": "monthly",
        "monthly_amount": Decimal(2950),
        "category_type": "fixed",
    },
}


def _make_targets_item(
    year: int = 2026,
    ceiling: float | int = _ANNUAL_CEILING,
    categories: dict[str, Any] | None = None,
    version: int = 1,
) -> dict[str, Any]:
    return make_budget_targets_item(
        year=year,
        version=version,
        ceiling=ceiling,
        categories=categories or _BIG_CATEGORIES,
    )


def _make_groups_item(year: int = 2026, version: int = 1) -> dict[str, Any]:
    return make_groups_item(year=year, version=version)


def _make_month_summary(year_month: str = "2026-01") -> dict[str, Any]:
    return {
        "year_month": year_month,
        "total_spending": Decimal(2000),
        "spending_count": 20,
        "deposit_total": Decimal(0),
        "deposit_count": 0,
        "by_category": {
            "groceries": {"amount": Decimal(1000), "count": 10},
            "rent": {"amount": Decimal(800), "count": 1},
            "office": {"amount": Decimal(200), "count": 3},
        },
        "by_company": {},
        "top_categories": [],
    }


# ---------------------------------------------------------------------------
# GET /api/v1/budget/config
# ---------------------------------------------------------------------------


class TestGetConfig:
    @pytest.mark.parametrize("mock_run_sync", ["budget"], indirect=True)
    def test_returns_404_when_not_configured(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = None
        resp = api_client.get("/api/v1/budget/config?year=2026")
        assert_problem(resp, 404)

    @pytest.mark.parametrize("mock_run_sync", ["budget"], indirect=True)
    def test_returns_full_shape(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.side_effect = [_make_targets_item(), _make_groups_item()]
        resp = api_client.get("/api/v1/budget/config?year=2026")
        assert_ok(resp)
        data = resp.json()
        assert data["year"] == 2026
        assert "spending_ceiling" in data
        assert "categories" in data
        assert "groups" in data
        assert "targets_version" in data
        assert "allocated_total" in data
        assert "unallocated" in data

    @pytest.mark.parametrize("mock_run_sync", ["budget"], indirect=True)
    def test_computes_allocated_total(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.side_effect = [_make_targets_item(), _make_groups_item()]
        resp = api_client.get("/api/v1/budget/config?year=2026")
        data = resp.json()
        # groceries 18000 + rent 35400 = 53400
        assert data["allocated_total"] == 53400.0
        assert data["unallocated"] == 96000.0 - 53400.0


# ---------------------------------------------------------------------------
# PUT /api/v1/budget/config
# ---------------------------------------------------------------------------


class TestPutConfig:
    @pytest.mark.parametrize("mock_run_sync", ["budget"], indirect=True)
    def test_creates_new_budget(self, mock_run_sync: AsyncMock, api_client) -> None:
        # get_targets + get_groups (ledger before-images), put_targets, put_groups,
        # then get_targets + get_groups for the re-read.
        mock_run_sync.side_effect = [
            None,
            None,
            1,
            1,
            _make_targets_item(version=1),
            _make_groups_item(version=1),
        ]

        body = {
            "spending_ceiling": 96000,
            "categories": {
                "groceries": {"target": 18000, "input_mode": "monthly", "category_type": "variable"},
            },
            "groups": [{"name": "Food & Dining", "categories": ["groceries"]}],
            "targets_version": None,
            "groups_version": None,
        }
        resp = api_client.put("/api/v1/budget/config?year=2026", json=body)
        assert_ok(resp)
        data = resp.json()
        assert "year" in data
        assert data["targets_version"] >= 1

    @pytest.mark.parametrize("mock_run_sync", ["budget"], indirect=True)
    def test_returns_409_on_conflict(self, mock_run_sync: AsyncMock, api_client) -> None:
        # get_targets + get_groups before-images succeed; put_targets raises the conflict.
        mock_run_sync.side_effect = [None, None, VersionConflictError("conflict")]

        body = {
            "spending_ceiling": 96000,
            "categories": {},
            "groups": [],
            "targets_version": 1,
            "groups_version": 1,
        }
        resp = api_client.put("/api/v1/budget/config?year=2026", json=body)
        assert_problem(resp, 409)


# ---------------------------------------------------------------------------
# GET /api/v1/budget/status
# ---------------------------------------------------------------------------


class TestGetStatus:
    @pytest.mark.parametrize("mock_run_sync", ["budget"], indirect=True)
    def test_returns_pace_data(self, mock_run_sync: AsyncMock, api_client, freeze_clock) -> None:
        freeze_clock(demo_clock)  # router's app_today() → May 2026
        targets = _make_targets_item()
        groups = _make_groups_item()
        # Need month summaries for each month up to current month (May)
        month_summaries = [_make_month_summary(f"2026-{str(m).zfill(2)}") for m in range(1, _CURRENT_MONTH_NUM + 1)]
        historical = {
            "months_analyzed": 6,
            "period": {"from": "2025-09", "to": "2026-02"},
            "categories": {"office": {"monthly_avg": 50.0}},
        }
        mock_run_sync.side_effect = [targets, groups, *month_summaries, historical]

        resp = api_client.get("/api/v1/budget/status?year=2026")
        assert_ok(resp)
        data = resp.json()
        assert "overall" in data
        assert "groups" in data
        assert "unbudgeted" in data
        assert data["overall"]["spending_ceiling"] == 96000.0
        assert data["elapsed_year_fraction"] > 0

    @pytest.mark.parametrize("mock_run_sync", ["budget"], indirect=True)
    def test_returns_prior_year_totals_when_compare_year_provided(
        self, mock_run_sync: AsyncMock, api_client, freeze_clock
    ) -> None:
        freeze_clock(demo_clock)  # router's app_today() → May 2026
        targets = _make_targets_item()
        groups = _make_groups_item()
        month_summaries = [_make_month_summary(f"2026-{str(m).zfill(2)}") for m in range(1, _CURRENT_MONTH_NUM + 1)]

        # 12 compare year months with different amounts
        compare_summaries = [
            {
                "year_month": f"2025-{str(m).zfill(2)}",
                "total_spending": Decimal(1500),
                "spending_count": 15,
                "deposit_total": Decimal(0),
                "deposit_count": 0,
                "by_category": {
                    "groceries": {"amount": Decimal(900), "count": 8},
                    "rent": {"amount": Decimal(600), "count": 1},
                },
                "by_company": {},
                "top_categories": [],
            }
            for m in range(1, 13)
        ]

        historical = {
            "months_analyzed": 6,
            "period": {"from": "2025-09", "to": "2026-02"},
            "categories": {"office": {"monthly_avg": 50.0}},
        }
        mock_run_sync.side_effect = [targets, groups, *month_summaries, *compare_summaries, historical]

        resp = api_client.get("/api/v1/budget/status?year=2026&compare_year=2025")
        assert_ok(resp)
        data = resp.json()

        assert data["compare_year"] == 2025
        # 12 months x $900 = $10,800 groceries; 12 x $600 = $7,200 rent
        assert data["prior_year_total"] == 10800.0 + 7200.0

        # Check categories have prior_year_total
        for group in data["groups"]:
            assert group["prior_year_total"] is not None
            for cat in group["categories"]:
                assert cat["prior_year_total"] is not None

        # Find groceries category
        groceries_cat = None
        for group in data["groups"]:
            for cat in group["categories"]:
                if cat["category"] == "groceries":
                    groceries_cat = cat
        assert groceries_cat is not None
        assert groceries_cat["prior_year_total"] == 10800.0

    @pytest.mark.parametrize("mock_run_sync", ["budget"], indirect=True)
    def test_prior_year_fields_null_without_compare_year(
        self, mock_run_sync: AsyncMock, api_client, freeze_clock
    ) -> None:
        freeze_clock(demo_clock)  # router's app_today() → May 2026
        targets = _make_targets_item()
        groups = _make_groups_item()
        month_summaries = [_make_month_summary(f"2026-{str(m).zfill(2)}") for m in range(1, _CURRENT_MONTH_NUM + 1)]
        historical = {
            "months_analyzed": 6,
            "period": {"from": "2025-09", "to": "2026-02"},
            "categories": {"office": {"monthly_avg": 50.0}},
        }
        mock_run_sync.side_effect = [targets, groups, *month_summaries, historical]

        resp = api_client.get("/api/v1/budget/status?year=2026")
        assert_ok(resp)
        data = resp.json()

        assert data["compare_year"] is None
        assert data["prior_year_total"] is None
        for group in data["groups"]:
            assert group["prior_year_total"] is None
            for cat in group["categories"]:
                assert cat["prior_year_total"] is None

    @pytest.mark.parametrize("mock_run_sync", ["budget"], indirect=True)
    def test_returns_monthly_breakdowns(self, mock_run_sync: AsyncMock, api_client, freeze_clock) -> None:
        freeze_clock(demo_clock)  # router's app_today() → May 2026
        targets = _make_targets_item()
        groups = _make_groups_item()
        month_summaries = [_make_month_summary(f"2026-{str(m).zfill(2)}") for m in range(1, _CURRENT_MONTH_NUM + 1)]
        historical = {
            "months_analyzed": 6,
            "period": {"from": "2025-09", "to": "2026-02"},
            "categories": {"office": {"monthly_avg": 50.0}},
        }
        mock_run_sync.side_effect = [targets, groups, *month_summaries, historical]

        resp = api_client.get("/api/v1/budget/status?year=2026")
        assert_ok(resp)
        data = resp.json()

        # Top-level monthly_totals is a 12-element array
        assert "monthly_totals" in data
        assert len(data["monthly_totals"]) == 12
        # Jan has spending (1000 groceries + 800 rent from budgeted)
        assert data["monthly_totals"][0] > 0

        # Each group has monthly_totals
        for group in data["groups"]:
            assert "monthly_totals" in group
            assert len(group["monthly_totals"]) == 12

        # Each category has monthly_spent
        for group in data["groups"]:
            for cat in group["categories"]:
                assert "monthly_spent" in cat
                assert len(cat["monthly_spent"]) == 12


# ---------------------------------------------------------------------------
# GET /api/v1/budget/status — forecast fields
# ---------------------------------------------------------------------------


def _make_forecast_items(year_month: str) -> list[dict[str, Any]]:
    """Raw transactions for one historical month: groceries on three days."""
    prefix = year_month.replace("-", ".")
    return [
        {
            "DateFileName": f"{prefix}.{day:02d}_10.00_test.json",
            "Amount": Decimal(str(amount)),
            "TransactionType": "purchase",
            "Category": "groceries",
        }
        for day, amount in ((5, 300), (15, 400), (25, 300))
    ]


def _find_category(data: dict[str, Any], name: str) -> dict[str, Any]:
    for group in data["groups"]:
        for cat in group["categories"]:
            if cat["category"] == name:
                return cat
    raise AssertionError(f"category {name!r} not in response groups")


class TestGetStatusForecast:
    @pytest.fixture(autouse=True)
    def _fresh_forecast_cache(self):
        # The ForecastService singleton caches fraction tables for an hour —
        # reset around each test so cache hits can't mask the mocked calls.
        from src.api.dependencies import get_forecast_service

        get_forecast_service().invalidate_cache()
        yield
        get_forecast_service().invalidate_cache()

    def _status_side_effect(self) -> list[Any]:
        """run_sync results for the current year, in call order:
        targets, groups, YTD month summaries, historical averages.

        Assumes the caller froze the router clock to ``_FROZEN_TODAY`` (May
        2026), so exactly ``_CURRENT_MONTH_NUM`` YTD summaries are supplied.
        """
        month_summaries = [_make_month_summary(f"2026-{str(m).zfill(2)}") for m in range(1, _CURRENT_MONTH_NUM + 1)]
        historical = {"months_analyzed": 6, "period": {}, "categories": {}}
        return [_make_targets_item(), _make_groups_item(), *month_summaries, historical]

    def _forecast_query_results(self) -> list[list[dict[str, Any]]]:
        """Six query_month item lists for the 6-month forecast window."""
        from src.finance.forecast_service import month_keys

        return [_make_forecast_items(ym) for ym in month_keys(_FROZEN_TODAY)]

    @pytest.mark.parametrize("mock_run_sync", ["budget"], indirect=True)
    def test_variable_category_gets_forecast_fields(self, mock_run_sync: AsyncMock, api_client, freeze_clock) -> None:
        freeze_clock(demo_clock)  # router's app_today() → May 2026
        # The router now single-flights the forecast build in one run_sync call
        # (get_or_build), so the mock returns pre-built tables rather than six
        # per-month query results — built from the same _make_forecast_items data.
        from src.finance.forecast_service import build_tables, month_keys

        tables = build_tables({ym: _make_forecast_items(ym) for ym in month_keys(_FROZEN_TODAY)})
        mock_run_sync.side_effect = [*self._status_side_effect(), tables]

        resp = api_client.get("/api/v1/budget/status?year=2026")
        assert_ok(resp)
        data = resp.json()

        groceries = _find_category(data, "groceries")
        assert groceries["forecast_month_total"] is not None
        # Quality depends on today's day-of-month (historical before day 5).
        assert groceries["forecast_quality"] in ("forecast", "historical")
        # monthly_amount is 1500 → pct is set
        assert groceries["forecast_pct"] is not None
        if groceries["forecast_lower"] is not None:
            assert groceries["forecast_lower"] <= groceries["forecast_month_total"] <= groceries["forecast_upper"]

        # Fixed category: posted this month ($800) → projection is the actual.
        rent = _find_category(data, "rent")
        assert rent["forecast_month_total"] == 800.0
        assert rent["forecast_quality"] is None

        assert data["overall"]["projected_month_total"] is not None
        assert data["overall"]["projected_month_status"] in ("under", "on_track", "over")

    @pytest.mark.parametrize("mock_run_sync", ["budget"], indirect=True)
    def test_lumpy_category_untouched(self, mock_run_sync: AsyncMock, api_client, freeze_clock) -> None:
        freeze_clock(demo_clock)  # router's app_today() → May 2026
        categories = {
            **_BIG_CATEGORIES,
            "travel": {
                "target": Decimal(6000),
                "input_mode": "yearly",
                "monthly_amount": Decimal(500),
                "category_type": "lumpy",
            },
        }
        targets = _make_targets_item(categories=categories)
        groups = _make_groups_item()
        groups["Data"]["groups"] = [{"name": "Everything", "categories": ["groceries", "rent", "travel"]}]
        side_effect = self._status_side_effect()
        side_effect[0] = targets
        side_effect[1] = groups
        mock_run_sync.side_effect = [*side_effect, *self._forecast_query_results()]

        resp = api_client.get("/api/v1/budget/status?year=2026")
        assert_ok(resp)
        travel = _find_category(resp.json(), "travel")
        assert travel["forecast_month_total"] is None
        assert travel["forecast_quality"] is None
        assert travel["forecast_pct"] is None

    @pytest.mark.parametrize("mock_run_sync", ["budget"], indirect=True)
    def test_forecast_fails_open(self, mock_run_sync: AsyncMock, api_client, freeze_clock) -> None:
        freeze_clock(demo_clock)  # router's app_today() → May 2026
        # The six forecast query_month calls blow up — response must still be
        # 200 with every forecast field None.
        mock_run_sync.side_effect = [*self._status_side_effect(), RuntimeError("dynamo down")]

        resp = api_client.get("/api/v1/budget/status?year=2026")
        assert_ok(resp)
        data = resp.json()
        assert data["overall"]["projected_month_total"] is None
        assert data["overall"]["projected_month_status"] is None
        for group in data["groups"]:
            for cat in group["categories"]:
                assert cat["forecast_month_total"] is None

    @staticmethod
    def _forecast_with_rent() -> list[list[dict[str, Any]]]:
        """Six forecast-window months, each with a steady $2,150 rent charge
        plus some groceries — so ``tables.categories['rent']`` has a real mean."""
        from src.finance.forecast_service import month_keys

        results = []
        for ym in month_keys(_FROZEN_TODAY):
            prefix = ym.replace("-", ".")
            results.append(
                [
                    {
                        "DateFileName": f"{prefix}.01_10.00_rent.json",
                        "Amount": Decimal(2150),
                        "TransactionType": "purchase",
                        "Category": "rent",
                        "Company": "RENT PAD",
                    },
                    {
                        "DateFileName": f"{prefix}.15_10.00_groc.json",
                        "Amount": Decimal(500),
                        "TransactionType": "purchase",
                        "Category": "groceries",
                        "Company": "SAFEWAY",
                    },
                ]
            )
        return results

    @classmethod
    def _rent_tables(cls):
        """Pre-built forecast tables over :meth:`_forecast_with_rent` — what the
        mocked single-flight ``get_or_build`` run_sync call returns."""
        from src.finance.forecast_service import build_tables, month_keys

        return build_tables(dict(zip(month_keys(_FROZEN_TODAY), cls._forecast_with_rent(), strict=True)))

    @staticmethod
    def _rent_upcoming(estimate: float) -> UpcomingResult:
        return UpcomingResult(
            charges=[
                ExpectedCharge(
                    merchant="rent pad",
                    display_name="Rent Pad",
                    amount_estimate=estimate,
                    expected_day=1,
                    status="upcoming",
                    channel="statement",
                    cadence="monthly",
                    category="rent",
                )
            ],
            recurring_merchants={"rent pad"},
        )

    @pytest.mark.parametrize("mock_run_sync", ["budget"], indirect=True)
    def test_committed_forecast_for_recurring_dominated_category(
        self, mock_run_sync: AsyncMock, api_client, freeze_clock
    ) -> None:
        freeze_clock(demo_clock)  # May 2026
        # rent history mean is $2,150; an expected $2,150 charge is ≥70% of it →
        # the category flips to the committed forecast. The upcoming result is
        # the LAST run_sync call apply_forecast makes (after the single-flight
        # get_or_build, which the mock answers with pre-built tables).
        mock_run_sync.side_effect = [
            *self._status_side_effect(),
            self._rent_tables(),
            self._rent_upcoming(2150.0),
        ]

        resp = api_client.get("/api/v1/budget/status?year=2026")
        assert_ok(resp)
        rent = _find_category(resp.json(), "rent")
        assert rent["forecast_quality"] == "committed"
        # spent (800, from month summaries) + still-coming committed (2150).
        assert rent["forecast_month_total"] == 2950.0
        # Committed terms are point estimates — no variance band.
        assert rent["forecast_lower"] is None
        assert rent["forecast_upper"] is None

    @pytest.mark.parametrize("mock_run_sync", ["budget"], indirect=True)
    def test_below_threshold_keeps_curve_forecast(self, mock_run_sync: AsyncMock, api_client, freeze_clock) -> None:
        freeze_clock(demo_clock)  # May 2026
        # A tiny $100 expected charge is far under 70% of the $2,150 mean →
        # rent keeps its ordinary fixed forecast (posted actual, quality None).
        mock_run_sync.side_effect = [
            *self._status_side_effect(),
            self._rent_tables(),
            self._rent_upcoming(100.0),
        ]

        resp = api_client.get("/api/v1/budget/status?year=2026")
        assert_ok(resp)
        rent = _find_category(resp.json(), "rent")
        assert rent["forecast_quality"] is None
        assert rent["forecast_month_total"] == 800.0  # posted actual, unchanged

    @pytest.mark.parametrize("mock_run_sync", ["budget"], indirect=True)
    def test_no_forecast_for_non_current_year(self, mock_run_sync: AsyncMock, api_client, freeze_clock) -> None:
        freeze_clock(demo_clock)  # app_today() → 2026, so year=2025 is a non-current year
        targets = _make_targets_item(year=2025)
        groups = _make_groups_item(year=2025)
        month_summaries = [_make_month_summary(f"2025-{str(m).zfill(2)}") for m in range(1, 13)]
        historical = {"months_analyzed": 6, "period": {}, "categories": {}}
        mock_run_sync.side_effect = [targets, groups, *month_summaries, historical]

        resp = api_client.get("/api/v1/budget/status?year=2025")
        assert_ok(resp)
        data = resp.json()
        assert data["overall"]["projected_month_total"] is None
        for group in data["groups"]:
            for cat in group["categories"]:
                assert cat["forecast_month_total"] is None

    @pytest.mark.parametrize("mock_run_sync", ["budget"], indirect=True)
    def test_zero_monthly_budget_leaves_pct_none(self, mock_run_sync: AsyncMock, api_client, freeze_clock) -> None:
        freeze_clock(demo_clock)  # router's app_today() → May 2026
        categories = {
            **_BIG_CATEGORIES,
            "hobbies": {
                "target": Decimal(0),
                "input_mode": "monthly",
                "monthly_amount": Decimal(0),
                "category_type": "variable",
            },
        }
        targets = _make_targets_item(categories=categories)
        groups = _make_groups_item()
        groups["Data"]["groups"] = [{"name": "Everything", "categories": ["groceries", "rent", "hobbies"]}]
        side_effect = self._status_side_effect()
        side_effect[0] = targets
        side_effect[1] = groups

        # Give hobbies history so a projection exists but pct cannot be computed.
        query_results = self._forecast_query_results()
        for items in query_results:
            hobby_item = dict(items[0])
            hobby_item["Category"] = "hobbies"
            items.append(hobby_item)
        mock_run_sync.side_effect = [*side_effect, *query_results]

        resp = api_client.get("/api/v1/budget/status?year=2026")
        assert_ok(resp)
        hobbies = _find_category(resp.json(), "hobbies")
        assert hobbies["forecast_pct"] is None


# ---------------------------------------------------------------------------
# GET /api/v1/budget/historical-averages
# ---------------------------------------------------------------------------


class TestGetHistorical:
    @pytest.mark.parametrize("mock_run_sync", ["budget"], indirect=True)
    def test_returns_categories(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = {
            "months_analyzed": 6,
            "period": {"from": "2025-09", "to": "2026-02"},
            "categories": {
                "groceries": {
                    "monthly_avg": 1200.0,
                    "total": 7200.0,
                    "months_active": 6,
                    "suggested_type": "variable",
                    "suggested_monthly": 1200,
                    "suggested_annual": 14400,
                },
            },
        }

        resp = api_client.get("/api/v1/budget/historical-averages?months=6")
        assert_ok(resp)
        data = resp.json()
        assert data["months_analyzed"] == 6
        assert "groceries" in data["categories"]
        cat = data["categories"]["groceries"]
        assert cat["suggested_type"] == "variable"
