"""Direct unit tests for the extracted budget status computation.

These pin the exact numeric output of the pure functions in
``src.api.routers.budget_helpers`` without going through a ``TestClient`` — the
whole point of the A8 extraction. Any changed literal here is a behavior change.
"""

from datetime import date

import pytest

from src.api.models import BudgetCategoryConfig, BudgetConfigResponse, BudgetGroupConfig
from src.api.routers.budget_helpers import (
    AggregatedSpending,
    aggregate_summaries,
    build_category_details,
    build_groups_and_unbudgeted,
    compute_status_value,
    elapsed_fractions,
)


def _config(
    *,
    ceiling: float,
    categories: dict[str, BudgetCategoryConfig],
    groups: list[BudgetGroupConfig] | None = None,
) -> BudgetConfigResponse:
    return BudgetConfigResponse(
        year=2026,
        spending_ceiling=ceiling,
        categories=categories,
        groups=groups or [],
        targets_version=1,
        groups_version=1,
        allocated_total=0.0,
        unallocated=0.0,
    )


def _cat(target: float, monthly: float, ctype: str) -> BudgetCategoryConfig:
    return BudgetCategoryConfig(target=target, input_mode="monthly", monthly_amount=monthly, category_type=ctype)


def _empty_aggregated(**overrides) -> AggregatedSpending:
    base: dict = {
        "ytd_by_cat": {},
        "current_month_by_cat": {},
        "current_month_counts": {},
        "monthly_by_cat": {},
        "total_ytd": 0.0,
        "prior_year_by_cat": {},
    }
    base.update(overrides)
    return AggregatedSpending(**base)


# ---------------------------------------------------------------------------
# elapsed_fractions — leap vs non-leap year fraction, unrounded month fraction
# ---------------------------------------------------------------------------


class TestElapsedFractions:
    def test_leap_year_full(self) -> None:
        eyf, _ = elapsed_fractions(date(2024, 12, 31), 2024)  # day 366 of 366
        assert eyf == 1.0

    def test_leap_vs_non_leap_march_1(self) -> None:
        # Mar 1 is day 61 in a leap year, day 60 otherwise — different fractions.
        leap, _ = elapsed_fractions(date(2024, 3, 1), 2024)
        non_leap, _ = elapsed_fractions(date(2026, 3, 1), 2026)
        assert leap == round(61 / 366, 3)  # 0.167
        assert non_leap == round(60 / 365, 3)  # 0.164
        assert leap != non_leap

    def test_may_7_non_leap(self) -> None:
        eyf, _ = elapsed_fractions(date(2026, 5, 7), 2026)  # day 127
        assert eyf == 0.348

    def test_month_fraction_is_unrounded(self) -> None:
        _, emf = elapsed_fractions(date(2026, 5, 7), 2026)  # 7 of 31 days
        assert emf == 7 / 31  # exact float, no rounding
        assert emf != round(7 / 31, 3)


# ---------------------------------------------------------------------------
# compute_status_value — the 5% band classifier and its edges
# ---------------------------------------------------------------------------


class TestComputeStatusValue:
    def test_expected_zero_is_on_track(self) -> None:
        assert compute_status_value(-100.0, 0.0) == "on_track"

    def test_positive_variance_is_under(self) -> None:
        assert compute_status_value(10.0, 100.0) == "under"

    def test_zero_variance_is_on_track(self) -> None:
        assert compute_status_value(0.0, 100.0) == "on_track"

    def test_exactly_five_percent_is_on_track(self) -> None:
        assert compute_status_value(-5.0, 100.0) == "on_track"

    def test_beyond_five_percent_is_over(self) -> None:
        assert compute_status_value(-6.0, 100.0) == "over"


# ---------------------------------------------------------------------------
# build_category_details — variable / lumpy / fixed detail math + overall
# ---------------------------------------------------------------------------


class TestBuildCategoryDetails:
    def test_variable_category_every_field(self) -> None:
        config = _config(ceiling=24000, categories={"groceries": _cat(12000, 1000, "variable")})
        aggregated = _empty_aggregated(
            ytd_by_cat={"groceries": 5000.0},
            current_month_by_cat={"groceries": 400.0},
            monthly_by_cat={"groceries": [1000.0] * 5 + [0.0] * 7},
            total_ytd=5000.0,
        )
        details, _ = build_category_details(config, aggregated, 0.5, 0.5, None)
        d = details["groceries"]
        assert d.category == "groceries"
        assert d.target == 12000.0
        assert d.monthly_amount == 1000.0
        assert d.category_type == "variable"
        assert d.current_month_spent == 400.0
        assert d.current_month_expected == 500.0  # monthly * emf
        assert d.ytd_spent == 5000.0
        assert d.ytd_expected == 6000.0  # target * eyf
        assert d.variance == 100.0  # 500 - 400
        assert d.pace_percent == 80.0  # 400/500*100
        assert d.status == "under"
        assert d.prior_year_total is None

    def test_lumpy_current_month_expected_special_case(self) -> None:
        config = _config(ceiling=24000, categories={"travel": _cat(6000, 500, "lumpy")})
        aggregated = _empty_aggregated(
            ytd_by_cat={"travel": 2000.0},
            current_month_by_cat={"travel": 100.0},
            total_ytd=2000.0,
        )
        details, _ = build_category_details(config, aggregated, 0.5, 0.5, None)
        d = details["travel"]
        assert d.category_type == "lumpy"
        assert d.current_month_spent == 100.0
        # Lumpy special case: current_month_expected uses monthly_amount * emf,
        # NOT the target-based ``expected`` (which would be 3000).
        assert d.current_month_expected == 250.0  # 500 * 0.5
        assert d.ytd_spent == 2000.0
        assert d.ytd_expected == 3000.0  # target * eyf (== expected for lumpy)
        assert d.variance == 1000.0  # 3000 - 2000
        assert d.pace_percent == 66.7  # 2000/3000*100
        assert d.status == "under"

    def test_fixed_category_within_band(self) -> None:
        config = _config(ceiling=24000, categories={"rent": _cat(12000, 1000, "fixed")})
        aggregated = _empty_aggregated(
            ytd_by_cat={"rent": 6000.0},
            current_month_by_cat={"rent": 1000.0},
            total_ytd=6000.0,
        )
        details, _ = build_category_details(config, aggregated, 0.5, 0.5, None)
        d = details["rent"]
        assert d.category_type == "fixed"
        assert d.current_month_expected == 1000.0  # monthly_amount, not * emf
        assert d.variance == 0.0
        assert d.pace_percent == 100.0
        assert d.status == "on_track"

    def test_fixed_override_off_within_five_percent(self) -> None:
        # 3% under budget: base status on_track, override does NOT fire.
        config = _config(ceiling=24000, categories={"rent": _cat(12000, 1000, "fixed")})
        aggregated = _empty_aggregated(current_month_by_cat={"rent": 1030.0})
        details, _ = build_category_details(config, aggregated, 0.5, 0.5, None)
        assert details["rent"].status == "on_track"

    def test_fixed_override_on_beyond_five_percent(self) -> None:
        # 10% underspent: base status would be "under" (variance > 0), but the
        # fixed >5%-deviation override forces "over".
        config = _config(ceiling=24000, categories={"rent": _cat(12000, 1000, "fixed")})
        aggregated = _empty_aggregated(current_month_by_cat={"rent": 900.0})
        details, _ = build_category_details(config, aggregated, 0.5, 0.5, None)
        d = details["rent"]
        assert d.variance == 100.0  # 1000 - 900 > 0 → base "under"
        assert d.status == "over"  # override fired

    def test_overall_headline_ahead(self) -> None:
        config = _config(ceiling=100000, categories={})
        aggregated = _empty_aggregated(total_ytd=37655.0)
        _, overall = build_category_details(config, aggregated, 0.5, 0.5, None)
        assert overall.expected_pace == 50000.0
        assert overall.variance == 12345.0  # 50000 - 37655
        assert overall.status == "under"
        assert overall.headline == "$12,345 ahead of pace"

    def test_overall_headline_over_budget(self) -> None:
        config = _config(ceiling=1000, categories={})
        aggregated = _empty_aggregated(total_ytd=800.0)
        _, overall = build_category_details(config, aggregated, 0.5, 0.5, None)
        assert overall.variance == -300.0  # 500 - 800
        assert overall.headline == "$300 over budget"


# ---------------------------------------------------------------------------
# aggregate_summaries — YTD / current-month / monthly / prior-year rollups
# ---------------------------------------------------------------------------


class TestAggregateSummaries:
    def test_rolls_up_ytd_current_and_monthly(self) -> None:
        month_summaries = [
            {"year_month": "2026-01", "by_category": {"groceries": {"amount": 1000, "count": 10}}},
            {"year_month": "2026-05", "by_category": {"groceries": {"amount": 400, "count": 4}}},
        ]
        agg = aggregate_summaries(month_summaries, [], "2026-05", None)
        assert agg.ytd_by_cat == {"groceries": 1400.0}
        assert agg.total_ytd == 1400.0
        assert agg.current_month_by_cat == {"groceries": 400.0}
        assert agg.current_month_counts == {"groceries": 4}
        assert agg.monthly_by_cat["groceries"][0] == 1000.0  # Jan
        assert agg.monthly_by_cat["groceries"][4] == 400.0  # May
        assert agg.prior_year_by_cat == {}

    def test_prior_year_only_when_compare_year(self) -> None:
        compare = [{"year_month": "2025-01", "by_category": {"groceries": {"amount": 900, "count": 9}}}]
        with_compare = aggregate_summaries([], compare, "2026-05", 2025)
        assert with_compare.prior_year_by_cat == {"groceries": 900.0}
        without = aggregate_summaries([], compare, "2026-05", None)
        assert without.prior_year_by_cat == {}


# ---------------------------------------------------------------------------
# build_groups_and_unbudgeted — group rollups + prior-year + unbudgeted list
# ---------------------------------------------------------------------------


class TestBuildGroupsAndUnbudgeted:
    def test_group_rollup_with_prior_year(self) -> None:
        config = _config(
            ceiling=24000,
            categories={
                "groceries": _cat(12000, 1000, "variable"),
                "rent": _cat(12000, 1000, "fixed"),
            },
            groups=[BudgetGroupConfig(name="Living", categories=["groceries", "rent"])],
        )
        aggregated = _empty_aggregated(
            ytd_by_cat={"groceries": 5000.0, "rent": 6000.0, "office": 300.0},
            current_month_by_cat={"groceries": 400.0, "rent": 1000.0, "office": 50.0},
            monthly_by_cat={
                "groceries": [1000.0] * 5 + [0.0] * 7,
                "rent": [1200.0] * 5 + [0.0] * 7,
            },
            total_ytd=11300.0,
            prior_year_by_cat={"groceries": 4800.0, "rent": 5800.0},
        )
        details, _ = build_category_details(config, aggregated, 0.5, 0.5, 2025)
        groups, unbudgeted, monthly_totals, total_prior = build_groups_and_unbudgeted(
            config, details, aggregated, {}, 0.5, 2025
        )

        assert len(groups) == 1
        g = groups[0]
        assert g.name == "Living"
        assert g.budgeted_total == 24000.0  # 12000 + 12000
        assert g.ytd_spent == 11000.0  # 5000 + 6000
        assert g.expected_pace == 12000.0  # 24000 * 0.5
        assert g.variance == 1000.0  # 12000 - 11000
        assert g.status == "under"
        assert g.monthly_totals[0] == 2200.0  # 1000 + 1200
        assert g.prior_year_total == 10600.0  # 4800 + 5800

        # Overall monthly totals + prior-year roll up across groups.
        assert monthly_totals[0] == 2200.0
        assert total_prior == 10600.0

        # office is unbudgeted (not in config.categories).
        assert len(unbudgeted) == 1
        u = unbudgeted[0]
        assert u.category == "office"
        assert u.ytd_spent == 300.0
        assert u.current_month_spent == 50.0
        assert u.monthly_avg_historical == 0.0  # empty hist_cats

    def test_no_prior_year_when_compare_year_none(self) -> None:
        config = _config(
            ceiling=12000,
            categories={"groceries": _cat(12000, 1000, "variable")},
            groups=[BudgetGroupConfig(name="Food", categories=["groceries"])],
        )
        aggregated = _empty_aggregated(
            ytd_by_cat={"groceries": 5000.0},
            monthly_by_cat={"groceries": [1000.0] * 5 + [0.0] * 7},
            total_ytd=5000.0,
        )
        details, _ = build_category_details(config, aggregated, 0.5, 0.5, None)
        groups, _unbudgeted, _monthly, total_prior = build_groups_and_unbudgeted(
            config, details, aggregated, {}, 0.5, None
        )
        assert groups[0].prior_year_total is None
        assert total_prior is None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
