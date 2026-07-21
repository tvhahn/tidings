"""Tests for the spending forecast engine (fraction tables + projection math)."""

import threading
import time
from datetime import date
from typing import Any

import pytest

from src.finance.forecast_service import (
    CategoryHistory,
    ForecastService,
    ForecastTables,
    _fraction_at,
    build_tables,
    compute_commitment_pace,
    compute_month_pace,
    month_keys,
    project_category,
    window_key,
)
from src.finance.upcoming_service import ExpectedCharge, UpcomingResult


def _item(
    ym: str,
    day: int,
    amount: float,
    category: str = "groceries",
    txn_type: str = "purchase",
    **overrides: Any,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "DateFileName": f"{ym[:4]}.{ym[5:7]}.{day:02d}_10.00_test.json",
        "Amount": amount,
        "TransactionType": txn_type,
        "Category": category,
    }
    base.update(overrides)
    return base


def _uniform_history(months: int = 4, total: float = 900.0) -> CategoryHistory:
    """History with thirds spent at positions 1/3, 2/3, 1.0 — fraction at 2/3 is exactly 2/3."""
    curve = [(1 / 3, 1 / 3), (2 / 3, 2 / 3), (1.0, 1.0)]
    return CategoryHistory(curves=[list(curve) for _ in range(months)], monthly_totals=[total] * months)


# ---------------------------------------------------------------------------
# month_keys / window_key
# ---------------------------------------------------------------------------


class TestMonthKeys:
    def test_six_complete_months_oldest_first_across_year_boundary(self) -> None:
        keys = month_keys(date(2026, 6, 10))
        assert keys == ["2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05"]

    def test_window_key(self) -> None:
        assert window_key(["2025-12", "2026-05"]) == "2025-12..2026-05"


# ---------------------------------------------------------------------------
# build_tables
# ---------------------------------------------------------------------------


class TestBuildTables:
    def test_cumulative_curve_and_total(self) -> None:
        # April 2026 has 30 days: $100 on day 10, $300 on day 20.
        tables = build_tables({"2026-04": [_item("2026-04", 10, 100.0), _item("2026-04", 20, 300.0)]})
        history = tables.categories["groceries"]
        assert history.monthly_totals == [400.0]
        assert history.curves == [[(10 / 30, 0.25), (20 / 30, 1.0)]]

    def test_month_length_normalization(self) -> None:
        # Feb 2026 (28 days) day 14 and Mar 2026 (31 days) day 15 are both mid-month.
        tables = build_tables(
            {
                "2026-02": [_item("2026-02", 14, 50.0), _item("2026-02", 28, 50.0)],
                "2026-03": [_item("2026-03", 15, 50.0), _item("2026-03", 31, 50.0)],
            }
        )
        history = tables.categories["groceries"]
        first_positions = [curve[0][0] for curve in history.curves]
        assert first_positions[0] == pytest.approx(14 / 28)
        assert first_positions[1] == pytest.approx(15 / 31)

    def test_excludes_deleted_ignored_and_deposits(self) -> None:
        # L2: statement-sourced rows now COUNT — only deleted/ignored/non-spending/
        # amount-less rows are excluded. Day 7 (StatementSource) and day 11 count.
        items = [
            _item("2026-04", 5, 100.0, DeletedAt="2026-04-06"),
            _item("2026-04", 6, 100.0, Ignored=True),
            _item("2026-04", 7, 100.0, StatementSource="rbc-chequing"),
            _item("2026-04", 8, 100.0, txn_type="deposit"),
            _item("2026-04", 9, 100.0, txn_type=None),
            _item("2026-04", 10, None),
            _item("2026-04", 11, 100.0),
        ]
        tables = build_tables({"2026-04": items})
        assert tables.categories["groceries"].monthly_totals == [200.0]

    def test_statement_and_enriched_rows_count(self) -> None:
        # L2 regression pin: a statement-created (`_stmt_`) row and an enriched
        # email row (StatementSource stamped onto a normal DateFileName) both count.
        stmt = {
            "DateFileName": "2026.04.03_00.00_stmt_simplii_ab12cd34.pdf",
            "Amount": 1900.0,
            "TransactionType": "purchase",
            "Category": "mortgage",
            "StatementSource": "simplii",
        }
        enriched = _item("2026-04", 9, 50.0, StatementSource="simplii")
        tables = build_tables({"2026-04": [stmt, enriched]})
        assert tables.categories["mortgage"].monthly_totals == [1900.0]
        assert tables.categories["groceries"].monthly_totals == [50.0]
        assert tables.overall.monthly_totals == [1950.0]

    def test_skips_malformed_date_file_name(self) -> None:
        items = [
            {"DateFileName": "garbage", "Amount": 50.0, "TransactionType": "purchase", "Category": "groceries"},
            _item("2026-04", 12, 75.0),
        ]
        tables = build_tables({"2026-04": items})
        assert tables.categories["groceries"].monthly_totals == [75.0]

    def test_category_absent_in_a_month_is_not_counted_active(self) -> None:
        tables = build_tables(
            {
                "2026-03": [_item("2026-03", 10, 100.0)],
                "2026-04": [_item("2026-04", 10, 100.0, category="gas")],
            }
        )
        assert tables.categories["groceries"].months_active == 1
        assert tables.categories["gas"].months_active == 1

    def test_defaults_missing_category_to_miscellaneous(self) -> None:
        item = _item("2026-04", 10, 100.0)
        item["Category"] = None
        tables = build_tables({"2026-04": [item]})
        assert "miscellaneous" in tables.categories


# ---------------------------------------------------------------------------
# build_tables — overall history (L1)
# ---------------------------------------------------------------------------


class TestOverallHistory:
    def test_overall_history_aligned_with_months(self) -> None:
        # 6-month window; 2026-03 has no transactions.
        items = {
            "2026-01": [_item("2026-01", 10, 100.0)],
            "2026-02": [_item("2026-02", 10, 100.0, category="gas")],
            "2026-03": [],
            "2026-04": [_item("2026-04", 10, 100.0)],
            "2026-05": [_item("2026-05", 10, 100.0)],
            "2026-06": [_item("2026-06", 10, 100.0)],
        }
        tables = build_tables(items)
        overall = tables.overall
        # One entry per window month, index-aligned with tables.months.
        assert len(overall.curves) == 6
        assert len(overall.monthly_totals) == 6
        assert tables.months == ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
        empty_idx = tables.months.index("2026-03")
        assert overall.curves[empty_idx] == []
        assert overall.monthly_totals[empty_idx] == 0.0
        # Overall spans categories (gas in Feb still contributes).
        assert overall.monthly_totals[tables.months.index("2026-02")] == 100.0

    def test_overall_excludes_deleted_ignored_deposits(self) -> None:
        items = [
            _item("2026-04", 5, 100.0, DeletedAt="2026-04-06"),
            _item("2026-04", 6, 100.0, Ignored=True),
            _item("2026-04", 7, 100.0, StatementSource="rbc-chequing"),
            _item("2026-04", 8, 100.0, txn_type="deposit"),
            _item("2026-04", 9, 100.0, txn_type=None),
            _item("2026-04", 10, None),
            _item("2026-04", 11, 100.0),
        ]
        tables = build_tables({"2026-04": items})
        # L2: the statement-enriched (day 7) and email (day 11) purchases both count.
        assert tables.overall.monthly_totals == [200.0]
        assert tables.overall.curves == [[(7 / 30, 0.5), (11 / 30, 1.0)]]

    def test_overall_defaults_when_constructed_without_it(self) -> None:
        # Existing constructions (categories/months only) keep working.
        tables = ForecastTables(categories={}, months=["2026-05"])
        assert tables.overall.curves == []
        assert tables.overall.monthly_totals == []


# ---------------------------------------------------------------------------
# compute_month_pace (tier L3)
# ---------------------------------------------------------------------------


def _overall_tables(overall: CategoryHistory, months: list[str] | None = None) -> ForecastTables:
    return ForecastTables(categories={}, months=months or [], overall=overall)


class TestComputeMonthPace:
    def test_compute_month_pace_fields(self) -> None:
        # 4 uniform-thirds months, total 900 each. June 20 (30 days) → position
        # 2/3, where the uniform curve reads exactly 2/3.
        curve = [(1 / 3, 1 / 3), (2 / 3, 2 / 3), (1.0, 1.0)]
        overall = CategoryHistory(curves=[list(curve) for _ in range(4)], monthly_totals=[900.0] * 4)
        tables = _overall_tables(overall, ["2026-02", "2026-03", "2026-04", "2026-05"])
        today = date(2026, 6, 20)

        result = compute_month_pace(tables, 500.0, 5, today)
        assert result is not None
        assert result["day_of_month"] == 20
        assert result["days_in_month"] == 30
        # previous = fraction(2/3) * total = 2/3 * 900 = 600.
        assert result["previous_to_date"] == pytest.approx(600.0)
        # typical = median of [600, 600, 600, 600].
        assert result["typical_to_date"] == pytest.approx(600.0)

        fc = project_category(overall, 500.0, 5, today)
        assert fc is not None
        assert result["projected_month_total"] == fc.month_total == pytest.approx(800.0)
        assert result["projected_lower"] == fc.lower
        assert result["projected_upper"] == fc.upper
        assert result["forecast_quality"] == fc.quality == "forecast"

    def test_compute_month_pace_prev_month_empty(self) -> None:
        curve = [(1 / 3, 1 / 3), (2 / 3, 2 / 3), (1.0, 1.0)]
        overall = CategoryHistory(
            curves=[list(curve), list(curve), list(curve), []],
            monthly_totals=[900.0, 900.0, 900.0, 0.0],
        )
        tables = _overall_tables(overall, ["2026-02", "2026-03", "2026-04", "2026-05"])
        today = date(2026, 6, 20)

        result = compute_month_pace(tables, 500.0, 5, today)
        assert result is not None
        # Empty last month → fraction(1.0) * 0.0 = 0.0.
        assert result["previous_to_date"] == 0.0
        # Projection still computed (from the whole overall history).
        fc = project_category(overall, 500.0, 5, today)
        assert fc is not None
        assert result["projected_month_total"] == fc.month_total
        assert result["projected_month_total"] is not None

    def test_compute_month_pace_single_active_month(self) -> None:
        # Exactly one spending month → typical is None; projection takes the
        # limited linear-extrapolation path.
        overall = CategoryHistory(curves=[[(0.5, 1.0)]], monthly_totals=[600.0])
        tables = _overall_tables(overall, ["2026-05"])
        today = date(2026, 6, 10)

        result = compute_month_pace(tables, 300.0, 5, today)
        assert result is not None
        assert result["typical_to_date"] is None
        assert result["forecast_quality"] == "limited"
        assert result["projected_month_total"] == pytest.approx(900.0)  # 300 / (10/30)
        assert result["projected_lower"] is None
        assert result["projected_upper"] is None

    def test_compute_month_pace_all_zero_window(self) -> None:
        overall = CategoryHistory(curves=[[], [], []], monthly_totals=[0.0, 0.0, 0.0])
        tables = _overall_tables(overall, ["2026-03", "2026-04", "2026-05"])
        assert compute_month_pace(tables, 0.0, 0, date(2026, 6, 10)) is None

    def test_compute_month_pace_empty_window(self) -> None:
        # Default overall (no months) is treated as empty.
        tables = ForecastTables(categories={}, months=[])
        assert compute_month_pace(tables, 0.0, 0, date(2026, 6, 10)) is None

    def test_compute_month_pace_day_boundaries(self) -> None:
        curve = [(1 / 3, 1 / 3), (2 / 3, 2 / 3), (1.0, 1.0)]
        overall = CategoryHistory(curves=[list(curve) for _ in range(3)], monthly_totals=[900.0] * 3)
        tables = _overall_tables(overall, ["2026-03", "2026-04", "2026-05"])

        # Day 1: position 1/30, no division by zero, fraction clamped to [0, 1].
        first = compute_month_pace(tables, 100.0, 5, date(2026, 6, 1))
        assert first is not None
        assert first["day_of_month"] == 1
        assert 0.0 <= first["previous_to_date"] <= 900.0

        # Last day: position 1.0, fraction saturates at 1.0.
        last = compute_month_pace(tables, 800.0, 5, date(2026, 6, 30))
        assert last is not None
        assert last["day_of_month"] == 30
        assert last["days_in_month"] == 30
        assert last["previous_to_date"] == pytest.approx(900.0)
        assert last["typical_to_date"] is not None
        assert 0.0 <= last["typical_to_date"] <= 900.0


# ---------------------------------------------------------------------------
# compute_commitment_pace, per L5
# ---------------------------------------------------------------------------


def _charge(merchant: str, amount: float, day: int, status: str, **overrides: Any) -> ExpectedCharge:
    base: dict[str, Any] = {
        "merchant": merchant,
        "display_name": merchant.title(),
        "amount_estimate": amount,
        "expected_day": day,
        "status": status,
        "channel": "email",
        "cadence": "monthly",
        "category": "subscriptions",
    }
    base.update(overrides)
    return ExpectedCharge(**base)


class TestCommitmentPace:
    def _tables(self) -> ForecastTables:
        return _overall_tables(_uniform_history(4, 900.0), ["2026-02", "2026-03", "2026-04", "2026-05"])

    def _disc_tables(self) -> ForecastTables:
        return _overall_tables(_uniform_history(4, 600.0), ["2026-02", "2026-03", "2026-04", "2026-05"])

    def test_sums_to_observed_assumed_upcoming_everyday(self) -> None:
        today = date(2026, 6, 20)  # position 2/3
        upcoming = UpcomingResult(
            charges=[
                _charge("upco", 100.0, 25, "upcoming"),
                _charge("assumeco", 200.0, 5, "assumed", channel="statement"),
                _charge("arrivedco", 50.0, 10, "arrived", actual_amount=50.0, actual_date="2026-06-10"),
                _charge("goneco", 30.0, 1, "unrecorded"),
            ],
            recurring_merchants={"upco", "assumeco", "arrivedco", "goneco"},
        )
        result = compute_commitment_pace(self._tables(), self._disc_tables(), upcoming, 500.0, 5, [], today)
        assert result is not None
        bd = result["breakdown"]
        assert bd["observed_mtd"] == 500.0
        assert bd["assumed_committed"] == 200.0
        assert bd["upcoming_committed"] == 100.0
        # discretionary_mtd = 500 - 50 arrived = 450; everyday = 650 - 450 = 200.
        assert bd["everyday_remainder"] == pytest.approx(200.0)
        # projected total sums observed 500, assumed 200, upcoming 100, everyday 200.
        assert result["projected_month_total"] == pytest.approx(1000.0)
        assert {c["status"] for c in bd["charges"]} == {"upcoming", "assumed", "arrived", "unrecorded"}

    def test_unrecorded_counts_in_neither_committed_term(self) -> None:
        today = date(2026, 6, 20)
        upcoming = UpcomingResult(charges=[_charge("goneco", 300.0, 1, "unrecorded")], recurring_merchants={"goneco"})
        result = compute_commitment_pace(self._tables(), self._disc_tables(), upcoming, 500.0, 5, [], today)
        assert result is not None
        bd = result["breakdown"]
        assert bd["assumed_committed"] == 0.0
        assert bd["upcoming_committed"] == 0.0
        # projected excludes the unrecorded 300: 500 + everyday(700-500=200) = 700.
        assert result["projected_month_total"] == pytest.approx(700.0)

    def test_current_month_statement_row_subtracted_from_discretionary(self) -> None:
        today = date(2026, 6, 20)
        # A recurring statement row already imported this month (not an arrived
        # expected charge) is removed from the discretionary slice.
        stmt_row = {
            "DateFileName": "2026.06.01_00.00_stmt_simplii_ab12cd34.pdf",
            "Amount": 200.0,
            "TransactionType": "purchase",
            "Company": "northwind property co",
        }
        upcoming = UpcomingResult(
            charges=[_charge("upco", 100.0, 25, "upcoming")], recurring_merchants={"northwind property co", "upco"}
        )
        result = compute_commitment_pace(self._tables(), self._disc_tables(), upcoming, 500.0, 5, [stmt_row], today)
        assert result is not None
        # discretionary_mtd = 500 - 200 stmt = 300; everyday = 600·(1/3)+300 -300...
        # blend = 300 + (1/3)*600 = 500; remainder = 200.
        assert result["breakdown"]["everyday_remainder"] == pytest.approx(200.0)

    def test_prev_month_arrival_not_subtracted_from_discretionary(self) -> None:
        # A boundary-fuzz arrival (day-1 merchant that posted on Feb 28) matches a
        # PREVIOUS-month row: its amount was never in observed_mtd, so it must not
        # be subtracted from the discretionary slice. current_count=2 forces the
        # historical projection path, where discretionary_mtd drives the remainder.
        today = date(2026, 3, 20)
        months = ["2025-11", "2025-12", "2026-01", "2026-02"]
        tables = _overall_tables(_uniform_history(4, 3600.0), months)
        disc = _overall_tables(_uniform_history(4, 3000.0), months)

        prev = UpcomingResult(
            charges=[_charge("rent", 2150.0, 1, "arrived", actual_amount=2150.0, actual_date="2026-02-28")],
            recurring_merchants={"rent"},
        )
        result = compute_commitment_pace(tables, disc, prev, 2500.0, 2, [], today)
        assert result is not None
        # discretionary_mtd stays 2500, so everyday = max(3000, 2500) - 2500 = 500.
        assert result["breakdown"]["everyday_remainder"] == pytest.approx(500.0)
        assert result["projected_month_total"] == pytest.approx(3000.0)  # 2500 + 500

        curr = UpcomingResult(
            charges=[_charge("rent", 2150.0, 1, "arrived", actual_amount=2150.0, actual_date="2026-03-01")],
            recurring_merchants={"rent"},
        )
        result_curr = compute_commitment_pace(tables, disc, curr, 2500.0, 2, [], today)
        assert result_curr is not None
        # Current-month arrival IS subtracted: disc_mtd = 350, so everyday = 3000 - 350 = 2650.
        assert result_curr["breakdown"]["everyday_remainder"] == pytest.approx(2650.0)
        assert result_curr["projected_month_total"] == pytest.approx(5150.0)

    def test_empty_upcoming_falls_back_to_month_pace(self) -> None:
        today = date(2026, 6, 20)
        upcoming = UpcomingResult(charges=[], recurring_merchants=set())
        result = compute_commitment_pace(self._tables(), self._disc_tables(), upcoming, 500.0, 5, [], today)
        base = compute_month_pace(self._tables(), 500.0, 5, today)
        assert result is not None
        assert base is not None
        assert result["breakdown"] is None
        assert result["projected_month_total"] == base["projected_month_total"]

    def test_zero_window_returns_none(self) -> None:
        overall = CategoryHistory(curves=[[], [], []], monthly_totals=[0.0, 0.0, 0.0])
        tables = _overall_tables(overall, ["2026-03", "2026-04", "2026-05"])
        upcoming = UpcomingResult(charges=[_charge("upco", 100.0, 25, "upcoming")], recurring_merchants={"upco"})
        assert compute_commitment_pace(tables, tables, upcoming, 0.0, 0, [], date(2026, 6, 10)) is None


class TestDiscretionaryTables:
    def test_removing_recurring_merchant_rows_lowers_totals(self) -> None:
        rows = [
            _item("2026-04", 10, 100.0, Company="Groceries R Us"),
            _item("2026-04", 1, 2150.0, Company="Landlord PAD", category="rent"),
        ]
        full = build_tables({"2026-04": rows})
        recurring = {"Landlord PAD"}
        discretionary = build_tables({"2026-04": [r for r in rows if (r.get("Company") or "") not in recurring]})
        assert full.overall.monthly_totals == [2250.0]
        assert discretionary.overall.monthly_totals == [100.0]


# ---------------------------------------------------------------------------
# _fraction_at
# ---------------------------------------------------------------------------


class TestFractionAt:
    def test_anchored_at_zero_and_interpolates_linearly(self) -> None:
        curve = [(0.5, 1.0)]
        assert _fraction_at(curve, 0.0) == 0.0
        assert _fraction_at(curve, 0.25) == pytest.approx(0.5)
        assert _fraction_at(curve, 0.5) == pytest.approx(1.0)

    def test_flat_at_one_after_last_transaction(self) -> None:
        assert _fraction_at([(0.5, 1.0)], 0.75) == 1.0

    def test_interpolates_between_points(self) -> None:
        curve = [(1 / 3, 1 / 3), (2 / 3, 2 / 3), (1.0, 1.0)]
        assert _fraction_at(curve, 0.5) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# project_category
# ---------------------------------------------------------------------------


class TestProjectCategory:
    def test_forecast_path_blends_ratio_with_historical_mean(self) -> None:
        # Day 20 of June (30 days): elapsed = 2/3, fraction at 2/3 is exactly 2/3.
        # Blend reduces to current + (1 - f) * mean = 500 + (1/3) * 900 = 800.
        fc = project_category(_uniform_history(), 500.0, 5, date(2026, 6, 20))
        assert fc is not None
        assert fc.quality == "forecast"
        assert fc.month_total == pytest.approx(800.0)
        # Identical historical months → zero variance → degenerate band.
        assert fc.lower == pytest.approx(800.0)
        assert fc.upper == pytest.approx(800.0)

    def test_early_month_uses_historical_mean(self) -> None:
        fc = project_category(_uniform_history(), 120.0, 5, date(2026, 6, 3))
        assert fc is not None
        assert fc.quality == "historical"
        assert fc.month_total == pytest.approx(900.0)

    def test_few_current_transactions_uses_historical_mean(self) -> None:
        fc = project_category(_uniform_history(), 500.0, 2, date(2026, 6, 20))
        assert fc is not None
        assert fc.quality == "historical"
        assert fc.month_total == pytest.approx(900.0)

    def test_historical_mean_is_clamped_to_current_spend(self) -> None:
        fc = project_category(_uniform_history(), 1500.0, 2, date(2026, 6, 20))
        assert fc is not None
        assert fc.month_total == pytest.approx(1500.0)

    def test_no_history_linear_extrapolation(self) -> None:
        # Day 10 of June: elapsed = 1/3 → projected = 300 / (1/3) = 900.
        fc = project_category(None, 300.0, 5, date(2026, 6, 10))
        assert fc is not None
        assert fc.quality == "limited"
        assert fc.month_total == pytest.approx(900.0)
        assert fc.lower is None
        assert fc.upper is None

    def test_single_historical_month_is_limited(self) -> None:
        history = CategoryHistory(curves=[[(0.5, 1.0)]], monthly_totals=[600.0])
        fc = project_category(history, 300.0, 5, date(2026, 6, 10))
        assert fc is not None
        assert fc.quality == "limited"

    def test_no_history_and_no_spend_returns_none(self) -> None:
        assert project_category(None, 0.0, 0, date(2026, 6, 10)) is None

    def test_band_widened_below_four_months(self) -> None:
        # Three months, identical mid-month curves, totals 600/900/1200.
        # At position 0.5: implied totals = current + 0.5 * total → stdev = 150.
        # Spread = 0.675 * 150 * 1.5 (widened) = 151.875.
        curve = [(0.5, 0.5), (1.0, 1.0)]
        history = CategoryHistory(curves=[list(curve) for _ in range(3)], monthly_totals=[600.0, 900.0, 1200.0])
        fc = project_category(history, 400.0, 5, date(2026, 6, 15))
        assert fc is not None
        assert fc.quality == "forecast"
        assert fc.month_total == pytest.approx(850.0)  # 400 + 0.5 * 900
        assert fc.lower == pytest.approx(850.0 - 151.88, abs=0.01)
        assert fc.upper == pytest.approx(850.0 + 151.88, abs=0.01)

    def test_band_lower_clamped_to_current_spend(self) -> None:
        curve = [(0.5, 0.5), (1.0, 1.0)]
        history = CategoryHistory(curves=[list(curve) for _ in range(3)], monthly_totals=[600.0, 900.0, 1200.0])
        fc = project_category(history, 2000.0, 5, date(2026, 6, 15))
        assert fc is not None
        assert fc.lower is not None
        assert fc.lower >= 2000.0


# ---------------------------------------------------------------------------
# ForecastService cache
# ---------------------------------------------------------------------------


class TestForecastServiceCache:
    def test_store_and_get(self) -> None:
        svc = ForecastService()
        tables = ForecastTables(categories={}, months=["2026-05"])
        assert svc.get_cached("w1") is None
        svc.store("w1", tables)
        assert svc.get_cached("w1") is tables

    def test_new_window_evicts_old(self) -> None:
        svc = ForecastService()
        svc.store("w1", ForecastTables(categories={}, months=[]))
        svc.store("w2", ForecastTables(categories={}, months=[]))
        assert svc.get_cached("w1") is None
        assert svc.get_cached("w2") is not None

    def test_ttl_expiry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import src.finance.forecast_service as fs

        clock = {"now": 1_000_000.0}
        monkeypatch.setattr(fs.time, "time", lambda: clock["now"])
        svc = ForecastService()
        svc.store("w1", ForecastTables(categories={}, months=[]))
        clock["now"] += 3599
        assert svc.get_cached("w1") is not None
        clock["now"] += 2
        assert svc.get_cached("w1") is None

    def test_invalidate(self) -> None:
        svc = ForecastService()
        svc.store("w1", ForecastTables(categories={}, months=[]))
        svc.invalidate_cache()
        assert svc.get_cached("w1") is None


# ---------------------------------------------------------------------------
# ForecastService concurrency (single-flight get_or_build)
# ---------------------------------------------------------------------------


class TestForecastServiceConcurrency:
    def test_get_or_build_single_flight(self) -> None:
        """8 threads hit a cold window simultaneously; the builder runs once and
        every caller gets the same result object."""
        svc = ForecastService()
        barrier = threading.Barrier(8)
        calls = 0
        calls_lock = threading.Lock()
        sentinel = ForecastTables(categories={}, months=["2026-06"])

        def builder() -> ForecastTables:
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.05)  # hold the miss long enough for all threads to pile on
            return sentinel

        results: list[ForecastTables] = []
        results_lock = threading.Lock()

        def worker() -> None:
            barrier.wait()
            tables = svc.get_or_build("w1", builder)
            with results_lock:
                results.append(tables)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert all(not t.is_alive() for t in threads)
        assert calls == 1
        assert len(results) == 8
        assert all(r is sentinel for r in results)

    def test_invalidate_during_build_no_deadlock(self) -> None:
        """invalidate_cache() from one thread while another is mid-build must
        neither deadlock nor corrupt: it blocks on the lock, then clears once the
        build stores its result."""
        svc = ForecastService()
        build_started = threading.Event()
        release_build = threading.Event()
        sentinel = ForecastTables(categories={}, months=["2026-06"])

        def builder() -> ForecastTables:
            build_started.set()
            release_build.wait(timeout=5)
            return sentinel

        build_result: list[ForecastTables] = []

        def build_thread() -> None:
            build_result.append(svc.get_or_build("w1", builder))

        invalidate_done = threading.Event()

        def invalidate_thread() -> None:
            build_started.wait(timeout=5)
            # Let the build finish, then invalidate — invalidate_cache must wait
            # for get_or_build to release the lock (held across builder + store).
            release_build.set()
            svc.invalidate_cache()
            invalidate_done.set()

        bt = threading.Thread(target=build_thread)
        it = threading.Thread(target=invalidate_thread)
        bt.start()
        it.start()
        bt.join(timeout=5)
        it.join(timeout=5)

        assert not bt.is_alive()
        assert not it.is_alive()
        assert invalidate_done.is_set()
        assert build_result == [sentinel]
        # invalidate always runs after the store (both need the lock), so the
        # window is cleared — proving the two serialized rather than raced.
        assert svc.get_cached("w1") is None
