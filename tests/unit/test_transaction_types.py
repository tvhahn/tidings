"""How each transaction type moves the month's totals (issues #97 and #98)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, get_args

import pytest

from src.api.models.ingestion import TransactionType
from src.finance.spending_aggregator import aggregate
from src.finance.transaction_types import ALL_TRANSACTION_TYPES, signed_spending
from tests.factories import make_transaction_item


def _item(txn_type: str, amount: str, **overrides: Any) -> dict[str, Any]:
    return make_transaction_item(TransactionType=txn_type, Amount=Decimal(amount), **overrides)


def test_api_accepts_exactly_the_known_types() -> None:
    assert get_args(TransactionType) == ALL_TRANSACTION_TYPES


@pytest.mark.parametrize(
    ("txn_type", "expected"),
    [
        ("purchase", 20.0),
        ("withdrawal", 20.0),
        ("preauth", 20.0),
        ("e-transfer", 20.0),
        ("refund", -20.0),
        ("deposit", None),
        ("card-payment", None),
        (None, None),
    ],
)
def test_signed_spending(txn_type: str | None, expected: float | None) -> None:
    assert signed_spending({"TransactionType": txn_type, "Amount": Decimal("20.00")}) == expected


def test_signed_spending_without_amount_is_none() -> None:
    assert signed_spending({"TransactionType": "refund", "Amount": None}) is None


class TestAggregate:
    def test_purchase_and_its_refund_net_to_zero(self) -> None:
        result = aggregate([_item("purchase", "64.99"), _item("refund", "64.99")])
        assert result["total_spending"] == Decimal("0.00")
        assert result["by_category"]["groceries"]["amount"] == Decimal("0.00")
        assert result["by_company"]["Test Store"]["amount"] == Decimal("0.00")
        assert result["spending_count"] == 1

    def test_refund_is_not_income(self) -> None:
        result = aggregate([_item("refund", "10.00")])
        assert result["deposit_total"] == Decimal(0)
        assert result["deposit_count"] == 0
        assert result["total_spending"] == Decimal("-10.00")

    def test_partial_refund_reduces_its_category_only(self) -> None:
        result = aggregate(
            [
                _item("purchase", "100.00", Category="shopping"),
                _item("refund", "30.00", Category="shopping"),
                _item("purchase", "50.00", Category="groceries", Company="Grocer"),
            ]
        )
        assert result["total_spending"] == Decimal("120.00")
        assert result["by_category"]["shopping"]["amount"] == Decimal("70.00")
        assert result["by_category"]["groceries"]["amount"] == Decimal("50.00")

    def test_card_payment_is_neither_spending_nor_income(self) -> None:
        result = aggregate([_item("purchase", "40.00"), _item("card-payment", "500.00", Company="Payment")])
        assert result["total_spending"] == Decimal("40.00")
        assert result["deposit_total"] == Decimal(0)
        assert "Payment" not in result["by_company"]

    def test_ignored_refund_does_not_count(self) -> None:
        result = aggregate([_item("purchase", "40.00"), _item("refund", "40.00", Ignored=True)])
        assert result["total_spending"] == Decimal("40.00")
