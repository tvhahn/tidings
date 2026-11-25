"""History replay in ``dev/cli/retype_credit_alerts.py`` (issues #97 and #98 backfill)."""

from __future__ import annotations

from typing import Any

from dev.cli.retype_credit_alerts import plan_retypes
from src.finance.parser_base import TransactionParser


class _StubParser(TransactionParser):
    """Reads a body of the form ``<type> <amount> <company>``."""

    def parse_email(self, email_body_text: str, email_details: dict[str, Any]) -> dict[str, Any]:
        txn_type, amount, company = email_body_text.split(" ", 2)
        return {**email_details, "transaction_type": txn_type, "amount": float(amount), "company": company}


PARSERS = {"Bank": _StubParser()}


def _item(body: str, **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "ForwardedTo": "user@example.com",
        "DateFileName": "2026.10.02_08.15_a.eml",
        "Institution": "Bank",
        "Body": body,
        "Amount": 25.0,
        "Company": "[MERCHANT]",
        "TransactionType": "purchase",
    }
    item.update(overrides)
    return item


def test_refund_stored_as_purchase_is_retyped() -> None:
    planned, mismatches = plan_retypes([_item("refund 25.00 [MERCHANT]")], PARSERS)
    assert mismatches == []
    assert [(p.transaction_type, p.fields, p.ignore) for p in planned] == [
        ("refund", {"transaction_type": "refund"}, False)
    ]


def test_card_payment_stored_as_deposit_is_retyped_and_ignored() -> None:
    planned, _ = plan_retypes([_item("card-payment 25.00 Payment", TransactionType="deposit")], PARSERS)
    assert [(p.transaction_type, p.ignore) for p in planned] == [("card-payment", True)]


def test_untyped_row_gains_amount_and_company() -> None:
    item = _item("refund 25.00 [MERCHANT]", TransactionType=None, Amount=None, Company=None)
    planned, _ = plan_retypes([item], PARSERS)
    assert [p.fields for p in planned] == [{"transaction_type": "refund", "amount": 25.0, "company": "[MERCHANT]"}]


def test_amount_mismatch_is_reported_not_written() -> None:
    planned, mismatches = plan_retypes([_item("refund 30.00 [MERCHANT]")], PARSERS)
    assert planned == []
    assert [m.parsed_amount for m in mismatches] == [30.0]


def test_rows_left_alone() -> None:
    items = [
        _item("refund 25.00 [MERCHANT]", TransactionType="refund"),  # already right
        _item("purchase 25.00 [MERCHANT]"),  # parser still says purchase
        _item("refund 25.00 [MERCHANT]", DeletedAt="2026-10-03"),
        _item("refund 25.00 [MERCHANT]", StatementSource="s3://statement.pdf"),
        _item("refund 25.00 [MERCHANT]", Institution="Unknown Bank"),
        _item("", Body=None),
    ]
    assert plan_retypes(items, PARSERS) == ([], [])
