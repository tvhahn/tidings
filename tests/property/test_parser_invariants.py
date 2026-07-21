"""Shared invariants that must hold across every bank parser.

Parametrized over all five parsers via ``PARSERS``. Each invariant
exercises behavior that must hold regardless of bank-specific logic:

1. ``parse_email`` never raises on arbitrary text.
2. Result is always a dict with a non-empty ``institution`` string.
3. ``amount`` is always ``float`` or ``None`` — never ``int`` / ``Decimal`` / ``str``.
4. ``name``, ``company``, ``transaction_type`` are always ``str`` or ``None``.
5. Same input produces the same result (parsers are stateless / idempotent).
6. Pure noise that lacks any trigger phrase leaves every transaction field ``None``.
7. Wrapping a valid body with arbitrary whitespace does not change ``amount``
   or ``transaction_type``.
8. Unicode-heavy names in an e-Transfer body don't crash the parser or leak
   replacement / null bytes into extracted strings.
"""

from __future__ import annotations

import string
from typing import TYPE_CHECKING, Any

import pytest
from hypothesis import assume, example, given
from hypothesis import strategies as st

from src.finance.parsers.cibc_parser import CIBCParser
from src.finance.parsers.mbna_parser import MBNAParser
from src.finance.parsers.pc_financial_parser import PCFinancialParser
from src.finance.parsers.rbc_parser import RBCParser
from src.finance.parsers.simplii_parser import SimpliiParser

if TYPE_CHECKING:
    from src.finance.parser_base import TransactionParser

PARSERS: list[type[TransactionParser]] = [
    RBCParser,
    CIBCParser,
    MBNAParser,
    SimpliiParser,
    PCFinancialParser,
]
PARSER_IDS: list[str] = [cls.__name__ for cls in PARSERS]

TRANSACTION_FIELDS: tuple[str, ...] = ("amount", "name", "company", "transaction_type")


def test_parsers_list_matches_live_dispatch_table() -> None:
    """``PARSERS`` must equal the live email dispatch table's parser classes.

    The invariants below are parametrized over ``PARSERS``. A bank parser that
    gets registered in ``src.finance.email_pipeline.build_parsers`` but not
    added here would silently escape all eight property invariants — so this
    guards against that drift in both directions.
    """
    from src.finance.email_pipeline import build_parsers

    dispatch_classes = {type(parser) for parser in build_parsers().values()}
    assert dispatch_classes == set(PARSERS), (
        "PARSERS is out of sync with the live email dispatch table. "
        f"Only in dispatch table: {dispatch_classes - set(PARSERS)}; "
        f"only in PARSERS: {set(PARSERS) - dispatch_classes}"
    )


# Substrings that any parser's ``parse_email`` inspects to decide whether
# to extract a transaction. If a random input happens to contain one of
# these, it is no longer "pure noise" — the no-hallucination invariant
# ``assume()``s them away.
TRIGGER_SUBSTRINGS: tuple[str, ...] = (
    "purchase",
    "withdrawal",
    "deposited",
    "preauthorized",
    "Merchant:",
)


def _body_rbc(amount: str) -> str:
    return f"Your purchase of ${amount} towards TEST MERCHANT."


def _body_cibc(amount: str) -> str:
    return f"Dear John, you made a purchase of ${amount} at TEST MERCHANT. You can sign into CIBC Online Banking"


def _body_mbna(amount: str) -> str:
    return f"A purchase of ${amount} from TEST MERCHANT was made"


def _body_simplii(amount: str) -> str:
    return (
        f"Hi John,\nYour e-Transfer of ${amount} (CAD) sent to TEST has been "
        f"successfully deposited.\nReference Number: ABC123"
    )


def _body_pc(amount: str) -> str:
    return f"Hi John,\nA purchase of ${amount} was made on your PC ® Mastercard.\nMerchant: TEST MERCHANT\n"


# Per-parser factory that produces a body guaranteed to trigger the
# parser's extraction path, templated on a generated amount. Used by the
# whitespace-invariant property.
BODY_FACTORIES: dict[type[TransactionParser], Any] = {
    RBCParser: _body_rbc,
    CIBCParser: _body_cibc,
    MBNAParser: _body_mbna,
    SimpliiParser: _body_simplii,
    PCFinancialParser: _body_pc,
}


@pytest.mark.parametrize("parser_cls", PARSERS, ids=PARSER_IDS)
@given(text=st.text(max_size=10_000))
@example(text="")
def test_parser_never_raises_on_arbitrary_text(parser_cls: type[TransactionParser], text: str) -> None:
    result = parser_cls().parse_email(text, {})
    assert isinstance(result, dict)


@pytest.mark.parametrize("parser_cls", PARSERS, ids=PARSER_IDS)
@given(text=st.text(max_size=2_000))
def test_parser_returns_dict_with_institution(parser_cls: type[TransactionParser], text: str) -> None:
    result = parser_cls().parse_email(text, {})
    institution = result.get("institution")
    assert isinstance(institution, str)
    assert institution, f"{parser_cls.__name__} returned empty institution"


@pytest.mark.parametrize("parser_cls", PARSERS, ids=PARSER_IDS)
@given(text=st.text(max_size=2_000))
def test_parser_amount_is_float_or_none(parser_cls: type[TransactionParser], text: str) -> None:
    result = parser_cls().parse_email(text, {})
    amount = result.get("amount")
    # bool subclasses int in Python — guard against that leaking even
    # though no parser currently emits one.
    assert amount is None or (isinstance(amount, float) and not isinstance(amount, bool)), (
        f"{parser_cls.__name__} returned non-float amount: {amount!r} (type {type(amount).__name__})"
    )


@pytest.mark.parametrize("parser_cls", PARSERS, ids=PARSER_IDS)
@given(text=st.text(max_size=2_000))
def test_parser_string_fields_are_str_or_none(parser_cls: type[TransactionParser], text: str) -> None:
    result = parser_cls().parse_email(text, {})
    for field in ("name", "company", "transaction_type"):
        value = result.get(field)
        assert value is None or isinstance(value, str), (
            f"{parser_cls.__name__} returned non-str/non-None for {field}: {value!r}"
        )


@pytest.mark.parametrize("parser_cls", PARSERS, ids=PARSER_IDS)
@given(text=st.text(max_size=2_000))
def test_parser_idempotent(parser_cls: type[TransactionParser], text: str) -> None:
    parser = parser_cls()
    first = parser.parse_email(text, {})
    second = parser.parse_email(text, {})
    assert first == second


@pytest.mark.parametrize("parser_cls", PARSERS, ids=PARSER_IDS)
@given(
    text=st.text(
        alphabet=string.ascii_letters + " ",
        min_size=1,
        max_size=500,
    )
)
def test_parser_no_hallucination_on_pure_noise(parser_cls: type[TransactionParser], text: str) -> None:
    for trigger in TRIGGER_SUBSTRINGS:
        assume(trigger not in text)
    result = parser_cls().parse_email(text, {})
    for field in TRANSACTION_FIELDS:
        assert result.get(field) is None, (
            f"{parser_cls.__name__} hallucinated {field}={result.get(field)!r} on pure-noise input {text!r}"
        )


@pytest.mark.parametrize("parser_cls", PARSERS, ids=PARSER_IDS)
@given(
    amount_cents=st.integers(min_value=1, max_value=9_999_999),
    ws_before=st.text(alphabet=" \t\n\r", max_size=20),
    ws_after=st.text(alphabet=" \t\n\r", max_size=20),
)
def test_parser_whitespace_invariant(
    parser_cls: type[TransactionParser],
    amount_cents: int,
    ws_before: str,
    ws_after: str,
) -> None:
    amount_str = f"{amount_cents / 100:.2f}"
    body = BODY_FACTORIES[parser_cls](amount_str)
    base = parser_cls().parse_email(body, {})
    wrapped = parser_cls().parse_email(f"{ws_before}{body}{ws_after}", {})
    assert base.get("amount") == wrapped.get("amount"), (
        f"{parser_cls.__name__} amount changed under whitespace wrap: "
        f"{base.get('amount')!r} vs {wrapped.get('amount')!r}"
    )
    assert base.get("transaction_type") == wrapped.get("transaction_type"), (
        f"{parser_cls.__name__} transaction_type changed under whitespace wrap: "
        f"{base.get('transaction_type')!r} vs {wrapped.get('transaction_type')!r}"
    )


@pytest.mark.parametrize("parser_cls", PARSERS, ids=PARSER_IDS)
@given(
    name=st.text(
        alphabet=st.characters(min_codepoint=0x00C0, max_codepoint=0x017F),
        min_size=1,
        max_size=20,
    ),
)
def test_parser_unicode_safe_in_names(parser_cls: type[TransactionParser], name: str) -> None:
    body = (
        f"Hi {name},\nYour e-Transfer of $42.00 (CAD) sent to TEST has been "
        f"successfully deposited.\nReference Number: ABC123"
    )
    result = parser_cls().parse_email(body, {})
    extracted = result.get("name")
    assert extracted is None or isinstance(extracted, str)
    if isinstance(extracted, str):
        assert "�" not in extracted, f"{parser_cls.__name__} leaked replacement char into name={extracted!r}"
        assert "\x00" not in extracted, f"{parser_cls.__name__} leaked null byte into name={extracted!r}"
