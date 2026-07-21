"""Unit tests for src/finance/parser_base.parse_amount.

parse_amount strips commas and delegates to float(). It returns None for
falsy input (None / empty string) and otherwise lets float() do the work —
meaning it relies on float()'s own whitespace handling and ValueError raising.
These tests pin the *actual current behavior*.
"""

import pytest

from src.finance.parser_base import parse_amount


@pytest.mark.parametrize(
    ("amount_str", "expected"),
    [
        # plain integers
        ("100", 100.0),
        ("0", 0.0),
        # decimals
        ("1234.56", 1234.56),
        ("42.00", 42.0),
        # comma-grouped
        ("1,234.56", 1234.56),
        ("1,000,000.00", 1000000.0),
        ("1,000", 1000.0),
        # leading/trailing whitespace (float() tolerates surrounding whitespace)
        ("  42.00  ", 42.0),
        ("\t1,234.56\n", 1234.56),
        # negative amounts pass straight through float()
        ("-50.00", -50.0),
    ],
)
def test_parse_amount_valid(amount_str, expected):
    assert parse_amount(amount_str) == pytest.approx(expected)


@pytest.mark.parametrize("falsy_input", [None, ""])
def test_parse_amount_falsy_returns_none(falsy_input):
    # `if not amount_str` short-circuits before float() is ever called.
    assert parse_amount(falsy_input) is None


@pytest.mark.parametrize(
    "bad_input",
    [
        "abc",  # non-numeric
        "   ",  # whitespace-only: non-empty so float() is called and raises
        "$42.00",  # currency symbol is NOT stripped (only commas are)
        "12.34.56",  # malformed decimal
        "1,234.56 CAD",  # trailing token
    ],
)
def test_parse_amount_invalid_raises_value_error(bad_input):
    with pytest.raises(ValueError, match="could not convert string to float"):
        parse_amount(bad_input)
