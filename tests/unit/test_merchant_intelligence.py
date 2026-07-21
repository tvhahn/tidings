"""Tests for MerchantIntelligenceService — recurring detection, price changes,
new/churned classification, and burn-rate computation."""

import threading
import time
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.finance.merchant_intelligence import MerchantIntelligenceService


def _ss_with_history(per_month: dict[str, dict[str, dict[str, Any]]]) -> MagicMock:
    """Build a SpendingSummary mock keyed by year_month.

    `per_month` shape: { "YYYY-MM": { "company": {"amount": Decimal, "count": int, "category": str} } }
    """
    ss = MagicMock(name="spending_summary")

    def get_summary(ym: str) -> dict[str, Any]:
        by_company = per_month.get(ym, {})
        total = sum(float(c.get("amount", 0)) for c in by_company.values())
        return {
            "by_company": by_company,
            "total_spending": total,
        }

    ss.get_summary.side_effect = get_summary
    return ss


def _aliases(map_: dict[str, str] | None = None) -> MagicMock:
    a = MagicMock()
    a.get_aliases_map.return_value = map_ or {}
    return a


def _make_constant_history(
    company: str, amount: Decimal, months: list[str], category: str = "subscriptions"
) -> dict[str, dict[str, dict[str, Any]]]:
    return {ym: {company: {"amount": amount, "count": 1, "category": category}} for ym in months}


WINDOW = ["2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03"]


def test_fixed_subscription_classified_as_fixed():
    history = _make_constant_history("Netflix", Decimal("15.99"), WINDOW)
    svc = MerchantIntelligenceService(_ss_with_history(history), _aliases())
    result = svc.get_intelligence("2026-03", months=6)
    netflix = next(m for m in result["merchants"] if m["company"] == "Netflix")
    assert netflix["frequency_type"] == "fixed"
    assert netflix["is_recurring"] is True
    assert netflix["months_active"] == 6


def test_lumpy_classification_for_intermittent_merchant():
    history: dict[str, dict[str, dict[str, Any]]] = {ym: {} for ym in WINDOW}
    for ym in ["2025-10", "2025-12", "2026-02"]:
        history[ym] = {"Costco": {"amount": Decimal(250), "count": 2, "category": "groceries"}}
    svc = MerchantIntelligenceService(_ss_with_history(history), _aliases())
    result = svc.get_intelligence("2026-03", months=6)
    costco = next(m for m in result["merchants"] if m["company"] == "Costco")
    assert costco["frequency_type"] == "lumpy"
    assert costco["is_recurring"] is False


def test_price_change_flagged_above_threshold():
    history: dict[str, dict[str, dict[str, Any]]] = {}
    for ym in WINDOW[:-1]:
        history[ym] = {"Spotify": {"amount": Decimal("9.99"), "count": 1, "category": "subscriptions"}}
    history["2026-03"] = {"Spotify": {"amount": Decimal("11.99"), "count": 1, "category": "subscriptions"}}
    svc = MerchantIntelligenceService(_ss_with_history(history), _aliases())
    result = svc.get_intelligence("2026-03", months=6)
    spotify = next(m for m in result["merchants"] if m["company"] == "Spotify")
    assert spotify["price_change"] is not None
    assert spotify["price_change"]["old_amount"] == 9.99
    assert spotify["price_change"]["new_amount"] == 11.99
    assert spotify["price_change"]["since_month"] == "2026-03"


def test_price_change_below_tolerance_ignored():
    # 1% bump on a $50 charge → below 5% threshold
    history: dict[str, dict[str, dict[str, Any]]] = {}
    for ym in WINDOW[:-1]:
        history[ym] = {"GymCo": {"amount": Decimal("50.00"), "count": 1, "category": "subscriptions"}}
    history["2026-03"] = {"GymCo": {"amount": Decimal("50.50"), "count": 1, "category": "subscriptions"}}
    svc = MerchantIntelligenceService(_ss_with_history(history), _aliases())
    result = svc.get_intelligence("2026-03", months=6)
    gymco = next(m for m in result["merchants"] if m["company"] == "GymCo")
    assert gymco["price_change"] is None


def test_price_change_only_for_fixed_merchants():
    # Highly variable amounts → "variable" → no price-change flag even if last delta is large
    history: dict[str, dict[str, dict[str, Any]]] = {}
    amounts = [Decimal(100), Decimal(220), Decimal(80), Decimal(310), Decimal(90), Decimal(400)]
    for ym, amt in zip(WINDOW, amounts, strict=True):
        history[ym] = {"Restaurant": {"amount": amt, "count": 5, "category": "restaurant/dining"}}
    svc = MerchantIntelligenceService(_ss_with_history(history), _aliases())
    result = svc.get_intelligence("2026-03", months=6)
    rest = next(m for m in result["merchants"] if m["company"] == "Restaurant")
    assert rest["frequency_type"] == "variable"
    assert rest["price_change"] is None


def test_new_merchant_when_active_two_consecutive_months():
    """A merchant active in the current month AND immediately prior month —
    and absent earlier in the window — is "new" (a relationship is forming)."""
    history: dict[str, dict[str, dict[str, Any]]] = {ym: {} for ym in WINDOW}
    history["2026-02"] = {"AnthropicAPI": {"amount": Decimal(20), "count": 1, "category": "subscriptions"}}
    history["2026-03"] = {"AnthropicAPI": {"amount": Decimal(20), "count": 1, "category": "subscriptions"}}
    svc = MerchantIntelligenceService(_ss_with_history(history), _aliases())
    result = svc.get_intelligence("2026-03", months=6)
    new = next(m for m in result["merchants"] if m["company"] == "AnthropicAPI")
    assert new["is_new"] is True


def test_one_off_purchase_is_not_new():
    """A merchant that appears only in the current month is NOT new — this is
    the false positive the prior 3-month-absent rule triggered for one-shot
    purchases (annual fees, single doctor visits)."""
    history: dict[str, dict[str, dict[str, Any]]] = {ym: {} for ym in WINDOW}
    history["2026-03"] = {
        "NorthwindProfessionalAssoc": {"amount": Decimal(950), "count": 1, "category": "professional membership"}
    }
    svc = MerchantIntelligenceService(_ss_with_history(history), _aliases())
    result = svc.get_intelligence("2026-03", months=6)
    rc = next(m for m in result["merchants"] if m["company"] == "NorthwindProfessionalAssoc")
    assert rc["is_new"] is False


def test_not_new_when_active_earlier_in_window():
    """Active in current month + prior month, but ALSO active earlier in the
    window — that's an established merchant, not new."""
    history: dict[str, dict[str, dict[str, Any]]] = {ym: {} for ym in WINDOW}
    history["2025-10"] = {"Foo": {"amount": Decimal(10), "count": 1, "category": "subscriptions"}}
    history["2026-02"] = {"Foo": {"amount": Decimal(10), "count": 1, "category": "subscriptions"}}
    history["2026-03"] = {"Foo": {"amount": Decimal(10), "count": 1, "category": "subscriptions"}}
    svc = MerchantIntelligenceService(_ss_with_history(history), _aliases())
    result = svc.get_intelligence("2026-03", months=6)
    foo = next(m for m in result["merchants"] if m["company"] == "Foo")
    assert foo["is_new"] is False


def test_churned_when_silent_recent_two_months():
    # Was active months 1-4, silent 5-6
    history: dict[str, dict[str, dict[str, Any]]] = {ym: {} for ym in WINDOW}
    for ym in WINDOW[:4]:
        history[ym] = {"OldGym": {"amount": Decimal(30), "count": 1, "category": "sports and recreation"}}
    svc = MerchantIntelligenceService(_ss_with_history(history), _aliases())
    result = svc.get_intelligence("2026-03", months=6)
    old = next(m for m in result["merchants"] if m["company"] == "OldGym")
    assert old["is_churned"] is True


def test_committed_burn_rate_sums_only_fixed():
    history: dict[str, dict[str, dict[str, Any]]] = {ym: {} for ym in WINDOW}
    # Netflix — fixed subscription
    for ym in WINDOW:
        history[ym]["Netflix"] = {"amount": Decimal("15.99"), "count": 1, "category": "subscriptions"}
    # Costco — variable, monthly but inconsistent amounts
    amounts = [Decimal(100), Decimal(220), Decimal(180), Decimal(310), Decimal(90), Decimal(400)]
    for ym, amt in zip(WINDOW, amounts, strict=True):
        history[ym]["Costco"] = {"amount": amt, "count": 3, "category": "groceries"}
    svc = MerchantIntelligenceService(_ss_with_history(history), _aliases())
    result = svc.get_intelligence("2026-03", months=6)
    summary = result["summary"]
    # Burn rate = Netflix avg ($15.99) only — Costco is "variable" so excluded
    assert summary["recurring_burn_rate"] == 15.99
    assert summary["recurring_count"] == 1


def test_alias_normalization_collapses_variants():
    history: dict[str, dict[str, dict[str, Any]]] = {ym: {} for ym in WINDOW}
    # Two raw variants of the same merchant
    for ym in WINDOW:
        history[ym]["NETFLIX BILL #123"] = {"amount": Decimal(8), "count": 1, "category": "subscriptions"}
        history[ym]["NETFLIX BILL #124"] = {"amount": Decimal(8), "count": 1, "category": "subscriptions"}
    aliases = _aliases({"netflix bill #123": "Netflix", "netflix bill #124": "Netflix"})
    svc = MerchantIntelligenceService(_ss_with_history(history), aliases)
    result = svc.get_intelligence("2026-03", months=6)
    matches = [m for m in result["merchants"] if m["company"] == "Netflix"]
    assert len(matches) == 1
    # 6 months * 2 transactions * $8 = $96 total
    assert matches[0]["total"] == 96.0


def test_caches_within_one_hour():
    history = _make_constant_history("Netflix", Decimal("15.99"), WINDOW)
    ss = _ss_with_history(history)
    svc = MerchantIntelligenceService(ss, _aliases())
    svc.get_intelligence("2026-03", months=6)
    initial_calls = ss.get_summary.call_count
    svc.get_intelligence("2026-03", months=6)
    # Same args → cache hit, no extra get_summary calls.
    assert ss.get_summary.call_count == initial_calls


def test_cache_keyed_by_args():
    history = _make_constant_history("Netflix", Decimal("15.99"), WINDOW)
    ss = _ss_with_history(history)
    svc = MerchantIntelligenceService(ss, _aliases())
    svc.get_intelligence("2026-03", months=6)
    initial_calls = ss.get_summary.call_count
    svc.get_intelligence("2026-02", months=6)
    assert ss.get_summary.call_count > initial_calls


def test_sparse_history_degrades_gracefully():
    # Only 1 month of data → all merchants land as "none"
    history: dict[str, dict[str, dict[str, Any]]] = {ym: {} for ym in WINDOW}
    history["2026-03"] = {"OneShot": {"amount": Decimal(50), "count": 1, "category": "miscellaneous"}}
    svc = MerchantIntelligenceService(_ss_with_history(history), _aliases())
    result = svc.get_intelligence("2026-03", months=6)
    one = next(m for m in result["merchants"] if m["company"] == "OneShot")
    # 1 month active → "lumpy", but burn rate should still be 0 since not fixed
    assert one["frequency_type"] == "lumpy"
    assert result["summary"]["recurring_burn_rate"] == 0.0


def test_unknown_merchant_filtered_out():
    """The "Unknown" parser fallback shouldn't surface as a merchant."""
    history: dict[str, dict[str, dict[str, Any]]] = {ym: {} for ym in WINDOW}
    for ym in WINDOW:
        history[ym] = {"Unknown": {"amount": Decimal(50), "count": 1, "category": "miscellaneous"}}
    svc = MerchantIntelligenceService(_ss_with_history(history), _aliases())
    result = svc.get_intelligence("2026-03", months=6)
    assert all(m["company"] != "Unknown" for m in result["merchants"])


def test_interac_memo_strings_filtered_out():
    """Raw Interac e-Transfer descriptions (pipe-delimited memo) shouldn't
    surface as merchants — they're transfer descriptions, not merchant names."""
    memo = "Morgan Westland for the amount of $123.45 (CAD) | Thanks | CAsAmPLe"
    history: dict[str, dict[str, dict[str, Any]]] = {ym: {} for ym in WINDOW}
    history["2026-03"] = {memo: {"amount": Decimal("123.45"), "count": 1, "category": "house maintenance"}}
    svc = MerchantIntelligenceService(_ss_with_history(history), _aliases())
    result = svc.get_intelligence("2026-03", months=6)
    assert all(m["company"] != memo for m in result["merchants"])


def test_get_intelligence_single_flight(monkeypatch: pytest.MonkeyPatch) -> None:
    """8 threads request the same cold (month, months) key simultaneously;
    _compute runs once and every caller shares the result object."""
    ss = _ss_with_history(_make_constant_history("Netflix", Decimal("15.99"), WINDOW))
    svc = MerchantIntelligenceService(ss, _aliases())

    barrier = threading.Barrier(8)
    calls = 0
    calls_lock = threading.Lock()
    sentinel: dict[str, Any] = {"month": "2026-03", "merchants": []}

    def fake_compute(year_month: str, months: int) -> dict[str, Any]:
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.05)  # hold the miss long enough for all threads to pile on
        return sentinel

    monkeypatch.setattr(svc, "_compute", fake_compute)

    results: list[dict[str, Any]] = []
    results_lock = threading.Lock()

    def worker() -> None:
        barrier.wait()
        r = svc.get_intelligence("2026-03", months=6)
        with results_lock:
            results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert all(not t.is_alive() for t in threads)
    assert calls == 1
    assert len(results) == 8
    assert all(r is sentinel for r in results)
