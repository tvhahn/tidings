"""MBNA-specific property tests.

MBNA only handles credit-card purchases. The ``parse_email`` guard is a
single substring check (``"purchase of"``), then ``parse_purchase``
requires ``"A purchase of $<amount>"`` and ``"from <merchant> was made"``
to populate amount + company. Properties exercise:

1. A well-formed MBNA purchase body round-trips ``amount`` (rendered with
   and without thousand separators), ``company``, and
   ``transaction_type == "purchase"``.
2. A body that contains the ``"purchase of"`` trigger but lacks the
   specific ``"A purchase of $"`` prefix leaves ``amount`` as ``None`` —
   guards against accidental relaxation of the amount regex.
"""

from __future__ import annotations

import string

from hypothesis import assume, given
from hypothesis import strategies as st

from src.finance.parsers.mbna_parser import MBNAParser


@st.composite
def _valid_mbna_body(draw: st.DrawFn) -> tuple[str, float, str]:
    """Return ``(body, amount, merchant)`` — inputs the parser must
    round-trip. Amounts >= 1000 are rendered with and without thousand
    separators. No ``"card ending in"`` phrase is included so the
    config-driven name mapping stays out of scope.
    """
    amount_cents = draw(st.integers(min_value=1, max_value=9_999_999_99))
    use_commas = draw(st.booleans())
    dollars = amount_cents // 100
    cents = amount_cents % 100
    amount_str = f"{dollars:,}.{cents:02d}" if use_commas and dollars >= 1_000 else f"{dollars}.{cents:02d}"
    amount = float(f"{dollars}.{cents:02d}")

    merchant_raw = draw(
        st.text(
            alphabet=string.ascii_letters + string.digits + " &-.#",
            min_size=1,
            max_size=30,
        )
    )
    merchant = merchant_raw.strip()
    assume(merchant)
    assume("was made" not in merchant)

    body = f"MBNA Alert\n\nA purchase of ${amount_str} from {merchant} was made on your MBNA Mastercard on some date.\n"
    return body, amount, merchant


@given(payload=_valid_mbna_body())
def test_mbna_valid_body_round_trips_core_fields(
    payload: tuple[str, float, str],
) -> None:
    body, amount, merchant = payload
    result = MBNAParser().parse_email(body, {})
    assert result["institution"] == "MBNA"
    assert result["transaction_type"] == "purchase"
    assert result["amount"] == amount
    assert result["company"] == merchant


@given(
    amount_cents=st.integers(min_value=1, max_value=999_999),
    filler=st.text(alphabet=string.ascii_letters + " ", min_size=0, max_size=50),
)
def test_mbna_trigger_without_A_prefix_leaves_amount_none(amount_cents: int, filler: str) -> None:
    amount_str = f"{amount_cents // 100}.{amount_cents % 100:02d}"
    body = f"{filler} Your purchase of ${amount_str} is being reviewed."
    assume("purchase of" in body)
    assume("A purchase of" not in body)
    result = MBNAParser().parse_email(body, {})
    assert result["institution"] == "MBNA"
    assert result["amount"] is None, (
        f"MBNAParser hallucinated amount={result['amount']!r} from a 'purchase of $X.XX' body "
        f"lacking the required 'A purchase of' prefix"
    )
