"""Pure tier-ranked matcher: which bank transaction does this receipt explain?

Same reconciliation shape as the statement reconciler, scoped to a receipt. Given
a validated parse (merchant/date/total) and the candidate month(s)' raw
transaction items, rank the transactions a receipt could belong to. No storage
imports — the caller (the attachments router) hands in the items, aliases, and the
set of transactions that already carry a receipt.

Constants (L8) are **not tunable**. Day math is done on the ``DateFileName[:10]``
slice — the established convention — never by re-parsing ``Date``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.finance.merchant_normalizer import normalize_merchant
from src.finance.spending_aggregator import SPENDING_TYPES

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

# L8 — locked, not tunable.
RECEIPT_AMOUNT_TOL = 0.02
RECEIPT_DATE_WINDOW_DAYS = 3
RECEIPT_TIP_PCT = 0.20
MAX_CANDIDATES = 8


@dataclass(frozen=True)
class Candidate:
    """A ranked transaction a receipt might explain."""

    forwarded_to: str
    date_file_name: str
    tier: int  # 1 (exact) | 2 (amount+window) | 3 (tip window)
    day_distance: int
    amount_distance: float
    company: str
    amount: float
    date: str  # DateFileName[:10] normalized to YYYY-MM-DD
    category: str
    already_has_receipt: bool


def _txn_date(date_file_name: str) -> datetime | None:
    """Parse the ``DateFileName[:10]`` slice (``YYYY.MM.DD``) into a date."""
    slice_ = date_file_name[:10]
    try:
        return datetime.strptime(slice_, "%Y.%m.%d")  # noqa: DTZ007 — date-only value, used for day-distance comparison
    except ValueError:
        return None


def find_candidates(
    parse: dict[str, Any],
    items_by_month: Mapping[str, Sequence[Mapping[str, Any]]],
    aliases: Mapping[str, str],
    linked_keys: set[tuple[str, str]],
) -> list[Candidate]:
    """Rank the transactions a receipt could belong to (see module docstring).

    ``parse`` carries ``merchant``, ``date`` (YYYY-MM-DD) and ``total``.
    ``items_by_month`` maps ``YYYY-MM`` to that month's raw transaction items.
    ``aliases`` is the merchant alias map (applied to both sides). ``linked_keys``
    is the set of ``(forwarded_to, date_file_name)`` composites that already carry
    a receipt-kind attachment — these are demoted (never excluded), since multiple
    receipts per transaction are legal.
    """
    try:
        receipt_date = datetime.strptime(parse["date"], "%Y-%m-%d")  # noqa: DTZ007 — date-only value, used for day-distance comparison
    except (KeyError, ValueError, TypeError):
        return []
    try:
        total = float(parse["total"])
    except (KeyError, ValueError, TypeError):
        return []
    receipt_merchant = normalize_merchant(str(parse.get("merchant") or ""), aliases).lower()

    tip_ceiling = total * (1 + RECEIPT_TIP_PCT)
    candidates: list[Candidate] = []
    seen: set[tuple[str, str]] = set()

    for items in items_by_month.values():
        for item in items:
            if item.get("DeletedAt") or item.get("Ignored"):
                continue
            if item.get("TransactionType") not in SPENDING_TYPES:
                continue
            forwarded_to = item.get("ForwardedTo")
            date_file_name = item.get("DateFileName")
            if not forwarded_to or not date_file_name:
                continue
            key = (forwarded_to, date_file_name)
            if key in seen:
                continue
            txn_dt = _txn_date(date_file_name)
            if txn_dt is None:
                continue
            try:
                amount = float(item.get("Amount"))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue

            day_distance = abs((txn_dt - receipt_date).days)
            # Round to cents before comparing so float dust (e.g. 42.52 - 42.50)
            # doesn't push an at-tolerance amount out of the exact-match band.
            amount_distance = round(abs(amount - total), 2)
            within_amount = amount_distance <= RECEIPT_AMOUNT_TOL
            within_window = day_distance <= RECEIPT_DATE_WINDOW_DAYS
            merchant = normalize_merchant(str(item.get("Company") or ""), aliases).lower()

            tier: int | None = None
            if within_amount and day_distance == 0 and merchant and merchant == receipt_merchant:
                tier = 1
            elif within_amount and within_window:
                tier = 2
            elif within_window and (total - RECEIPT_AMOUNT_TOL) <= amount <= tip_ceiling:
                tier = 3
            if tier is None:
                continue

            seen.add(key)
            candidates.append(
                Candidate(
                    forwarded_to=forwarded_to,
                    date_file_name=date_file_name,
                    tier=tier,
                    day_distance=day_distance,
                    amount_distance=round(amount_distance, 2),
                    company=str(item.get("Company") or "Unknown"),
                    amount=amount,
                    date=txn_dt.strftime("%Y-%m-%d"),
                    category=str(item.get("Category") or "miscellaneous"),
                    already_has_receipt=key in linked_keys,
                )
            )

    # Sort: best tier first; at equal tier, transactions still lacking a receipt
    # come before ones already carrying one; then nearest day, then nearest amount.
    candidates.sort(key=lambda c: (c.tier, c.already_has_receipt, c.day_distance, c.amount_distance))
    return candidates[:MAX_CANDIDATES]
