"""RBC-specific property tests.

RBC is the largest parser — three transaction types routed by an
if / elif chain in ``parse_email``:

1. ``"purchase of"``        → credit-card purchase
2. ``"withdrawal of"``       → debit withdrawal
3. ``"e-Transfer"`` + ``"successfully deposited"`` → incoming e-Transfer

RBC additionally maps card-ending fragments to cardholder names via
``get_card_name_mappings()`` — an autouse monkeypatch empties this map
so tests stay independent of the user's personal config.

Properties:

1. Valid purchase body round-trips ``amount`` + ``company`` (merchant,
   via ``towards (.+?)\\.``), ``transaction_type == "purchase"``.
2. Valid withdrawal body round-trips ``amount``,
   ``transaction_type == "withdrawal"``, and leaves ``company`` + ``name`` None.
3. Valid e-Transfer body (including ``"successfully deposited"``)
   round-trips ``amount``, capitalized sender ``name``, and
   ``transaction_type == "e-transfer"``.
4. When multiple trigger phrases are present, the precedence is
   purchase > withdrawal > e-transfer (matches the if/elif order).

Amounts >= 1000 are rendered with and without thousand separators.
"""

from __future__ import annotations

import string
from typing import TYPE_CHECKING

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from src.finance.parsers.rbc_parser import RBCParser

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _empty_rbc_card_mappings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Replace the user's card-ending → cardholder mapping with an empty
    dict so random card numbers in generated bodies can't accidentally
    resolve to a configured name (or fail to, depending on the host).
    """
    monkeypatch.setattr(
        "src.finance.parsers.rbc_parser.get_card_name_mappings",
        lambda: {"RBC": {}},
    )
    return


def _format_amount(amount_cents: int, use_commas: bool) -> tuple[str, float]:
    dollars = amount_cents // 100
    cents = amount_cents % 100
    amount_str = f"{dollars:,}.{cents:02d}" if use_commas and dollars >= 1_000 else f"{dollars}.{cents:02d}"
    amount = float(f"{dollars}.{cents:02d}")
    return amount_str, amount


@st.composite
def _valid_rbc_purchase_body(draw: st.DrawFn) -> tuple[str, float, str]:
    """Return ``(body, amount, merchant)``. Merchant avoids ``"."`` so
    the ``towards (.+?)\\.`` non-greedy capture terminates at the
    intended trailing period.
    """
    amount_cents = draw(st.integers(min_value=1, max_value=9_999_999_99))
    amount_str, amount = _format_amount(amount_cents, draw(st.booleans()))

    merchant_raw = draw(
        st.text(
            alphabet=string.ascii_letters + string.digits + " &-#",
            min_size=1,
            max_size=30,
        )
    )
    merchant = merchant_raw.strip()
    assume(merchant)

    body = (
        f"Hello,\n\nAs requested, a purchase of ${amount_str} was made on your RBC "
        f"Royal Bank credit card account ending in 0000 towards {merchant}.\n"
        f"Thank you!\n"
    )
    return body, amount, merchant


@st.composite
def _valid_rbc_withdrawal_body(draw: st.DrawFn) -> tuple[str, float]:
    amount_cents = draw(st.integers(min_value=1, max_value=9_999_999_99))
    amount_str, amount = _format_amount(amount_cents, draw(st.booleans()))

    body = (
        f"Hello,\n\nA withdrawal of ${amount_str} was debited from your bank account "
        f"Daily Savings. The full details are below.\nThank you!\n"
    )
    return body, amount


@st.composite
def _valid_rbc_etransfer_body(draw: st.DrawFn) -> tuple[str, str, float]:
    first_name = draw(st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=12))
    amount_cents = draw(st.integers(min_value=1, max_value=9_999_999_99))
    dollars = amount_cents // 100
    cents = amount_cents % 100
    amount = float(f"{dollars}.{cents:02d}")
    amount_str = f"{dollars:,}.{cents:02d}" if dollars >= 1_000 else f"{dollars}.{cents:02d}"

    body = (
        f"Hi {first_name},\n\nThe ${amount_str} (CAD) you sent to RECIPIENT has been "
        f"successfully deposited.\n\nReference Number: ABC123XYZ\n\n"
        f"INTERAC e-Transfer service.\n"
    )
    return body, first_name, amount


@given(payload=_valid_rbc_purchase_body())
def test_rbc_valid_purchase_body_round_trips_core_fields(
    payload: tuple[str, float, str],
) -> None:
    body, amount, merchant = payload
    result = RBCParser().parse_email(body, {})
    assert result["institution"] == "RBC"
    assert result["transaction_type"] == "purchase"
    assert result["amount"] == amount
    assert result["company"] == merchant
    assert result["name"] is None


@given(payload=_valid_rbc_withdrawal_body())
def test_rbc_valid_withdrawal_body_round_trips_core_fields(
    payload: tuple[str, float],
) -> None:
    body, amount = payload
    result = RBCParser().parse_email(body, {})
    assert result["institution"] == "RBC"
    assert result["transaction_type"] == "withdrawal"
    assert result["amount"] == amount
    assert result["name"] is None
    assert result["company"] is None


@given(payload=_valid_rbc_etransfer_body())
def test_rbc_valid_etransfer_body_round_trips_core_fields(
    payload: tuple[str, str, float],
) -> None:
    body, first_name, amount = payload
    result = RBCParser().parse_email(body, {})
    assert result["institution"] == "RBC"
    assert result["transaction_type"] == "e-transfer"
    assert result["amount"] == amount
    assert result["name"] == first_name.capitalize()


@given(purchase_payload=_valid_rbc_purchase_body())
def test_rbc_purchase_wins_over_withdrawal_and_etransfer(
    purchase_payload: tuple[str, float, str],
) -> None:
    body, _amount, _merchant = purchase_payload
    body_with_all = (
        f"{body}\nAlso note: a withdrawal of $99.99 was made.\nAlso: your e-Transfer has been successfully deposited.\n"
    )
    result = RBCParser().parse_email(body_with_all, {})
    assert result["institution"] == "RBC"
    assert result["transaction_type"] == "purchase", (
        f"RBCParser selected {result['transaction_type']!r} — purchase must win when "
        f"'purchase of', 'withdrawal of', and e-Transfer triggers all appear"
    )
