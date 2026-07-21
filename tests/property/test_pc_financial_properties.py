"""PC Financial-specific property tests.

PC Financial only handles credit-card purchases. The parser guards the
extraction path with TWO substring checks: ``"purchase of $"`` AND
``"PC ® Mastercard"``. The brand marker makes the parser more
conservative than RBC / MBNA (which trigger on ``"purchase of"`` alone).
Properties exercise:

1. A well-formed PC Financial purchase body round-trips the cardholder
   ``name``, ``amount`` (rendered with or without thousand separators),
   and the ``merchant`` (``company``), with ``transaction_type == "purchase"``.
2. A body containing ``"purchase of $"`` but missing the ``"PC ® Mastercard"``
   brand marker returns institution-only — no transaction field is
   populated. Guards against the brand-check being relaxed accidentally.
3. (regression) Amounts >= 1000 rendered WITHOUT thousand separators
   parse in full. The old shared regex ``\\d{1,3}(?:,\\d{3})*|\\d+``
   preferred the comma-grouped branch and truncated ``"1000.00"`` to
   ``100.0``; ``AMOUNT_PATTERN`` in ``parser_base`` requires at least one
   comma group before taking that branch.
"""

from __future__ import annotations

import string

from hypothesis import assume, given
from hypothesis import strategies as st

from src.finance.parsers.pc_financial_parser import PCFinancialParser


@st.composite
def _valid_pc_body(draw: st.DrawFn) -> tuple[str, str, float, str]:
    """Return ``(body, name, amount, merchant)`` — inputs the parser must
    round-trip verbatim. Amounts >= 1000 are rendered with and without
    thousand separators.
    """
    name_raw = draw(st.text(alphabet=string.ascii_letters + " ", min_size=1, max_size=20))
    name = name_raw.strip()
    assume(name)

    amount_cents = draw(st.integers(min_value=1, max_value=9_999_999_99))
    use_commas = draw(st.booleans())
    dollars = amount_cents // 100
    cents = amount_cents % 100
    amount_str = f"{dollars:,}.{cents:02d}" if use_commas and dollars >= 1_000 else f"{dollars}.{cents:02d}"
    amount = float(f"{dollars}.{cents:02d}")

    merchant_raw = draw(
        st.text(
            alphabet=string.ascii_uppercase + string.digits + " @-#",
            min_size=1,
            max_size=30,
        )
    )
    merchant = merchant_raw.strip()
    assume(merchant)

    body = (
        f"Hi {name},\n\n"
        f"A purchase of ${amount_str} was made on your PC ® Mastercard ® card ending in 8804.\n\n"
        f"Merchant: {merchant}\n"
        f"Purchase amount: ${amount_str}\n"
    )
    return body, name, amount, merchant


@given(payload=_valid_pc_body())
def test_pc_financial_valid_body_round_trips_core_fields(
    payload: tuple[str, str, float, str],
) -> None:
    body, name, amount, merchant = payload
    result = PCFinancialParser().parse_email(body, {})
    assert result["institution"] == "PC Financial"
    assert result["transaction_type"] == "purchase"
    assert result["amount"] == amount
    assert result["name"] == name
    assert result["company"] == merchant


@given(
    name=st.text(alphabet=string.ascii_letters, min_size=1, max_size=10),
    amount_cents=st.integers(min_value=1, max_value=9_999_999),
    merchant=st.text(alphabet=string.ascii_uppercase, min_size=1, max_size=10),
)
def test_pc_financial_without_brand_marker_is_inert(name: str, amount_cents: int, merchant: str) -> None:
    amount_str = f"{amount_cents // 100}.{amount_cents % 100:02d}"
    body = f"Hi {name},\nA purchase of ${amount_str} was made on your card ending in 8804.\nMerchant: {merchant}\n"
    assume("PC ® Mastercard" not in body)
    result = PCFinancialParser().parse_email(body, {})
    assert result["institution"] == "PC Financial"
    for field in ("amount", "name", "company", "transaction_type"):
        assert result.get(field) is None, (
            f"PCFinancialParser hallucinated {field}={result.get(field)!r} without 'PC ® Mastercard' marker"
        )


@given(
    dollars=st.integers(min_value=1_000, max_value=999_999),
    cents=st.integers(min_value=0, max_value=99),
)
def test_pc_financial_amount_without_commas_parses_in_full(dollars: int, cents: int) -> None:
    """Regression: '$1000.00' used to truncate to 100.0 (comma-branch greed)."""
    amount_str = f"{dollars}.{cents:02d}"
    expected = float(amount_str)
    body = (
        f"Hi John,\n"
        f"A purchase of ${amount_str} was made on your PC ® Mastercard ® card ending in 8804.\n"
        f"Merchant: TEST\n"
    )
    result = PCFinancialParser().parse_email(body, {})
    assert result["amount"] == expected
