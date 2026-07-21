"""Negative tests for all parsers — degenerate input must not hallucinate fields.

Previous version only checked that the parser didn't raise and that
``amount`` stayed None. That gave a false sense of coverage: an AI that
hallucinated a ``company`` name, a ``transaction_type``, or a card-holder
``name`` on empty or garbled input would pass silently.

This version asserts every transaction-specific field (``amount``,
``company``, ``name``, ``transaction_type``) stays None/empty for every
parser on both empty and garbled input. The only legitimate key on a
degenerate parse is ``institution`` (plus whatever email_details
supplied — the test passes an empty dict so nothing leaks in).
"""

from typing import Any

import pytest

from src.finance.parser_base import TransactionParser
from src.finance.parsers.cibc_parser import CIBCParser
from src.finance.parsers.mbna_parser import MBNAParser
from src.finance.parsers.pc_financial_parser import PCFinancialParser
from src.finance.parsers.rbc_parser import RBCParser
from src.finance.parsers.simplii_parser import SimpliiParser

GARBLED_TEXT = "xyzzy 42 random gibberish <html>broken</html> $$$"
EMPTY_DETAILS: dict[str, Any] = {}

PARSERS = [
    (RBCParser, "RBC"),
    (CIBCParser, "CIBC"),
    (MBNAParser, "MBNA"),
    (SimpliiParser, "Simplii"),
    (PCFinancialParser, "PC Financial"),
]

# Transaction-specific fields that must NEVER be populated on degenerate input.
# A parser that filled any of these with a non-None / non-empty value has
# hallucinated — the slop pattern this suite is designed to catch.
HALLUCINATION_FIELDS = ("amount", "company", "name", "transaction_type")


def _assert_no_hallucinations(result: dict[str, Any], parser_name: str, input_kind: str) -> None:
    for field in HALLUCINATION_FIELDS:
        value = result.get(field)
        assert value in (None, ""), f"{parser_name} hallucinated {field}={value!r} on {input_kind} input"


@pytest.mark.parametrize(("parser_cls", "institution"), PARSERS, ids=[p[1] for p in PARSERS])
class TestParserHallucination:
    def test_empty_body_hallucinates_no_fields(self, parser_cls: type[TransactionParser], institution: str) -> None:
        result = parser_cls().parse_email("", EMPTY_DETAILS.copy())
        assert result["institution"] == institution
        _assert_no_hallucinations(result, parser_cls.__name__, "empty")

    def test_garbled_body_hallucinates_no_fields(self, parser_cls: type[TransactionParser], institution: str) -> None:
        result = parser_cls().parse_email(GARBLED_TEXT, EMPTY_DETAILS.copy())
        assert result["institution"] == institution
        _assert_no_hallucinations(result, parser_cls.__name__, "garbled")
