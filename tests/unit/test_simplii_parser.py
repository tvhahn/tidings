import pytest

from src.finance.email_pipeline import parse_email_body
from src.finance.parsers.etransfer_parser import parse_e_transfer
from src.finance.parsers.simplii_parser import SimpliiParser
from tests.conftest import load_test_data, read_file

# Load email details from JSON files
email_details = load_test_data("simplii")


@pytest.fixture
def parser() -> SimpliiParser:
    return SimpliiParser()


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
        if "email_filepath" in detail
    ],
    ids=[detail["filename"].removesuffix(".json") for detail in email_details if "email_filepath" in detail],
)
def test_parse_email(
    parser: SimpliiParser,
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

    if expected_transaction_type == "e-transfer":
        result = parse_e_transfer(email_body)
    else:
        result = {}

    assert result.get("name") == expected_name
    assert result.get("amount") == expected_amount
    assert result.get("company") == expected_company
    assert result.get("transaction_type") == expected_transaction_type


def test_json_files_have_required_fields() -> None:
    required_fields = ["institution", "email_filepath"]
    email_fixtures = [d for d in email_details if "email_filepath" in d]
    for detail in email_fixtures:
        for field in required_fields:
            assert field in detail, f"Missing required field '{field}' in {detail.get('filename', 'unknown file')}"
