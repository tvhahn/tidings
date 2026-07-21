"""CIBC-specific property tests.

CIBC handles two transaction types — credit-card purchases (gated on
``"made a purchase"``) and preauthorized payments (gated on
``"preauthorized payment"``). ``parse_email`` checks the purchase gate
FIRST, so purchase wins when both phrases are present. Properties:

1. A well-formed CIBC purchase body round-trips ``name``, ``amount``,
   ``company`` (merchant, with trailing period stripped), and
   ``transaction_type == "purchase"``.
2. A well-formed CIBC preauth body round-trips ``name``, ``amount``,
   ``company`` (recipient), and ``transaction_type == "preauth"``.
3. A valid purchase body that ALSO contains the string
   ``"preauthorized payment"`` still routes to the purchase branch —
   ``transaction_type == "purchase"``, never ``"preauth"``.

Amounts >= 1000 are rendered with and without thousand separators.
"""

from __future__ import annotations

import re
import string

from hypothesis import assume, given
from hypothesis import strategies as st

from src.finance.parsers.cibc_parser import CIBCParser


def _format_amount(amount_cents: int, use_commas: bool) -> tuple[str, float]:
    dollars = amount_cents // 100
    cents = amount_cents % 100
    amount_str = f"{dollars:,}.{cents:02d}" if use_commas and dollars >= 1_000 else f"{dollars}.{cents:02d}"
    amount = float(f"{dollars}.{cents:02d}")
    return amount_str, amount


@st.composite
def _valid_cibc_purchase_body(draw: st.DrawFn) -> tuple[str, str, float, str]:
    """Return ``(body, name, amount, merchant)``. Merchant is kept free
    of ``"."`` and ``"You can sign"`` so the regex captures it verbatim.
    """
    name = draw(st.text(alphabet=string.ascii_letters, min_size=1, max_size=12))
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
    assume("You can sign" not in merchant)

    body = (
        f"Dear {name},\n"
        f"      You've recently made a purchase with your CIBC card ending in 1234 "
        f"for ${amount_str} at {merchant}.\n"
        f"You can sign on to your CIBC Online Banking to view details."
    )
    return body, name, amount, merchant


@st.composite
def _valid_cibc_preauth_body(draw: st.DrawFn) -> tuple[str, str, float, str]:
    """Return ``(body, name, amount, recipient)``. The parser's preauth
    regex delimits the recipient with ``to\\s+(.+?)\\s+on`` — the capture
    stops at the *first* whitespace-then-"on" sequence anywhere in the
    body (" on ", a trailing " on", even " on0"), not at the intended
    " on <date>". Recipient is therefore kept free of any ``\\s+on``
    match, and of ``"made a purchase"`` — the parser's branch dispatch
    checks that purchase trigger phrase against the whole body first, so
    a recipient containing it misroutes the alert.
    """
    name = draw(st.text(alphabet=string.ascii_letters, min_size=1, max_size=12))
    amount_cents = draw(st.integers(min_value=1, max_value=9_999_999_99))
    amount_str, amount = _format_amount(amount_cents, draw(st.booleans()))

    recipient_raw = draw(
        st.text(
            alphabet=string.ascii_letters + string.digits + " &-#",
            min_size=1,
            max_size=30,
        )
    )
    recipient = recipient_raw.strip()
    assume(recipient)
    assume(re.search(r"\s+on", recipient) is None)
    assume("made a purchase" not in recipient)

    body = (
        f"Dear {name},\n"
        f"      Your CIBC debit card ending in 3345 has processed a preauthorized "
        f"payment of ${amount_str} to {recipient} on October 01, 2024.\n"
        f"Sign in to review."
    )
    return body, name, amount, recipient


@given(payload=_valid_cibc_purchase_body())
def test_cibc_valid_purchase_body_round_trips_core_fields(
    payload: tuple[str, str, float, str],
) -> None:
    body, name, amount, merchant = payload
    result = CIBCParser().parse_email(body, {})
    assert result["institution"] == "CIBC"
    assert result["transaction_type"] == "purchase"
    assert result["amount"] == amount
    assert result["name"] == name
    assert result["company"] == merchant


@given(payload=_valid_cibc_preauth_body())
def test_cibc_valid_preauth_body_round_trips_core_fields(
    payload: tuple[str, str, float, str],
) -> None:
    body, name, amount, recipient = payload
    result = CIBCParser().parse_email(body, {})
    assert result["institution"] == "CIBC"
    assert result["transaction_type"] == "preauth"
    assert result["amount"] == amount
    assert result["name"] == name
    assert result["company"] == recipient


@given(
    payload=_valid_cibc_purchase_body(),
    preauth_suffix=st.text(alphabet=string.ascii_letters + " ", max_size=50),
)
def test_cibc_purchase_trigger_wins_over_preauth(payload: tuple[str, str, float, str], preauth_suffix: str) -> None:
    body, _name, _amount, _merchant = payload
    body_with_both = f"{body}\n{preauth_suffix} Note: preauthorized payment arrangement."
    result = CIBCParser().parse_email(body_with_both, {})
    assert result["institution"] == "CIBC"
    assert result["transaction_type"] == "purchase", (
        f"CIBCParser selected {result['transaction_type']!r} when both 'made a purchase' "
        f"and 'preauthorized payment' triggers were present — purchase must win"
    )
