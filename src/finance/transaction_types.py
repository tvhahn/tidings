"""Transaction types and how each one moves the month's totals.

Every stored transaction carries a positive ``Amount``; its ``TransactionType``
says which way that amount moves money:

* **Spending** (``SPENDING_TYPES``) adds to spending.
* **Refund** (``REFUND_TYPES``) is money a merchant gave back on a card. It
  reduces spending in its category and merchant, so a purchase and its refund
  net to zero. It is not income.
* **Deposit** (``DEPOSIT_TYPES``) is money coming in. It counts as income.
* **Card payment** (``TRANSFER_TYPES``) pays down a card from another account.
  The purchases on the card already count as spending, so the payment counts
  as neither spending nor income.

This module is the single source of truth for those sets. Code that sums
spending goes through :func:`signed_spending` so refunds are netted the same way
everywhere; code that looks for individual purchases (receipt matching,
recurring charges, tax lines) keeps testing ``SPENDING_TYPES`` membership.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "ALL_TRANSACTION_TYPES",
    "CARD_PAYMENT",
    "DEPOSIT_TYPES",
    "REFUND",
    "REFUND_TYPES",
    "SPENDING_TYPES",
    "TRANSFER_TYPES",
    "signed_spending",
]

REFUND: Final = "refund"
CARD_PAYMENT: Final = "card-payment"

SPENDING_TYPES: Final = frozenset({"purchase", "withdrawal", "preauth", "e-transfer"})
REFUND_TYPES: Final = frozenset({REFUND})
DEPOSIT_TYPES: Final = frozenset({"deposit"})
TRANSFER_TYPES: Final = frozenset({CARD_PAYMENT})

# Ordered for prompts, enums and pickers: the common types first.
ALL_TRANSACTION_TYPES: Final = ("purchase", "withdrawal", "preauth", "e-transfer", "deposit", REFUND, CARD_PAYMENT)


def signed_spending(item: Mapping[str, Any]) -> float | None:
    """How much a PascalCase transaction item adds to spending.

    The positive amount for a spending type, the negated amount for a refund,
    and ``None`` for anything that is not spending (deposits, card payments,
    untyped or amount-less rows). Deleted and Ignored rows are the caller's
    concern.
    """
    amount = item.get("Amount")
    if amount is None:
        return None
    txn_type = item.get("TransactionType")
    if txn_type in SPENDING_TYPES:
        return float(amount)
    if txn_type in REFUND_TYPES:
        return -float(amount)
    return None
