"""Tests for UpcomingService — recurring-profile derivation and the four-state
status machine (L1/L3/L4)."""

from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

import src.finance.upcoming_service as us
from src.finance.upcoming_service import UpcomingResult, UpcomingService

TODAY = date(2026, 7, 17)
CURRENT = "2026-07"


def _row(
    ym: str,
    day: int,
    amount: float,
    company: str,
    category: str = "subscriptions",
    *,
    stmt: bool = False,
    txn_type: str = "purchase",
    seq: int = 10,
    **overrides: Any,
) -> dict[str, Any]:
    if stmt:
        date_file_name = f"{ym[:4]}.{ym[5:7]}.{day:02d}_00.00_stmt_simplii_ab12cd{seq:02d}.pdf"
    else:
        date_file_name = f"{ym[:4]}.{ym[5:7]}.{day:02d}_{seq:02d}.00_{company}.json"
    base: dict[str, Any] = {
        "ForwardedTo": "user@example.com",
        "DateFileName": date_file_name,
        "Amount": Decimal(str(amount)),
        "TransactionType": txn_type,
        "Company": company,
        "Category": category,
    }
    base.update(overrides)
    return base


def _summary(rows_by_month: dict[str, list[dict[str, Any]]]) -> MagicMock:
    ss = MagicMock(name="spending_summary")
    ss.query_month.side_effect = lambda ym, *a, **k: list(rows_by_month.get(ym, []))
    return ss


def _aliases(map_: dict[str, str] | None = None) -> MagicMock:
    a = MagicMock(name="aliases")
    a.get_aliases_map.return_value = map_ or {}
    return a


def _run(
    monkeypatch: pytest.MonkeyPatch,
    rows_by_month: dict[str, list[dict[str, Any]]],
    aliases: dict[str, str] | None = None,
    *,
    today: date = TODAY,
    year_month: str = CURRENT,
) -> UpcomingResult:
    monkeypatch.setattr(us, "forecast_today", lambda: today)
    svc = UpcomingService(_summary(rows_by_month), _aliases(aliases))
    return svc.get_upcoming(year_month)


def _charge(result: UpcomingResult, merchant: str) -> Any:
    return next((c for c in result.charges if c.merchant == merchant), None)


# ---------------------------------------------------------------------------
# Recurring-profile classification, per L3.
# ---------------------------------------------------------------------------


def test_fixed_recurring_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = {ym: [_row(ym, 25, 15.99, "Netflix")] for ym in ["2026-04", "2026-05", "2026-06"]}
    result = _run(monkeypatch, rows)
    charge = _charge(result, "Netflix")
    assert charge is not None
    assert charge.cadence == "monthly"
    assert charge.channel == "email"
    assert charge.amount_estimate == 15.99
    assert charge.status == "upcoming"  # day 25 > today 17
    assert "Netflix" in result.recurring_merchants


def test_variable_recurring_detected_four_of_six(monkeypatch: pytest.MonkeyPatch) -> None:
    # Active 4 of the last 6 complete months with swinging amounts (CV too high
    # for fixed) → variable.
    amounts = {"2026-03": 100.0, "2026-04": 300.0, "2026-05": 150.0, "2026-06": 400.0}
    rows = {ym: [_row(ym, 25, amt, "Costco", category="groceries")] for ym, amt in amounts.items()}
    result = _run(monkeypatch, rows)
    charge = _charge(result, "Costco")
    assert charge is not None
    assert charge.cadence == "monthly"
    # amount_estimate = median of the last 3 charges: median(300, 150, 400) = 300.
    assert charge.amount_estimate == 300.0


def test_annual_detected_two_charges_twelve_months_apart(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = {
        "2025-07": [_row("2025-07", 15, 500.0, "HydroCorp", category="utilities")],
        "2026-07": [_row("2026-07", 15, 500.0, "HydroCorp", category="utilities")],
    }
    result = _run(monkeypatch, rows)
    charge = _charge(result, "HydroCorp")
    assert charge is not None
    assert charge.cadence == "annual"
    assert charge.previous_amount == 500.0
    # This year's July charge is present → arrived.
    assert charge.status == "arrived"
    assert charge.actual_date == "2026-07-15"


def test_annual_single_charge_not_penciled(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = {"2025-07": [_row("2025-07", 15, 500.0, "HydroCorp", category="utilities")]}
    result = _run(monkeypatch, rows)
    assert _charge(result, "HydroCorp") is None
    assert result.recurring_merchants == set()


def test_below_threshold_merchant_produces_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    # Two non-consecutive months only → not fixed, not 4/6, not annual.
    rows = {
        "2026-02": [_row("2026-02", 10, 60.0, "RandoShop")],
        "2026-05": [_row("2026-05", 10, 60.0, "RandoShop")],
    }
    result = _run(monkeypatch, rows)
    assert result.charges == []
    assert result.recurring_merchants == set()


def test_median_day_computation(monkeypatch: pytest.MonkeyPatch) -> None:
    days = {"2026-04": 3, "2026-05": 5, "2026-06": 10}
    rows = {ym: [_row(ym, d, 20.0, "GymCo")] for ym, d in days.items()}
    result = _run(monkeypatch, rows)
    charge = _charge(result, "GymCo")
    assert charge is not None
    assert charge.expected_day == 5  # median(3, 5, 10)


def test_amount_estimate_fixed_uses_most_recent(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = {
        "2026-04": [_row("2026-04", 14, 10.0, "Spotify")],
        "2026-05": [_row("2026-05", 14, 10.0, "Spotify")],
        "2026-06": [_row("2026-06", 14, 12.0, "Spotify")],
    }
    result = _run(monkeypatch, rows)
    charge = _charge(result, "Spotify")
    assert charge is not None
    assert charge.amount_estimate == 12.0  # most recent


def test_amount_estimate_variable_uses_median_of_last_three(monkeypatch: pytest.MonkeyPatch) -> None:
    amounts = {"2026-01": 100.0, "2026-03": 200.0, "2026-05": 300.0, "2026-06": 400.0}
    rows = {ym: [_row(ym, 20, amt, "Uber", category="transportation")] for ym, amt in amounts.items()}
    result = _run(monkeypatch, rows)
    charge = _charge(result, "Uber")
    assert charge is not None
    assert charge.amount_estimate == 300.0  # median(200, 300, 400)


# ---------------------------------------------------------------------------
# Bill-cadence guard (L3)
# ---------------------------------------------------------------------------


def test_bill_cadence_single_charge_per_month_still_classifies(monkeypatch: pytest.MonkeyPatch) -> None:
    # 1 charge/month in 4 of 6 months → mean 1.0/active-month ≤ 1.5 → still a profile.
    amounts = {"2026-03": 100.0, "2026-04": 300.0, "2026-05": 150.0, "2026-06": 400.0}
    rows = {ym: [_row(ym, 20, amt, "Uber", category="transportation")] for ym, amt in amounts.items()}
    result = _run(monkeypatch, rows)
    assert _charge(result, "Uber") is not None
    assert "Uber" in result.recurring_merchants


def test_bill_cadence_multi_visit_variable_guarded_out(monkeypatch: pytest.MonkeyPatch) -> None:
    # 3 charges/month every month with swinging amounts (not fixed, but 6/6 ≥ 4/6):
    # mean 3.0/active-month > 1.5 → neither penciled nor a recurring merchant.
    rows: dict[str, list[dict[str, Any]]] = {}
    swing = {"2026-01": 50.0, "2026-02": 90.0, "2026-03": 40.0, "2026-04": 120.0, "2026-05": 60.0, "2026-06": 110.0}
    for ym, amt in swing.items():
        rows[ym] = [
            _row(ym, d, amt, "NorthwindFoods", category="groceries", seq=s) for d, s in ((5, 8), (15, 10), (25, 12))
        ]
    result = _run(monkeypatch, rows)
    assert _charge(result, "NorthwindFoods") is None
    assert "NorthwindFoods" not in result.recurring_merchants


def test_bill_cadence_multi_visit_fixed_cv_guarded_out(monkeypatch: pytest.MonkeyPatch) -> None:
    # 2 charges/month every month, stable monthly sum (cv < 0.15 → would be fixed):
    # mean 2.0/active-month > 1.5 → still guarded out.
    rows: dict[str, list[dict[str, Any]]] = {}
    for ym in ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]:
        rows[ym] = [
            _row(ym, 10, 100.0, "WalMart", category="groceries", seq=8),
            _row(ym, 20, 100.0, "WalMart", category="groceries", seq=10),
        ]
    result = _run(monkeypatch, rows)
    assert _charge(result, "WalMart") is None
    assert "WalMart" not in result.recurring_merchants


# ---------------------------------------------------------------------------
# Channel classification (L3)
# ---------------------------------------------------------------------------


def test_channel_email(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = {ym: [_row(ym, 14, 20.0, "Netflix")] for ym in ["2026-04", "2026-05", "2026-06"]}
    charge = _charge(_run(monkeypatch, rows), "Netflix")
    assert charge is not None
    assert charge.channel == "email"


def test_channel_statement_via_stmt_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = {ym: [_row(ym, 3, 1900.0, "Mortgage", stmt=True)] for ym in ["2026-04", "2026-05", "2026-06"]}
    charge = _charge(_run(monkeypatch, rows), "Mortgage")
    assert charge is not None
    assert charge.channel == "statement"


def test_channel_mixed(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = {
        "2026-04": [_row("2026-04", 14, 20.0, "Hybrid", stmt=True)],
        "2026-05": [_row("2026-05", 14, 20.0, "Hybrid")],
        "2026-06": [_row("2026-06", 14, 20.0, "Hybrid", stmt=True)],
    }
    charge = _charge(_run(monkeypatch, rows), "Hybrid")
    assert charge is not None
    assert charge.channel == "mixed"


def test_enriched_email_row_counts_as_email(monkeypatch: pytest.MonkeyPatch) -> None:
    # StatementSource stamped onto a normal (non-`_stmt_`) DateFileName → email.
    rows = {ym: [_row(ym, 14, 20.0, "Enriched", StatementSource="simplii")] for ym in ["2026-04", "2026-05", "2026-06"]}
    charge = _charge(_run(monkeypatch, rows), "Enriched")
    assert charge is not None
    assert charge.channel == "email"


# ---------------------------------------------------------------------------
# Status machine (L4)
# ---------------------------------------------------------------------------


def _fixed(company: str, day: int, amount: float, **row_kwargs: Any) -> dict[str, list[dict[str, Any]]]:
    return {ym: [_row(ym, day, amount, company, **row_kwargs)] for ym in ["2026-04", "2026-05", "2026-06"]}


def test_status_upcoming(monkeypatch: pytest.MonkeyPatch) -> None:
    charge = _charge(_run(monkeypatch, _fixed("Netflix", 25, 15.99)), "Netflix")
    assert charge is not None
    assert charge.status == "upcoming"


def test_status_arrived_within_tolerance(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _fixed("Netflix", 10, 50.0)
    rows[CURRENT] = [_row(CURRENT, 10, 50.50, "Netflix")]  # |50.50 - 50| = 0.50 ≤ max($2, 10%)
    charge = _charge(_run(monkeypatch, rows), "Netflix")
    assert charge is not None
    assert charge.status == "arrived"
    assert charge.actual_amount == 50.5
    assert charge.actual_date == "2026-07-10"


def test_status_arrived_via_previous_month_boundary_fuzz(monkeypatch: pytest.MonkeyPatch) -> None:
    # Day-1 merchant whose July charge actually posted on June 30.
    amounts = {"2026-03": 1900.0, "2026-04": 1900.0, "2026-05": 1900.0}
    rows: dict[str, list[dict[str, Any]]] = {ym: [_row(ym, 1, amt, "Mortgage")] for ym, amt in amounts.items()}
    rows["2026-06"] = [_row("2026-06", 30, 1900.0, "Mortgage")]  # early post of July's charge
    charge = _charge(_run(monkeypatch, rows), "Mortgage")
    assert charge is not None
    assert charge.expected_day == 1
    assert charge.status == "arrived"
    assert charge.actual_date == "2026-06-30"


def test_status_assumed_statement_channel_day_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    # Statement-observed, expected day 3 has passed, no current-month row yet.
    charge = _charge(_run(monkeypatch, _fixed("Mortgage", 3, 1900.0, stmt=True)), "Mortgage")
    assert charge is not None
    assert charge.channel == "statement"
    assert charge.status == "assumed"


def test_status_unrecorded_email_channel_past_grace(monkeypatch: pytest.MonkeyPatch) -> None:
    # Email-observed, expected day 1, today 17 → 16 days past (> 3 grace).
    charge = _charge(_run(monkeypatch, _fixed("GymCo", 1, 40.0)), "GymCo")
    assert charge is not None
    assert charge.status == "unrecorded"


def test_status_within_grace_stays_upcoming(monkeypatch: pytest.MonkeyPatch) -> None:
    # Expected day 15, today 17 → 2 days past, within the 3-day grace.
    charge = _charge(_run(monkeypatch, _fixed("GymCo", 15, 40.0)), "GymCo")
    assert charge is not None
    assert charge.status == "upcoming"


# ---------------------------------------------------------------------------
# Exclusions and used-row set
# ---------------------------------------------------------------------------


def test_ignored_rows_never_produce_a_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _fixed("GhostSub", 14, 20.0, Ignored=True)
    result = _run(monkeypatch, rows)
    assert _charge(result, "GhostSub") is None
    assert "GhostSub" not in result.recurring_merchants


def test_deleted_current_row_does_not_match(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _fixed("Netflix", 5, 50.0)
    rows[CURRENT] = [_row(CURRENT, 5, 50.0, "Netflix", DeletedAt="2026-07-06")]
    charge = _charge(_run(monkeypatch, rows), "Netflix")
    assert charge is not None
    assert charge.status != "arrived"
    assert charge.status == "unrecorded"


def test_row_not_shared_across_merchants(monkeypatch: pytest.MonkeyPatch) -> None:
    # Alpha has a current-month row; Beta does not. Beta must not steal Alpha's row.
    rows = {ym: [_row(ym, 10, 50.0, "Alpha"), _row(ym, 10, 50.0, "Beta")] for ym in ["2026-04", "2026-05", "2026-06"]}
    rows[CURRENT] = [_row(CURRENT, 10, 50.0, "Alpha")]
    result = _run(monkeypatch, rows)
    alpha, beta = _charge(result, "Alpha"), _charge(result, "Beta")
    assert alpha is not None
    assert alpha.status == "arrived"
    assert beta is not None
    assert beta.status != "arrived"


def test_used_row_consumed_only_once(monkeypatch: pytest.MonkeyPatch) -> None:
    # Two current-month rows, one expectation → exactly one arrived charge.
    rows = _fixed("Netflix", 10, 50.0)
    rows[CURRENT] = [_row(CURRENT, 10, 50.0, "Netflix", seq=9), _row(CURRENT, 10, 50.0, "Netflix", seq=11)]
    result = _run(monkeypatch, rows)
    netflix = [c for c in result.charges if c.merchant == "Netflix"]
    assert len(netflix) == 1
    assert netflix[0].status == "arrived"


def test_alias_normalization_collapses_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    # Two raw variants of one merchant, alternating months (1 charge/month) so the
    # bill-cadence guard keeps it a monthly profile while alias-collapse is tested.
    variants = {"2026-04": "NETFLIX BILL #1", "2026-05": "NETFLIX BILL #2", "2026-06": "NETFLIX BILL #1"}
    rows = {ym: [_row(ym, 25, 15.99, name)] for ym, name in variants.items()}
    aliases = {"netflix bill": "Netflix"}
    result = _run(monkeypatch, rows, aliases)
    assert _charge(result, "Netflix") is not None


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def test_cache_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(us, "forecast_today", lambda: TODAY)
    clock = {"now": 1_000_000.0}
    monkeypatch.setattr(us.time, "time", lambda: clock["now"])
    ss = _summary(_fixed("Netflix", 25, 15.99))
    svc = UpcomingService(ss, _aliases())

    svc.get_upcoming(CURRENT)
    first_calls = ss.query_month.call_count
    assert first_calls == 14  # 13 complete months + current

    svc.get_upcoming(CURRENT)
    assert ss.query_month.call_count == first_calls  # cache hit

    clock["now"] += 3601
    svc.get_upcoming(CURRENT)
    assert ss.query_month.call_count == first_calls * 2  # recomputed after TTL
