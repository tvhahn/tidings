"""Unit tests for src/finance/parsers/etransfer_parser.parse_e_transfer.

`parse_e_transfer` runs five independent regexes over the raw email body and
assembles a transaction dict::

    {"name", "amount", "company", "transaction_type"}

- `name`     — first token of the "Hi <NAME>," greeting, capitalized; None if absent
- `amount`   — `parse_amount` of the "$<n> (CAD)" capture; None if absent
- `company`  — " | "-joined concatenation of recipient, message, reference number
               (only the parts that matched, in that fixed order)
- `transaction_type` — always the literal "e-transfer"

These tests construct minimal inline bodies (no real bank data) and pin the
function's *actual current behavior*, including how missing regex matches
collapse to None / empty string.
"""

import pytest

from src.finance.parsers.etransfer_parser import parse_e_transfer

# A complete body that exercises every regex branch. The recipient pattern is
# `sent to (.*?) has been`, the message pattern reads up to the next blank line,
# and the reference pattern grabs the trailing word-token.
FULL_BODY = (
    "Hi JOHN DOE,\n"
    "\n"
    "Your money transfer sent to Jane Smith has been deposited.\n"
    "\n"
    "The amount of $1,234.56 (CAD) was transferred to your account.\n"
    "\n"
    "Message:\n"
    "Thanks for lunch\n"
    "\n"
    "Reference Number: ABC123XYZ\n"
    "\n"
    "This email was sent to you by Interac Corp.\n"
)


def test_parse_e_transfer_full_body():
    result = parse_e_transfer(FULL_BODY)

    # Greeting -> first token, capitalized.
    assert result["name"] == "John"
    # "$1,234.56 (CAD)" -> commas stripped, parsed to float.
    assert result["amount"] == pytest.approx(1234.56)
    # company_info is recipient | message | reference, in that fixed order.
    assert result["company"] == "Jane Smith | Thanks for lunch | ABC123XYZ"
    assert result["transaction_type"] == "e-transfer"


def test_parse_e_transfer_return_shape():
    # The dict always has exactly these four keys, regardless of matches.
    result = parse_e_transfer(FULL_BODY)
    assert set(result.keys()) == {"name", "amount", "company", "transaction_type"}


def test_parse_e_transfer_first_token_capitalized():
    # `capitalize()` upper-cases the first letter and lower-cases the rest of the
    # first whitespace-delimited token only: "MCINTYRE NELSON" -> "Mcintyre".
    body = "Hi MCINTYRE NELSON,\n\nsent to Bob has been deposited.\n"
    result = parse_e_transfer(body)
    assert result["name"] == "Mcintyre"


def test_parse_e_transfer_missing_name():
    # No "Hi <name>," greeting -> name is None, other fields still parse.
    body = (
        "Your transfer sent to Jane Smith has been deposited.\n"
        "\n"
        "The amount of $15.00 (CAD).\n"
        "\n"
        "Reference Number: REF001\n"
        "\n"
    )
    result = parse_e_transfer(body)
    assert result["name"] is None
    assert result["amount"] == pytest.approx(15.00)
    assert result["company"] == "Jane Smith | REF001"


def test_parse_e_transfer_missing_amount():
    # No "$<n> (CAD)" pattern -> amount_match is None -> parse_amount(None) -> None.
    body = "Hi SAM LEE,\n\nsent to Jane Smith has been deposited.\n\nReference Number: REF002\n\n"
    result = parse_e_transfer(body)
    assert result["name"] == "Sam"
    assert result["amount"] is None
    assert result["company"] == "Jane Smith | REF002"


def test_parse_e_transfer_missing_reference():
    # No "Reference Number:" -> reference omitted from company_info entirely.
    body = (
        "Hi SAM LEE,\n"
        "\n"
        "sent to Jane Smith has been deposited.\n"
        "\n"
        "The amount of $20.00 (CAD).\n"
        "\n"
        "Message:\n"
        "groceries\n"
        "\n"
    )
    result = parse_e_transfer(body)
    assert result["amount"] == pytest.approx(20.00)
    # recipient | message, no reference token appended.
    assert result["company"] == "Jane Smith | groceries"


def test_parse_e_transfer_malformed_amount_without_cad():
    # An amount that is missing the "(CAD)" suffix does NOT satisfy the regex,
    # so it is treated as absent and collapses to None.
    body = (
        "Hi SAM LEE,\n"
        "\n"
        "sent to Jane Smith has been deposited.\n"
        "\n"
        "The amount of $20.00 was transferred.\n"
        "\n"
        "Reference Number: REF003\n"
        "\n"
    )
    result = parse_e_transfer(body)
    assert result["amount"] is None
    # Name/recipient/reference still parse normally.
    assert result["name"] == "Sam"
    assert result["company"] == "Jane Smith | REF003"


def test_parse_e_transfer_empty_body():
    # Nothing matches: name/amount None, company empty string, type still set.
    result = parse_e_transfer("")
    assert result == {
        "name": None,
        "amount": None,
        "company": "",
        "transaction_type": "e-transfer",
    }


def test_parse_e_transfer_no_matches_company_is_empty_string():
    # A non-empty body with no recognizable fields still yields an empty company
    # (the parts list is empty, so " | ".join([]) == "").
    result = parse_e_transfer("totally unrelated text with no fields\n")
    assert result["name"] is None
    assert result["amount"] is None
    assert result["company"] == ""
    assert result["transaction_type"] == "e-transfer"
