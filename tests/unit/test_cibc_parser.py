import pytest

from src.finance.email_pipeline import parse_email_body
from src.finance.parsers.cibc_parser import CIBCParser
from tests.conftest import load_test_data, read_file

# Load email details from JSON files
email_details = load_test_data("cibc")


@pytest.fixture
def parser() -> CIBCParser:
    return CIBCParser()


@pytest.mark.parametrize(
    (
        "email_filepath",
        "expected_institution",
        "expected_name",
        "expected_amount",
        "expected_company",
        "expected_transaction_type",
    ),
    [
        (
            detail["email_filepath"],
            detail.get("institution"),
            detail.get("name"),
            detail.get("amount"),
            detail.get("company"),
            detail.get("transaction_type"),
        )
        for detail in email_details
    ],
    ids=[detail["filename"].removesuffix(".json") for detail in email_details],
)
def test_parse_email(
    parser: CIBCParser,
    email_filepath: str,
    expected_institution: str | None,
    expected_name: str | None,
    expected_amount: float | None,
    expected_company: str | None,
    expected_transaction_type: str | None,
) -> None:
    email_body = read_file(email_filepath)

    # Use parse_email_body to check for the correct institution
    parsed_result = parse_email_body(email_body, {})
    assert parsed_result.get("institution") == expected_institution, (
        f"Expected institution {expected_institution}, but got {parsed_result.get('institution')}"
    )

    if expected_transaction_type == "purchase":
        result = parser.parse_purchase(email_body)
    elif expected_transaction_type == "preauth":
        result = parser.parse_preauth_payment(email_body)
    else:
        result = {}

    assert result is not None
    assert result.get("name") == expected_name
    assert result.get("amount") == expected_amount
    assert result.get("company") == expected_company
    assert result.get("transaction_type") == expected_transaction_type


def test_json_files_have_required_fields() -> None:
    required_fields = ["institution", "email_filepath"]
    for detail in email_details:
        for field in required_fields:
            assert field in detail, f"Missing required field '{field}' in {detail.get('filename', 'unknown file')}"
