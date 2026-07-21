"""Tests for daily summary context gathering."""

from typing import Any

from src.finance.daily_summary_context import gather_daily_contexts


class TestGatherDailyContexts:
    def _make_day(
        self,
        date: str,
        day_total: float = 50.0,
        count: int = 2,
        mtd_total: float = 100.0,
        transactions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if transactions is None:
            transactions = [
                {"company": "Grocery Store", "amount": 30.0, "category": "Groceries"},
                {"company": "Coffee Shop", "amount": 20.0, "category": "Restaurant/Dining"},
            ]
        return {
            "date": date,
            "day_total": day_total,
            "count": count,
            "mtd_total": mtd_total,
            "transactions": transactions,
        }

    def test_empty_input_returns_empty(self):
        assert gather_daily_contexts([]) == []

    def test_basic_context_structure(self):
        days = [self._make_day("2026-04-15")]
        result = gather_daily_contexts(days, budget_ceiling=3000.0)
        assert len(result) == 1
        ctx = result[0]
        assert ctx["date"] == "2026-04-15"
        assert ctx["day_of_week"] == "Wednesday"
        assert ctx["day_total"] == 50.0
        assert ctx["transaction_count"] == 2
        assert ctx["mtd_total"] == 100.0
        assert ctx["month_day_number"] == 15
        assert ctx["month_total_days"] == 30
        assert ctx["budget_ceiling_monthly"] == 3000.0

    def test_transactions_compacted(self):
        days = [self._make_day("2026-04-15")]
        result = gather_daily_contexts(days)
        txns = result[0]["transactions"]
        assert len(txns) == 2
        assert txns[0]["company"] == "Grocery Store"
        assert txns[0]["amount"] == 30.0
        assert txns[0]["category"] == "Groceries"

    def test_mtd_by_category_computed(self):
        days = [self._make_day("2026-04-15")]
        result = gather_daily_contexts(days)
        mtd_cat = result[0]["mtd_by_category"]
        assert mtd_cat["Groceries"] == 30.0
        assert mtd_cat["Restaurant/Dining"] == 20.0

    def test_no_budget_ceiling(self):
        days = [self._make_day("2026-04-15")]
        result = gather_daily_contexts(days, budget_ceiling=None)
        assert result[0]["budget_ceiling_monthly"] is None

    def test_previous_month_total(self):
        days = [self._make_day("2026-04-15")]
        result = gather_daily_contexts(days, prev_month_total=2500.0)
        assert result[0]["previous_month_total"] == 2500.0

    def test_multiple_days(self):
        days = [
            self._make_day("2026-04-14", mtd_total=50.0),
            self._make_day("2026-04-15", mtd_total=100.0),
        ]
        result = gather_daily_contexts(days)
        assert len(result) == 2
        assert result[0]["date"] == "2026-04-14"
        assert result[1]["date"] == "2026-04-15"

    def test_days_in_month_february(self):
        days = [self._make_day("2026-02-15")]
        result = gather_daily_contexts(days)
        assert result[0]["month_total_days"] == 28

    def test_days_in_month_january(self):
        days = [self._make_day("2026-01-10")]
        result = gather_daily_contexts(days)
        assert result[0]["month_total_days"] == 31

    def test_pace_pct_without_budget(self):
        days = [self._make_day("2026-04-15", mtd_total=1000.0)]
        result = gather_daily_contexts(days, budget_ceiling=None)
        assert result[0]["expected_pace_pct"] == 50.0  # day 15 of 30
        assert result[0]["actual_pace_pct"] is None

    def test_pace_pct_with_budget(self):
        days = [self._make_day("2026-04-15", mtd_total=1500.0)]
        result = gather_daily_contexts(days, budget_ceiling=3000.0)
        assert result[0]["actual_pace_pct"] == 50.0  # 1500 / 3000

    def test_monthly_context_forwards_trend_avg(self):
        days = [self._make_day("2026-04-15")]
        monthly = {
            "trend": [
                {"year_month": "2025-11", "total_spending": 2000},
                {"year_month": "2025-12", "total_spending": 3000},
                {"year_month": "2026-01", "total_spending": 2500},
                {"year_month": "2026-02", "total_spending": 2700},
                {"year_month": "2026-03", "total_spending": 2800},
                {"year_month": "2026-04", "total_spending": 1000},  # excluded (current)
            ],
            "anomalies": [],
            "category_deltas": [],
        }
        result = gather_daily_contexts(days, monthly_context=monthly)
        # Average of 5 prior months: (2000+3000+2500+2700+2800)/5 = 2600
        assert result[0]["trend_avg_6mo"] == 2600.0

    def test_monthly_context_forwards_top_anomalies(self):
        days = [self._make_day("2026-04-15")]
        monthly = {
            "trend": [],
            "anomalies": [
                {"category": "Groceries", "current": 800, "baseline": 400, "reason": "above"},
                {"category": "Gas", "current": 0, "baseline": 200, "reason": "below"},
                {"category": "Dining", "current": 100, "baseline": 50, "reason": "above"},
            ],
            "category_deltas": [],
        }
        result = gather_daily_contexts(days, monthly_context=monthly)
        anoms = result[0]["top_anomalies"]
        assert len(anoms) == 2
        assert anoms[0]["category"] == "Groceries"
        assert anoms[1]["category"] == "Gas"

    def test_monthly_context_forwards_top_category_deltas(self):
        days = [self._make_day("2026-04-15")]
        monthly = {
            "trend": [],
            "anomalies": [],
            "category_deltas": [
                {"category": "A", "current": 500, "previous": 100, "delta_pct": 400.0},
                {"category": "B", "current": 200, "previous": 300, "delta_pct": -33.3},
                {"category": "C", "current": 50, "previous": 60, "delta_pct": -16.7},
                {"category": "D", "current": 10, "previous": 15, "delta_pct": -33.3},
            ],
        }
        result = gather_daily_contexts(days, monthly_context=monthly)
        deltas = result[0]["category_deltas_top"]
        assert len(deltas) == 3
        assert deltas[0]["category"] == "A"

    def test_no_monthly_context_uses_safe_defaults(self):
        days = [self._make_day("2026-04-15")]
        result = gather_daily_contexts(days)
        assert result[0]["trend_avg_6mo"] is None
        assert result[0]["top_anomalies"] == []
        assert result[0]["category_deltas_top"] == []

    # --- upcoming_tomorrow (L15): the day-before heads-up line ----------------

    def test_upcoming_tomorrow_absent_defaults_empty(self):
        days = [self._make_day("2026-04-15")]
        result = gather_daily_contexts(days)  # no upcoming_by_date param
        assert result[0]["upcoming_tomorrow"] == []

    def test_upcoming_tomorrow_present_for_next_day(self):
        # The charge lands on the 16th; the 15th's context surfaces it.
        days = [self._make_day("2026-04-15")]
        upcoming = {
            "2026-04-16": [
                {"display_name": "Rent", "amount_estimate": 2150.0, "channel": "statement", "expected_day": 16}
            ]
        }
        result = gather_daily_contexts(days, upcoming_by_date=upcoming)
        tomorrow = result[0]["upcoming_tomorrow"]
        assert len(tomorrow) == 1
        assert tomorrow[0]["display_name"] == "Rent"
        assert tomorrow[0]["amount_estimate"] == 2150.0
        assert tomorrow[0]["channel"] == "statement"
        assert tomorrow[0]["expected_day"] == 16

    def test_upcoming_tomorrow_empty_when_no_charge_next_day(self):
        # A charge exists in the map, but not for the day AFTER the 15th.
        days = [self._make_day("2026-04-15")]
        upcoming = {
            "2026-04-20": [
                {"display_name": "Insurance", "amount_estimate": 183.0, "channel": "email", "expected_day": 20}
            ]
        }
        result = gather_daily_contexts(days, upcoming_by_date=upcoming)
        assert result[0]["upcoming_tomorrow"] == []

    def test_upcoming_tomorrow_crosses_month_boundary(self):
        # The 30th's "tomorrow" is May 1 — a next-month key still resolves.
        days = [self._make_day("2026-04-30")]
        upcoming = {
            "2026-05-01": [
                {"display_name": "Rent", "amount_estimate": 2150.0, "channel": "statement", "expected_day": 1}
            ]
        }
        result = gather_daily_contexts(days, upcoming_by_date=upcoming)
        assert len(result[0]["upcoming_tomorrow"]) == 1
        assert result[0]["upcoming_tomorrow"][0]["display_name"] == "Rent"
