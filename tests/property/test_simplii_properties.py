"""Simplii-specific property tests.

Simplii only handles incoming e-Transfers (delegates to
``etransfer_parser.parse_e_transfer``). Two trigger substrings guard the
extraction path: ``"e-Transfer"`` AND ``"successfully deposited"`` must
both be present. Properties exercise:

1. A well-formed Simplii e-Transfer body round-trips ``amount``, ``name``
   (capitalized first name), and ``transaction_type == "e-transfer"``.
   Amounts are generated with and without thousand-separator commas.
2. A body containing ``"e-Transfer"`` but missing ``"successfully deposited"``
   returns institution-only — no transaction field is populated. Guards
   against partial-trigger hallucination.
"""

from __future__ import annotations

import string

from hypothesis import assume, given
from hypothesis import strategies as st

from src.finance.parsers.simplii_parser import SimpliiParser


@st.composite
def _valid_simplii_body(draw: st.DrawFn) -> tuple[str, str, float, str]:
    """Return ``(body, expected_first_name_lowercase, expected_amount,
    expected_recipient)``. Recipient is a non-empty uppercase string with
    no internal trigger-phrase collisions.
    """
    first_name = draw(st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=12))
    amount_cents = draw(st.integers(min_value=1, max_value=9_999_999_99))
    dollars = amount_cents // 100
    cents = amount_cents % 100
    use_commas = draw(st.booleans())
    amount_str = f"{dollars:,}.{cents:02d}" if use_commas and dollars >= 1_000 else f"{dollars}.{cents:02d}"
    amount = float(f"{dollars}.{cents:02d}")
    recipient = draw(st.text(alphabet=string.ascii_uppercase + " ", min_size=1, max_size=20).map(str.strip))
    assume(recipient)
    assume("HAS BEEN" not in recipient)
    ref_num = draw(st.text(alphabet=string.ascii_letters + string.digits, min_size=4, max_size=12))
    body = (
        f"Hi {first_name},\n\n"
        f"The ${amount_str} (CAD) you sent to {recipient} has been successfully deposited.\n\n"
        f"Reference Number: {ref_num}\n\n"
        f"INTERAC e-Transfer service.\n"
    )
    return body, first_name, amount, recipient


@given(payload=_valid_simplii_body())
def test_simplii_valid_body_round_trips_core_fields(
    payload: tuple[str, str, float, str],
) -> None:
    body, first_name, amount, recipient = payload
    result = SimpliiParser().parse_email(body, {})
    assert result["institution"] == "Simplii"
    assert result["transaction_type"] == "e-transfer"
    assert result["amount"] == amount
    assert result["name"] == first_name.capitalize()
    company = result["company"]
    assert isinstance(company, str)
    assert recipient in company


@given(
    prefix=st.text(alphabet=string.ascii_letters + " \n", max_size=200),
    suffix=st.text(alphabet=string.ascii_letters + " \n", max_size=200),
)
def test_simplii_etransfer_without_deposited_trigger_is_inert(prefix: str, suffix: str) -> None:
    body = f"{prefix}\nINTERAC e-Transfer service in progress.\n{suffix}"
    assume("successfully deposited" not in body)
    result = SimpliiParser().parse_email(body, {})
    assert result["institution"] == "Simplii"
    for field in ("amount", "name", "company", "transaction_type"):
        assert result.get(field) is None, (
            f"SimpliiParser hallucinated {field}={result.get(field)!r} without 'successfully deposited' trigger"
        )
