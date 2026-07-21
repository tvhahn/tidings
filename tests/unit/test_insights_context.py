"""Unit tests for insights context assembly (src/finance/insights_context.py).

The API endpoint test (test_api_insights.py) drives ``gather_context`` with
services passed in, which leaves the pure helpers, the no-service auto-construct
fallback, and the to-file wrapper uncovered. These cover them directly.
"""

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from src.finance.insights_context import (
    _annotated_amounts_by_category,
    _build_pace,
    _compute_category_deltas,
    _fixed_charges,
    _largest_transactions,
    _recurring_annual,
    _same_month_last_year,
    _strip_decimals,
    _suspected_ignored,
    _truncate_at_paragraph,
    gather_context,
    gather_context_to_file,
    latest_briefing_for_month,
)


def _txn(**over: Any) -> dict[str, Any]:
    base = {
        "Date": "05/01/2026 10:00 PDT",
        "Company": "Merchant",
        "Amount": Decimal(10),
        "Category": "groceries",
        "TransactionType": "purchase",
        "Comment": None,
        "Ignored": None,
        "DeletedAt": None,
    }
    base.update(over)
    return base


class TestComputeCategoryDeltas:
    def test_percent_when_previous_positive(self) -> None:
        out = _compute_category_deltas(
            {"groceries": {"amount": 150}},
            {"groceries": {"amount": 100}},
        )
        assert out[0]["category"] == "groceries"
        assert out[0]["delta_amount"] == 50.0
        assert out[0]["delta_pct"] == 50.0

    def test_percent_is_none_when_previous_zero(self) -> None:
        # A category with no prior-month spend → percent is undefined, not inf.
        out = _compute_category_deltas({"dining": {"amount": 80}}, {})
        assert out[0]["delta_pct"] is None
        assert out[0]["delta_amount"] == 80.0

    def test_sorted_by_absolute_delta_and_capped_at_top_n(self) -> None:
        current = {f"c{i}": {"amount": i * 10} for i in range(8)}
        out = _compute_category_deltas(current, {}, top_n=3)
        assert len(out) == 3
        amounts = [d["delta_amount"] for d in out]
        assert amounts == sorted(amounts, key=abs, reverse=True)
        assert out[0]["category"] == "c7"  # biggest mover ranks first


class TestStripDecimals:
    def test_scalar_decimal_becomes_float(self) -> None:
        result = _strip_decimals(Decimal("4.50"))
        assert result == 4.5
        assert isinstance(result, float)

    def test_recurses_through_dict_list_and_tuple(self) -> None:
        out = _strip_decimals({"a": [Decimal(1)], "b": (Decimal(2), 3)})
        assert out == {"a": [1.0], "b": (2.0, 3)}
        assert isinstance(out["b"], tuple)  # tuple branch (line 63) preserves shape

    def test_passes_through_non_decimal(self) -> None:
        assert _strip_decimals("x") == "x"
        assert _strip_decimals(7) == 7


class TestAnnotatedAmounts:
    def test_sums_commented_live_spending_per_category(self) -> None:
        items = [
            _txn(Category="miscellaneous", Amount=Decimal("84.99"), Comment="desk lamp"),
            _txn(Category="miscellaneous", Amount=Decimal(50), Comment=None),  # no comment
            _txn(Category="groceries", Amount=Decimal(20), Comment="split with roommate"),
        ]
        out = _annotated_amounts_by_category(items)
        assert out == {"miscellaneous": 84.99, "groceries": 20.0}

    def test_excludes_ignored_deleted_and_non_spending(self) -> None:
        items = [
            _txn(Category="misc", Amount=Decimal(100), Comment="x", Ignored=True),
            _txn(Category="misc", Amount=Decimal(200), Comment="y", DeletedAt="2026-05-02"),
            _txn(Category="misc", Amount=Decimal(300), Comment="z", TransactionType="deposit"),
        ]
        assert _annotated_amounts_by_category(items) == {}


class TestLargestTransactions:
    def test_top_n_sorted_desc_with_conditional_comment(self) -> None:
        items = [
            _txn(Company="A", Amount=Decimal(10)),
            _txn(Company="B", Amount=Decimal(500), Comment="big one"),
            _txn(Company="C", Amount=Decimal(250)),
            _txn(Company=None, Amount=Decimal(999), Ignored=True),  # ignored — excluded
        ]
        out = _largest_transactions(items, n=2)
        assert [t["company"] for t in out] == ["B", "C"]
        assert out[0]["amount"] == 500.0
        assert out[0]["comment"] == "big one"
        assert "comment" not in out[1]  # only present when the txn has one

    def test_unknown_company_fallback(self) -> None:
        out = _largest_transactions([_txn(Company=None, Amount=Decimal(40))])
        assert out[0]["company"] == "Unknown"


class TestSuspectedIgnored:
    def test_flags_merchant_usually_ignored(self) -> None:
        target = [_txn(Company="Mapletrade", Amount=Decimal(500))]
        prior = [
            _txn(Company="Mapletrade", Ignored=True),
            _txn(Company="Mapletrade", Ignored=True),
            _txn(Company="Mapletrade", Ignored=True),
            _txn(Company="Mapletrade", Ignored=None),  # 3/4 ignored → share 0.75
        ]
        out = _suspected_ignored(target, prior)
        assert len(out) == 1
        assert out[0]["company"] == "Mapletrade"
        assert out[0]["amount"] == 500.0
        assert out[0]["count"] == 1
        assert out[0]["historical_ignored_share"] == 0.75

    def test_below_thresholds_not_flagged(self) -> None:
        target = [_txn(Company="Rare", Amount=Decimal(30)), _txn(Company="Clean", Amount=Decimal(40))]
        prior = [
            _txn(Company="Rare", Ignored=True),  # only 1 ignored → below the >=2 floor
            _txn(Company="Rare", Ignored=None),
            _txn(Company="Clean", Ignored=None),
            _txn(Company="Clean", Ignored=None),  # never ignored
        ]
        assert _suspected_ignored(target, prior) == []


class TestBuildPace:
    def _ytd_summaries(self) -> list[dict[str, Any]]:
        # Jan..May. groceries $600/mo (ytd 3000); insurance $880 once (Jan);
        # misc $20/mo (ytd 100, unbudgeted).
        summaries = []
        for i in range(5):
            by_cat: dict[str, Any] = {
                "groceries": {"amount": Decimal(600), "count": 1},
                "misc": {"amount": Decimal(20), "count": 1},
            }
            total = Decimal(620)
            if i == 0:
                by_cat["insurance"] = {"amount": Decimal(880), "count": 1}
                total = Decimal(1500)
            summaries.append({"total_spending": total, "by_category": by_cat})
        return summaries

    def _pace(self) -> dict[str, Any]:
        return _build_pace(
            year=2026,
            month_num=5,
            targets_categories={
                "groceries": {"category_type": "variable", "target": 6000, "monthly_amount": 500},
                "insurance": {"category_type": "lumpy", "target": 4800, "monthly_amount": 400},
            },
            spending_ceiling=12000,
            ytd_summaries=self._ytd_summaries(),
            current_by_category={"groceries": {"amount": Decimal(600)}, "misc": {"amount": Decimal(20)}},
            is_current_calendar_month=False,
            today_day=15,
        )

    def test_ceiling_math(self) -> None:
        ceiling = self._pace()["ceiling"]
        assert ceiling["annual"] == 12000.0
        assert ceiling["ytd_spent"] == 3980.0
        assert ceiling["prorated_to_date"] == 5000.0  # 12000 * 5/12
        assert ceiling["variance_amount"] == -1020.0
        assert ceiling["projected_naive"] == 9552.0  # 3980 / 5 * 12

    def test_projected_adjusted_treats_lumpy_as_done(self) -> None:
        # groceries 3000/5*12=7200 + insurance max(880,4800)=4800 + misc 100/5*12=240
        assert self._pace()["ceiling"]["projected_adjusted"] == 12240.0

    def test_variable_category_shape(self) -> None:
        groceries = next(c for c in self._pace()["categories"] if c["category"] == "groceries")
        assert groceries["expected_to_date"] == 2500.0  # 500 * 5
        assert groceries["ytd_actual"] == 3000.0
        assert groceries["variance_amount"] == 500.0
        assert groceries["assessment"] == "ahead"  # spending faster than prorated target
        assert "pct_of_annual" not in groceries  # lumpy-only field omitted

    def test_lumpy_category_shape(self) -> None:
        insurance = next(c for c in self._pace()["categories"] if c["category"] == "insurance")
        assert insurance["pct_of_annual"] == 18.33  # 880 / 4800 * 100
        assert insurance["remaining_expected"] == 3920.0
        assert insurance["assessment"] == "annual — assess against full-year target"
        assert "expected_to_date" not in insurance  # variable-only field omitted

    def test_unbudgeted_and_no_month_progress(self) -> None:
        pace = self._pace()
        assert pace["unbudgeted"] == [{"category": "misc", "ytd_actual": 100.0, "month_actual": 20.0}]
        assert pace["month_progress"] is None

    def test_month_progress_when_current(self) -> None:
        pace = _build_pace(
            year=2026,
            month_num=5,
            targets_categories={},
            spending_ceiling=12000,
            ytd_summaries=self._ytd_summaries(),
            current_by_category={"groceries": {"amount": Decimal(600)}},
            is_current_calendar_month=True,
            today_day=10,
        )
        mp = pace["month_progress"]
        assert mp == {"days_elapsed": 10, "days_in_month": 31, "projected_month_end": 1860.0}


class TestGatherContextTrim:
    """gather_context trims per-company detail off trend/previous and adds the new blocks."""

    def _services(self) -> tuple[MagicMock, MagicMock]:
        def summary(ym: str) -> dict[str, Any]:
            return {
                "year_month": ym,
                "total_spending": Decimal(1000),
                "spending_count": 3,
                "by_category": {"groceries": {"amount": Decimal(1000), "count": 3}},
                "by_company": {"Store": {"amount": Decimal(1000), "count": 3, "category": "groceries"}},
                "deposits_by_company": {"Payroll": {"amount": Decimal(5000), "count": 1}},
                "top_categories": [["groceries", {"amount": Decimal(1000), "count": 3}]],
                "deposit_total": Decimal(5000),
                "deposit_count": 1,
            }

        ss = MagicMock()
        ss.get_summary.side_effect = summary
        ss.get_summary_with_comparison.return_value = {
            "current": summary("2026-05"),
            "previous": summary("2026-04"),
            "delta_amount": 0.0,
            "delta_percent": 0.0,
        }
        ss.query_month.return_value = [_txn(Amount=Decimal(300), Comment="note")]

        bs = MagicMock()
        bs.get_targets.return_value = {
            "Data": {
                "spending_ceiling": 12000,
                "categories": {"groceries": {"category_type": "variable", "target": 6000, "monthly_amount": 500}},
            }
        }
        bs.get_historical_averages.return_value = {"categories": {}}
        bs.get_category_anomalies.return_value = []
        return ss, bs

    def test_trim_and_new_blocks(self) -> None:
        ss, bs = self._services()
        with (
            patch("src.finance.insights_context.latest_briefing_for_month", return_value=None),
            patch("src.finance.insights_context.get_config", return_value={}),
        ):
            ctx = asyncio.run(gather_context("2026-05", spending_summary=ss, budget_service=bs))

        # memory-signal blocks are present with the documented shapes
        assert ctx["same_month_last_year"] is not None  # 2025-05 has data in the stub
        assert ctx["same_month_last_year"]["year_month"] == "2025-05"
        assert isinstance(ctx["recurring_annual"], list)
        assert isinstance(ctx["fixed_charges"], list)
        # the always-active stub merchant "Store" reads as a flat fixed charge
        assert any(f["company"] == "Store" for f in ctx["fixed_charges"])
        assert ctx["previous_briefing"] is None
        assert ctx["user_memo"] is None

        # current_month keeps full detail
        assert "by_company" in ctx["current_month"]
        # previous_month keeps by_category + top_categories, drops per-company + deposits
        assert "by_category" in ctx["previous_month"]
        assert "top_categories" in ctx["previous_month"]
        assert "by_company" not in ctx["previous_month"]
        assert "deposits_by_company" not in ctx["previous_month"]
        # trend entries are trimmed to the four essentials
        for entry in ctx["trend"]:
            assert set(entry) == {"year_month", "total_spending", "spending_count", "by_category"}
        # new top-level blocks present
        assert ctx["pace"] is not None
        assert ctx["pace"]["ceiling"]["annual"] == 12000.0
        assert isinstance(ctx["largest_transactions"], list)
        assert ctx["largest_transactions"][0]["amount"] == 300.0
        assert isinstance(ctx["suspected_ignored"], list)

    def test_pace_null_without_targets(self) -> None:
        ss, bs = self._services()
        bs.get_targets.return_value = None
        with (
            patch("src.finance.insights_context.latest_briefing_for_month", return_value=None),
            patch("src.finance.insights_context.get_config", return_value={}),
        ):
            ctx = asyncio.run(gather_context("2026-05", spending_summary=ss, budget_service=bs))
        assert ctx["pace"] is None
        assert ctx["budget"] is None

    def test_user_memo_passthrough(self) -> None:
        ss, bs = self._services()
        memo = "Two kids in daycare; mortgage renews in September."
        with (
            patch("src.finance.insights_context.latest_briefing_for_month", return_value=None),
            patch("src.finance.insights_context.get_config", return_value={"insights_user_memo": memo}),
        ):
            ctx = asyncio.run(gather_context("2026-05", spending_summary=ss, budget_service=bs))
        assert ctx["user_memo"] == memo


def _summary(ym: str, by_category: dict[str, float]) -> dict[str, Any]:
    """Minimal month summary with Decimal amounts, as the services emit."""
    return {
        "year_month": ym,
        "total_spending": Decimal(str(sum(by_category.values()))),
        "spending_count": len(by_category),
        "by_category": {cat: {"amount": Decimal(str(amt)), "count": 1} for cat, amt in by_category.items()},
    }


def _summary_with_companies(ym: str, by_company: dict[str, tuple[float, str]]) -> dict[str, Any]:
    """Month summary carrying per-company detail (amount, category), as fixed_charges reads."""
    return {
        "year_month": ym,
        "by_company": {
            comp: {"amount": Decimal(str(amt)), "count": 1, "category": cat} for comp, (amt, cat) in by_company.items()
        },
    }


class TestSameMonthLastYear:
    def test_present_with_carried_comments(self) -> None:
        summaries = {"2025-05": _summary("2025-05", {"groceries": 1000.0})}
        raw = {
            "2025-05": [
                _txn(
                    Company="Northwind Insurance",
                    Amount=Decimal("1240.00"),
                    Category="insurance",
                    Comment="Home insurance",
                ),
                _txn(Company="Store", Amount=Decimal(50), Comment=None),  # no comment → excluded
            ]
        }
        out = _same_month_last_year("2025-05", summaries, raw)
        assert out is not None
        assert out["year_month"] == "2025-05"
        assert out["comments"] == [
            {
                "date": "05/01/2026 10:00 PDT",
                "company": "Northwind Insurance",
                "amount": Decimal("1240.00"),
                "category": "insurance",
                "comment": "Home insurance",
            }
        ]

    def test_absent_when_no_data(self) -> None:
        # Month present in the lookup but with no spending → treated as no data.
        summaries = {"2025-05": _summary("2025-05", {})}
        assert _same_month_last_year("2025-05", summaries, {}) is None
        # Month missing entirely → also None.
        assert _same_month_last_year("2025-05", {}, {}) is None


class TestRecurringAnnual:
    def _lookback(self) -> tuple[list[str], dict[str, dict[str, Any]]]:
        # 24 months of data. groceries every month ($600); property_tax only in the
        # same month one year ago and the target month ($1750).
        from datetime import date

        from dateutil.relativedelta import relativedelta

        target = date(2026, 5, 1)
        months = [(target - relativedelta(months=i)).strftime("%Y-%m") for i in range(23, -1, -1)]
        summaries: dict[str, dict[str, Any]] = {}
        for ym in months:
            cats = {"groceries": 600.0}
            if ym in ("2025-05", "2026-05"):
                cats["property_tax"] = 1750.0
            summaries[ym] = _summary(ym, cats)
        return months, summaries

    def test_sparse_annual_found_monthly_excluded(self) -> None:
        months, summaries = self._lookback()
        out = _recurring_annual("2026-05", "2025-05", months, summaries)
        cats = {r["category"] for r in out}
        assert "property_tax" in cats  # active 2/24 → sparse annual
        assert "groceries" not in cats  # active 24/24 → monthly, excluded
        pt = next(r for r in out if r["category"] == "property_tax")
        assert pt["typical_amount"] == 1750.0
        assert pt["months_seen"] == ["2025-05", "2026-05"]
        assert pt["last_seen"] == "2026-05"

    def test_below_mean_threshold_excluded(self) -> None:
        # A sparse category whose mean active amount is under $200 is not an "event".
        months, summaries = self._lookback()
        summaries["2026-05"]["by_category"]["small_annual"] = {"amount": Decimal(50), "count": 1}
        summaries["2025-05"]["by_category"]["small_annual"] = {"amount": Decimal(50), "count": 1}
        out = _recurring_annual("2026-05", "2025-05", months, summaries)
        assert "small_annual" not in {r["category"] for r in out}

    def test_requires_active_now_or_same_month_last_year(self) -> None:
        # A sparse, large category that last billed in some off-month (not now, not
        # the same month last year) is not surfaced as landing around this time.
        months, summaries = self._lookback()
        summaries["2025-09"]["by_category"]["autumn_event"] = {"amount": Decimal(900), "count": 1}
        out = _recurring_annual("2026-05", "2025-05", months, summaries)
        assert "autumn_event" not in {r["category"] for r in out}


class TestFixedCharges:
    def test_flat_merchant_included_varying_excluded(self) -> None:
        gas_by_month = {
            "2025-12": 93.0,
            "2026-01": 100.0,
            "2026-02": 107.0,
            "2026-03": 93.0,
            "2026-04": 100.0,
            "2026-05": 107.0,
        }  # mean 100, ~5.7% coefficient of variation → excluded
        baseline = [
            _summary_with_companies(
                ym,
                {
                    "WM": (2950.00, "mortgage"),  # flat every month → CV 0
                    "Gas": (gas_by_month[ym], "transportation"),
                },
            )
            for ym in gas_by_month
        ]
        out = _fixed_charges(baseline)
        companies = {f["company"] for f in out}
        assert "WM" in companies
        assert "Gas" not in companies  # coefficient of variation over threshold
        wm = next(f for f in out if f["company"] == "WM")
        assert wm["category"] == "mortgage"
        assert wm["monthly_amount"] == 2950.00
        assert wm["months_active"] == 6

    def test_too_few_active_months_excluded(self) -> None:
        # Active in only 4 of 6 baseline months (even if perfectly flat) → excluded.
        months = ["2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05"]
        baseline = []
        for i, ym in enumerate(months):
            comps = {"Strata": (390.00, "strata")} if i >= 2 else {}
            baseline.append(_summary_with_companies(ym, comps))
        out = _fixed_charges(baseline)
        assert "Strata" not in {f["company"] for f in out}


class TestTruncateAtParagraph:
    def test_short_text_unchanged(self) -> None:
        assert _truncate_at_paragraph("short", 3000) == "short"

    def test_truncates_at_paragraph_boundary(self) -> None:
        text = "A" * 100 + "\n\n" + "B" * 5000
        out = _truncate_at_paragraph(text, 3000)
        assert out == "A" * 100  # backed up to the blank-line boundary
        assert len(out) <= 3000


class TestLatestBriefingForMonth:
    def test_returns_most_recent_and_truncates(self, tmp_path: Path, monkeypatch: Any) -> None:
        monkeypatch.chdir(tmp_path)
        month_dir = tmp_path / "data" / "insights" / "2026-04"
        month_dir.mkdir(parents=True)
        (month_dir / "2026-04-01_09-00-00.md").write_text("## Old\n\nolder briefing")
        newer = "## Headline\n\n" + "x" * 100 + "\n\n" + "y" * 5000
        (month_dir / "2026-04-15_18-30-00.md").write_text(newer)
        (month_dir / "notes.md").write_text("ignored — stem does not match")

        out = latest_briefing_for_month("2026-04")
        assert out is not None
        assert out["month"] == "2026-04"
        assert out["generated_at"] == "2026-04-15T18:30:00"
        assert out["excerpt"].startswith("## Headline")
        assert len(out["excerpt"]) <= 3000
        assert "y" * 5000 not in out["excerpt"]  # truncated at a paragraph boundary

    def test_absent_when_no_directory(self, tmp_path: Path, monkeypatch: Any) -> None:
        monkeypatch.chdir(tmp_path)
        assert latest_briefing_for_month("2026-04") is None


class TestGatherContextToFile:
    def test_auto_constructs_services_and_writes_json(self, tmp_path: Path) -> None:
        """With no services passed, gather_context builds SQLite-backed defaults
        (isolated to the per-test DB via conftest) and the wrapper persists a
        JSON-safe dict to the given path.
        """
        out_path = tmp_path / "ctx.json"
        result = gather_context_to_file("2026-01", output_path=str(out_path))

        assert out_path.is_file()
        on_disk = json.loads(out_path.read_text())
        assert on_disk["month"] == "2026-01"
        assert result["month"] == "2026-01"
        # Every Decimal was stripped upstream — re-serializing must not raise.
        assert json.dumps(result)
