"""Integration test: full email parsing + OpenAI categorization (no DynamoDB)."""

import os

import pytest

from src.finance.ai_client import resolve_openai_categorization_settings
from src.finance.config_loader import get_categories
from src.finance.email_pipeline import parse_email_body
from src.finance.openai_client import OpenAIClient
from tests.conftest import load_test_data, read_file

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not OPENAI_API_KEY, reason="OPENAI_API_KEY not set"),
]

# Hand-picked fixtures that have both amount and company (needed for categorization).
# Covers: RBC e-transfer, CIBC purchase, MBNA purchase
SELECTED_FIXTURES = [
    ("rbc", "2024.08.27_14.05_rbc606fff707_rbc_e-transfer"),
    ("cibc", "edge_case_large_amount_cibc_purchase"),
    ("mbna", "2024.10.15_14.30_xyz789ghi012_mbna_purchase"),
]


@pytest.fixture(scope="module")
def openai_client() -> OpenAIClient:
    """Live client built exactly as production builds it.

    Both the model and the reasoning effort come from the shared resolver, so
    this test exercises whatever the app actually ships rather than a literal
    that silently rots when the default moves.
    """
    model, reasoning_effort = resolve_openai_categorization_settings(None, None)
    return OpenAIClient(model=model, api_key=OPENAI_API_KEY, reasoning_effort=reasoning_effort)


@pytest.mark.parametrize(("institution", "fixture_stem"), SELECTED_FIXTURES)
def test_categorization_returns_valid_category(
    openai_client: OpenAIClient, institution: str, fixture_stem: str
) -> None:
    """Parse a test email end-to-end and verify OpenAI returns a valid category."""
    entries = load_test_data(institution)
    entry = next(e for e in entries if fixture_stem in e.get("email_filepath", ""))

    email_body = read_file(entry["email_filepath"])
    result = parse_email_body(email_body, {}, api_client=openai_client)

    # Parser fields still correct
    assert result["institution"] == entry["institution"]
    assert result["amount"] == entry["amount"]

    # Categorization happened and returned a valid category
    assert "category" in result, f"No 'category' key in result: {result}"
    valid_categories = [c.lower() for c in get_categories()]
    assert result["category"].lower() in valid_categories, f"Category '{result['category']}' not in valid categories"
