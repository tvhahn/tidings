"""Tests for SpendingSummary aggregation, query, and comparison logic."""

from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.finance.spending_summary import SpendingSummary, get_forwarded_to_addresses
from tests.factories import make_transaction_item

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item(
    amount: str = "50.00",
    txn_type: str = "purchase",
    category: str = "groceries",
    company: str = "Safeway",
    forwarded_to: str = "test@example.com",
) -> dict[str, Any]:
    """Build a DynamoDB-style transaction item for spending summary tests."""
    return make_transaction_item(
        ForwardedTo=forwarded_to,
        DateFileName="2026.01.15_14.30_test.eml",
        Amount=Decimal(amount),
        TransactionType=txn_type,
        Category=category,
        Company=company,
    )


def _make_summary(dyn_resource: MagicMock | None = None) -> SpendingSummary:
    """Create a SpendingSummary with a mock DynamoDB resource."""
    if dyn_resource is None:
        dyn_resource = MagicMock()
        dyn_resource.Table.return_value = MagicMock()
    return SpendingSummary(dyn_resource=dyn_resource)


# ---------------------------------------------------------------------------
# get_forwarded_to_addresses
# ---------------------------------------------------------------------------


class TestGetForwardedToAddresses:
    @patch("src.finance.user_mapping.user_id_cache", {"a@b.com": "user1", "c@d.com": "user2"})
    def test_returns_all_keys(self):
        result = get_forwarded_to_addresses()
        assert set(result) == {"a@b.com", "c@d.com"}

    @patch("src.finance.user_mapping.load_user_mappings")
    def test_loads_mappings_when_empty(self, mock_load: MagicMock) -> None:
        # user_id_cache is already empty from autouse fixture
        get_forwarded_to_addresses()
        mock_load.assert_called_once()


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


class TestAggregate:
    def test_empty_list(self):
        summary = _make_summary()
        result = summary.aggregate([])
        assert result["total_spending"] == Decimal(0)
        assert result["spending_count"] == 0
        assert result["deposit_total"] == Decimal(0)
        assert result["deposit_count"] == 0
        assert result["by_category"] == {}
        assert result["by_company"] == {}
        assert result["top_categories"] == []

    def test_single_purchase(self):
        items = [_make_item(amount="99.99", category="groceries", company="Safeway")]
        result = _make_summary().aggregate(items)
        assert result["total_spending"] == Decimal("99.99")
        assert result["spending_count"] == 1
        assert result["deposit_total"] == Decimal(0)

    def test_multiple_categories(self):
        items = [
            _make_item(amount="100.00", category="groceries", company="Safeway"),
            _make_item(amount="50.00", category="restaurant/dining", company="Starbucks"),
            _make_item(amount="200.00", category="rent", company="Landlord"),
        ]
        result = _make_summary().aggregate(items)
        assert result["total_spending"] == Decimal("350.00")
        assert result["spending_count"] == 3
        # Per-category values (not just count): catches an AI that returns
        # the right set of keys with the wrong amounts or swapped counts.
        assert result["by_category"] == {
            "groceries": {"amount": Decimal("100.00"), "count": 1},
            "restaurant/dining": {"amount": Decimal("50.00"), "count": 1},
            "rent": {"amount": Decimal("200.00"), "count": 1},
        }

    def test_spending_vs_deposits(self):
        items = [
            _make_item(amount="100.00", txn_type="purchase"),
            _make_item(amount="50.00", txn_type="deposit"),
        ]
        result = _make_summary().aggregate(items)
        assert result["total_spending"] == Decimal("100.00")
        assert result["spending_count"] == 1
        assert result["deposit_total"] == Decimal("50.00")
        assert result["deposit_count"] == 1

    def test_e_transfer_counted_as_spending(self):
        items = [_make_item(amount="300.00", txn_type="e-transfer")]
        result = _make_summary().aggregate(items)
        assert result["total_spending"] == Decimal("300.00")
        assert result["spending_count"] == 1

    def test_deposits_by_company(self):
        items = [
            _make_item(amount="2000.00", txn_type="deposit", company="Employer A"),
            _make_item(amount="500.00", txn_type="deposit", company="Employer B"),
            _make_item(amount="1000.00", txn_type="deposit", company="Employer A"),
        ]
        result = _make_summary().aggregate(items)
        assert result["deposit_total"] == Decimal("3500.00")
        assert result["deposit_count"] == 3
        dbc = result["deposits_by_company"]
        assert dbc["Employer A"]["amount"] == Decimal("3000.00")
        assert dbc["Employer A"]["count"] == 2
        assert dbc["Employer B"]["amount"] == Decimal("500.00")
        assert dbc["Employer B"]["count"] == 1

    def test_deposits_by_company_empty_for_no_deposits(self):
        items = [_make_item(amount="100.00", txn_type="purchase")]
        result = _make_summary().aggregate(items)
        assert result["deposits_by_company"] == {}

    def test_preauth_counted_as_spending(self):
        items = [_make_item(amount="75.00", txn_type="preauth")]
        result = _make_summary().aggregate(items)
        assert result["total_spending"] == Decimal("75.00")
        assert result["spending_count"] == 1

    def test_withdrawal_counted_as_spending(self):
        items = [_make_item(amount="200.00", txn_type="withdrawal")]
        result = _make_summary().aggregate(items)
        assert result["total_spending"] == Decimal("200.00")

    def test_none_amount_skipped(self):
        item = _make_item()
        item["Amount"] = None
        result = _make_summary().aggregate([item])
        assert result["total_spending"] == Decimal(0)
        assert result["spending_count"] == 0

    def test_none_transaction_type_skipped(self):
        item = _make_item()
        item["TransactionType"] = None
        result = _make_summary().aggregate([item])
        assert result["total_spending"] == Decimal(0)
        assert result["spending_count"] == 0

    def test_ignored_transactions_excluded(self):
        items = [
            _make_item(amount="100.00", category="groceries"),
            {**_make_item(amount="50.00", category="rent"), "Ignored": True},
        ]
        result = _make_summary().aggregate(items)
        assert result["total_spending"] == Decimal("100.00")
        assert result["spending_count"] == 1

    def test_ignored_false_still_counted(self):
        items = [
            {**_make_item(amount="100.00", category="groceries"), "Ignored": False},
        ]
        result = _make_summary().aggregate(items)
        assert result["total_spending"] == Decimal("100.00")
        assert result["spending_count"] == 1

    def test_deleted_transactions_excluded(self):
        items = [
            _make_item(amount="100.00", category="groceries"),
            {**_make_item(amount="50.00", category="rent"), "DeletedAt": "2026-01-20T00:00:00+00:00"},
        ]
        result = _make_summary().aggregate(items)
        assert result["total_spending"] == Decimal("100.00")
        assert result["spending_count"] == 1


# ---------------------------------------------------------------------------
# Top categories
# ---------------------------------------------------------------------------


class TestTopCategories:
    def test_sorted_by_amount_desc(self):
        items = [
            _make_item(amount="100.00", category="rent"),
            _make_item(amount="500.00", category="groceries"),
            _make_item(amount="200.00", category="restaurant/dining"),
        ]
        result = _make_summary().aggregate(items)
        names = [name for name, _ in result["top_categories"]]
        assert names == ["groceries", "restaurant/dining", "rent"]

    def test_capped_at_five(self):
        items = [_make_item(amount=str(i * 10), category=f"cat_{i}") for i in range(1, 8)]
        result = _make_summary().aggregate(items)
        assert len(result["top_categories"]) == 5

    def test_top_categories_is_top_five_by_amount_descending(self):
        """Catches off-by-one slice, wrong sort key, and swapped-index slop.

        10 distinct categories with strictly descending amounts and identical
        count=1 — so an AI that sorts by count (instead of amount) still has
        to pick a stable order, and the identity assertions pin which ends
        up at position 0 and position 4.
        """
        # amount = 100, 95, 90, ... 55  (10 values, strictly descending)
        items = [_make_item(amount=f"{100 - i * 5}.00", category=f"cat_{i:02d}") for i in range(10)]
        result = _make_summary().aggregate(items)

        top = result["top_categories"]
        assert len(top) == 5  # slice length — catches [:4] or [:6]

        amounts = [entry[1]["amount"] for entry in top]
        assert amounts == sorted(amounts, reverse=True)  # strictly descending
        assert amounts == [
            Decimal("100.00"),
            Decimal("95.00"),
            Decimal("90.00"),
            Decimal("85.00"),
            Decimal("80.00"),
        ]  # exact values — catches sort-by-count with stable ordering

        names = [entry[0] for entry in top]
        assert names[0] == "cat_00"  # head — highest amount
        assert names[4] == "cat_04"  # tail of slice — 5th-highest (not 6th)


# ---------------------------------------------------------------------------
# Company breakdown
# ---------------------------------------------------------------------------


class TestCompanyBreakdown:
    def test_tracks_amount_count_category(self):
        items = [
            _make_item(amount="10.00", company="Safeway", category="groceries"),
            _make_item(amount="25.00", company="Safeway", category="groceries"),
        ]
        result = _make_summary().aggregate(items)
        safeway = result["by_company"]["Safeway"]
        assert safeway["amount"] == Decimal("35.00")
        assert safeway["count"] == 2
        assert safeway["category"] == "groceries"


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


class TestQueryMonth:
    @patch("src.finance.spending_summary.get_forwarded_to_addresses", return_value=["a@b.com"])
    def test_single_partition(self, _):
        mock_resource = MagicMock()
        mock_table = MagicMock(name="dynamodb_table")
        mock_resource.Table.return_value = mock_table
        mock_table.query.return_value = {"Items": [_make_item()]}

        summary = SpendingSummary(dyn_resource=mock_resource)
        result = summary.query_month("2026-01")

        assert len(result) == 1
        mock_table.query.assert_called_once()

    @patch("src.finance.spending_summary.get_forwarded_to_addresses", return_value=["a@b.com", "c@d.com"])
    def test_multiple_partitions(self, _):
        mock_resource = MagicMock()
        mock_table = MagicMock(name="dynamodb_table")
        mock_resource.Table.return_value = mock_table
        mock_table.query.return_value = {"Items": [_make_item()]}

        summary = SpendingSummary(dyn_resource=mock_resource)
        result = summary.query_month("2026-01")

        assert len(result) == 2
        assert mock_table.query.call_count == 2

    @patch("src.finance.spending_summary.get_forwarded_to_addresses", return_value=["a@b.com"])
    def test_pagination(self, _):
        mock_resource = MagicMock()
        mock_table = MagicMock(name="dynamodb_table")
        mock_resource.Table.return_value = mock_table
        mock_table.query.side_effect = [
            {"Items": [_make_item()], "LastEvaluatedKey": {"k": "v"}},
            {"Items": [_make_item()]},
        ]

        summary = SpendingSummary(dyn_resource=mock_resource)
        result = summary.query_month("2026-01")

        assert len(result) == 2
        assert mock_table.query.call_count == 2


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


class TestComparison:
    def _mock_summary_with_totals(self, current_total: float, previous_total: float) -> SpendingSummary:
        """Create a SpendingSummary that returns canned get_summary results."""
        summary = _make_summary()
        calls = iter(
            [
                {
                    "year_month": "2026-01",
                    "total_spending": Decimal(str(current_total)),
                    "spending_count": 5,
                    "deposit_total": Decimal(0),
                    "deposit_count": 0,
                    "by_category": {},
                    "by_company": {},
                    "top_categories": [],
                },
                {
                    "year_month": "2025-12",
                    "total_spending": Decimal(str(previous_total)),
                    "spending_count": 3,
                    "deposit_total": Decimal(0),
                    "deposit_count": 0,
                    "by_category": {},
                    "by_company": {},
                    "top_categories": [],
                },
            ]
        )
        summary.get_summary = MagicMock(side_effect=lambda ym: next(calls))
        return summary

    def test_positive_delta(self):
        summary = self._mock_summary_with_totals(1000, 800)
        result = summary.get_summary_with_comparison("2026-01")
        assert result["delta_amount"] == Decimal(200)
        assert result["delta_percent"] == pytest.approx(25.0)

    def test_negative_delta(self):
        summary = self._mock_summary_with_totals(500, 800)
        result = summary.get_summary_with_comparison("2026-01")
        assert result["delta_amount"] == Decimal(-300)
        assert result["delta_percent"] == pytest.approx(-37.5)

    def test_zero_previous_month(self):
        summary = self._mock_summary_with_totals(500, 0)
        result = summary.get_summary_with_comparison("2026-01")
        assert result["delta_percent"] == float("inf")

    def test_both_zero(self):
        summary = self._mock_summary_with_totals(0, 0)
        result = summary.get_summary_with_comparison("2026-01")
        assert result["delta_percent"] == 0.0


# ---------------------------------------------------------------------------
# SMS formatting
# ---------------------------------------------------------------------------


class TestSmsFormatting:
    def test_message_length(self):
        from src.finance.spending_summary import format_sms

        data = {
            "current": {
                "year_month": "2026-01",
                "total_spending": Decimal("2847.32"),
                "spending_count": 35,
                "deposit_total": Decimal("200.00"),
                "deposit_count": 3,
                "by_category": {},
                "by_company": {},
                "top_categories": [
                    ("groceries", {"amount": Decimal("623.45"), "count": 15}),
                    ("restaurant/dining", {"amount": Decimal("412.80"), "count": 8}),
                    ("gasoline", {"amount": Decimal("287.15"), "count": 4}),
                    ("rent", {"amount": Decimal("1200.00"), "count": 1}),
                    ("subscriptions", {"amount": Decimal("89.99"), "count": 3}),
                ],
            },
            "previous": {
                "year_month": "2025-12",
                "total_spending": Decimal("2507.32"),
            },
            "delta_amount": Decimal("340.00"),
            "delta_percent": 13.6,
        }
        message = format_sms(data)
        assert len(message) < 350
        assert "January 2026" in message
        assert "$2,847.32" in message
        assert "Groceries" in message

    def test_contains_top_categories(self):
        from src.finance.spending_summary import format_sms

        data = {
            "current": {
                "year_month": "2026-01",
                "total_spending": Decimal("500.00"),
                "spending_count": 10,
                "deposit_total": Decimal(0),
                "deposit_count": 0,
                "by_category": {},
                "by_company": {},
                "top_categories": [
                    ("groceries", {"amount": Decimal("300.00"), "count": 5}),
                    ("rent", {"amount": Decimal("200.00"), "count": 1}),
                ],
            },
            "previous": {
                "year_month": "2025-12",
                "total_spending": Decimal("400.00"),
            },
            "delta_amount": Decimal("100.00"),
            "delta_percent": 25.0,
        }
        message = format_sms(data)
        assert "Groceries" in message
        assert "Rent" in message
