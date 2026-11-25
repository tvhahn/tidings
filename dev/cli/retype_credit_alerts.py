"""Re-type stored credit and card-payment alerts (issues #97 and #98 backfill).

Before the bank parsers knew the credit and payment-received alerts, those
emails went to the AI extraction fallback, which stored refunds as purchases
and card payments as deposits or purchases. Older copies, from before the
fallback existed, were stored with no transaction type at all.

This replays today's deterministic parsers over every stored alert body. When
a parser now reads an alert as a ``refund`` or ``card-payment`` and the stored
row says otherwise, the row is re-typed. A card payment is also set Ignored,
the default for new ones. Nothing else changes: category, comment and history
stay as they are. Rows whose parsed amount disagrees with the stored amount are
reported and left alone.

Run ``dev/cli/mark_duplicate_alerts.py`` afterwards so per-cardholder copies of
one card payment are marked as repeats of each other.

Dry run by default. Pass ``--apply`` to write. Safe to rerun: a row already
carrying the parsed type is skipped.

Usage:
    uv run dev/cli/retype_credit_alerts.py
    uv run dev/cli/retype_credit_alerts.py --apply
"""

import argparse
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.finance.email_pipeline import build_parsers
from src.finance.parser_base import TransactionParser
from src.finance.storage import create_transactions_db
from src.finance.transaction_types import REFUND_TYPES, TRANSFER_TYPES

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

_RETYPED = REFUND_TYPES | TRANSFER_TYPES


@dataclass(frozen=True)
class Retype:
    """One stored row and the fields the current parser gives it."""

    item: Mapping[str, Any]
    transaction_type: str
    fields: dict[str, Any]
    ignore: bool


@dataclass(frozen=True)
class Mismatch:
    """A row the parser reads as a credit or payment, but for another amount."""

    item: Mapping[str, Any]
    parsed_amount: float


def plan_retypes(
    items: list[Mapping[str, Any]], parsers: Mapping[str, TransactionParser]
) -> tuple[list[Retype], list[Mismatch]]:
    """Decide which stored alerts to re-type. Pure: reads nothing, writes nothing."""
    planned: list[Retype] = []
    mismatches: list[Mismatch] = []
    for item in items:
        if item.get("DeletedAt") or item.get("StatementSource"):
            continue
        body = item.get("Body")
        parser = parsers.get(str(item.get("Institution") or ""))
        if not body or parser is None:
            continue
        parsed = parser.parse_email(str(body), {})
        new_type = parsed.get("transaction_type")
        if new_type not in _RETYPED or item.get("TransactionType") == new_type:
            continue
        parsed_amount = parsed.get("amount")
        stored_amount = item.get("Amount")
        if parsed_amount is None:
            continue
        if stored_amount is not None and round(float(stored_amount), 2) != round(float(parsed_amount), 2):
            mismatches.append(Mismatch(item=item, parsed_amount=float(parsed_amount)))
            continue
        fields: dict[str, Any] = {"transaction_type": new_type}
        # Untyped rows from before the AI fallback may also lack these.
        if stored_amount is None:
            fields["amount"] = float(parsed_amount)
        if not item.get("Company") and parsed.get("company"):
            fields["company"] = parsed["company"]
        planned.append(
            Retype(
                item=item,
                transaction_type=str(new_type),
                fields=fields,
                ignore=new_type in TRANSFER_TYPES and not item.get("Ignored"),
            )
        )
    return planned, mismatches


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write the new types (default: dry run)")
    args = parser.parse_args()

    db = create_transactions_db()
    items = [dict(item) for item in db.scan_all_transactions()]
    planned, mismatches = plan_retypes(items, build_parsers())

    for retype in planned:
        item = retype.item
        old = item.get("TransactionType") or "(none)"
        note = "  and ignore" if retype.ignore else ""
        print(
            f"{str(item['DateFileName'])[:16]}  {item.get('Institution') or '-':<12} "
            f"{item.get('Company') or '-':<32.32} {item.get('Amount') or '':>10}  "
            f"{old:>12} -> {retype.transaction_type}{note}"
        )
    for mismatch in mismatches:
        item = mismatch.item
        print(
            f"{str(item['DateFileName'])[:16]}  skipped: stored amount {item.get('Amount')} "
            f"but the alert says {mismatch.parsed_amount:.2f}"
        )
    print(f"\n{len(planned)} row(s) to re-type; {len(mismatches)} skipped for an amount mismatch.")

    if not args.apply:
        print("Dry run — nothing written. Rerun with --apply to re-type them.")
        return
    for retype in planned:
        forwarded_to, date_file_name = str(retype.item["ForwardedTo"]), str(retype.item["DateFileName"])
        db.update_fields(forwarded_to, date_file_name, retype.fields)
        if retype.ignore:
            db.set_ignored(forwarded_to, date_file_name, True)
    print(f"Re-typed {len(planned)} row(s). Now run dev/cli/mark_duplicate_alerts.py for cardholder copies.")


if __name__ == "__main__":
    main()
