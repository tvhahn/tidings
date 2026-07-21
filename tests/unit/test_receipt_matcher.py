"""Tier-ranked receipt matcher (pure) — src/finance/receipt_matcher.py.

Items are built with ``tests.factories.make_transaction_item`` (lowercase
categories, PascalCase keys). The matcher constants (L8) are not tunable, so these
tests pin the exact tier boundaries.
"""

from __future__ import annotations

from decimal import Decimal

from src.finance.receipt_matcher import (
    MAX_CANDIDATES,
    RECEIPT_AMOUNT_TOL,
    RECEIPT_DATE_WINDOW_DAYS,
    find_candidates,
)
from tests.factories import make_transaction_item


def _item(date_file_name: str, amount: str, company: str, **overrides: object) -> dict:
    return make_transaction_item(
        DateFileName=date_file_name,
        Amount=Decimal(amount),
        Company=company,
        **overrides,
    )


def _parse(merchant: str = "Booster Juice", date: str = "2026-02-15", total: float = 42.50) -> dict:
    return {"merchant": merchant, "date": date, "total": total}


def _by_month(*items: dict) -> dict[str, list[dict]]:
    return {"2026-02": list(items)}


class TestTier1:
    def test_exact_same_day_normalized_merchant_first(self) -> None:
        # Store-number variant on the transaction, bare name on the receipt.
        exact = _item("2026.02.15_10.30_a.eml", "42.50", "BOOSTER JUICE #123")
        # A nearby-but-not-exact-merchant row that only makes tier 2.
        other = _item("2026.02.15_11.00_b.eml", "42.50", "Some Cafe")
        result = find_candidates(_parse(), _by_month(exact, other), {}, set())
        assert result[0].tier == 1
        assert result[0].date_file_name == "2026.02.15_10.30_a.eml"
        assert result[0].company == "BOOSTER JUICE #123"
        # The merchant-mismatched row is tier 2 (amount + same day within window).
        assert result[1].tier == 2

    def test_alias_resolves_both_sides(self) -> None:
        item = _item("2026.02.15_10.30_a.eml", "42.50", "BJ CANADA")
        aliases = {"bj canada": "Booster Juice"}
        result = find_candidates(_parse(), _by_month(item), aliases, set())
        assert result[0].tier == 1


class TestTierOrderingAndTip:
    def test_t2_before_t3(self) -> None:
        # T2: amount within tol, one day off, merchant differs.
        t2 = _item("2026.02.16_10.00_a.eml", "42.50", "Cafe A")
        # T3: 18% tip over total, same window, merchant differs.
        t3 = _item("2026.02.16_10.00_b.eml", "50.15", "Cafe B")  # 42.50 * 1.18
        result = find_candidates(_parse(), _by_month(t2, t3), {}, set())
        assert [c.tier for c in result] == [2, 3]

    def test_tip_18pct_included_25pct_excluded(self) -> None:
        within = _item("2026.02.15_10.00_a.eml", "50.15", "Cafe A")  # +18%
        over = _item("2026.02.15_10.00_b.eml", "53.13", "Cafe B")  # +25%
        result = find_candidates(_parse(), _by_month(within, over), {}, set())
        keys = {c.date_file_name for c in result}
        assert "2026.02.15_10.00_a.eml" in keys
        assert "2026.02.15_10.00_b.eml" not in keys


class TestBoundaries:
    def test_day_window_in_and_out(self) -> None:
        within = _item("2026.02.18_10.00_a.eml", "42.50", "Cafe A")  # +3 days
        outside = _item("2026.02.19_10.00_b.eml", "42.50", "Cafe B")  # +4 days
        result = find_candidates(_parse(), _by_month(within, outside), {}, set())
        keys = {c.date_file_name for c in result}
        assert "2026.02.18_10.00_a.eml" in keys
        assert "2026.02.19_10.00_b.eml" not in keys
        assert RECEIPT_DATE_WINDOW_DAYS == 3

    def test_amount_tol_edge(self) -> None:
        # Off by exactly the tolerance is still within (<=), same day, merchant differs -> T2.
        edge = _item("2026.02.15_10.00_a.eml", str(42.50 + RECEIPT_AMOUNT_TOL), "Cafe A")
        result = find_candidates(_parse(), _by_month(edge), {}, set())
        assert result
        assert result[0].tier == 2

    def test_month_boundary_pulls_prior_month(self) -> None:
        # Receipt on the 1st; the matching transaction is the prior month's last day.
        prior = _item("2026.01.31_10.00_a.eml", "42.50", "Booster Juice")
        items = {"2026-02": [], "2026-01": [prior]}
        result = find_candidates(_parse(date="2026-02-01"), items, {}, set())
        assert result
        assert result[0].date_file_name == "2026.01.31_10.00_a.eml"
        # 1 day apart (not same day), so tier 2 despite the exact amount + merchant.
        assert result[0].tier == 2


class TestExclusionsAndReceiptFlag:
    def test_deleted_ignored_deposit_excluded(self) -> None:
        deleted = _item("2026.02.15_10.00_a.eml", "42.50", "Booster Juice", DeletedAt="2026-02-16")
        ignored = _item("2026.02.15_10.01_b.eml", "42.50", "Booster Juice", Ignored=True)
        deposit = _item("2026.02.15_10.02_c.eml", "42.50", "Booster Juice", TransactionType="deposit")
        result = find_candidates(_parse(), _by_month(deleted, ignored, deposit), {}, set())
        assert result == []

    def test_already_has_receipt_sorts_after_bare(self) -> None:
        bare = _item("2026.02.15_10.00_bare.eml", "42.50", "Booster Juice")
        has = _item("2026.02.15_10.00_has.eml", "42.50", "Booster Juice")
        linked = {("user@example.com", "2026.02.15_10.00_has.eml")}
        result = find_candidates(_parse(), _by_month(bare, has), {}, linked)
        assert [c.date_file_name for c in result] == [
            "2026.02.15_10.00_bare.eml",
            "2026.02.15_10.00_has.eml",
        ]
        assert result[0].already_has_receipt is False
        assert result[1].already_has_receipt is True

    def test_max_candidates_cap(self) -> None:
        items = [_item(f"2026.02.15_10.{i:02d}_x.eml", "42.50", f"Cafe {i}") for i in range(MAX_CANDIDATES + 4)]
        result = find_candidates(_parse(), _by_month(*items), {}, set())
        assert len(result) == MAX_CANDIDATES
