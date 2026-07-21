"""Mocked unit tests for AI transaction extraction (extractor.py).

Mirrors the mock style of tests/unit/test_openai_categorization.py — a
SimpleNamespace completion carrying a single tool call. Covers the happy path,
the extraction-failure fallbacks (api error / empty completion / parse error /
no client → "ai_extraction_failed"), and the verbatim-validation matrix
(→ "ai_validation_failed").
"""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from src.finance.extractor import extract_transaction, validate_extraction

# ---------------------------------------------------------------------------
# Helpers to build mock completion objects (copied from the categorization tests)
# ---------------------------------------------------------------------------


def _make_completion(function_name: str, arguments_dict: dict[str, Any]) -> SimpleNamespace:
    """Build a mock completion with a single tool call."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    tool_calls=[
                        SimpleNamespace(
                            function=SimpleNamespace(
                                name=function_name,
                                arguments=json.dumps(arguments_dict),
                            )
                        )
                    ]
                )
            )
        ]
    )


def _make_empty_completion() -> SimpleNamespace:
    """Build a completion with no tool calls."""
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None))])


def _email(body: str, *, subject: str = "Transaction alert", institution: str | None = None) -> dict[str, Any]:
    details: dict[str, Any] = {"subject": subject, "body": body}
    if institution is not None:
        details["detected_institution"] = institution
    return details


# ---------------------------------------------------------------------------
# extract_transaction — happy path
# ---------------------------------------------------------------------------


class TestExtractTransactionHappyPath:
    def test_successful_extraction(self) -> None:
        client = MagicMock()
        client.chat.return_value = _make_completion(
            "extract_transaction",
            {"amount": "42.50", "company": "TEST MERCHANT", "transaction_type": "purchase"},
        )
        body = "Your purchase of $42.50 at TEST MERCHANT was approved."
        result, stage = extract_transaction(client, _email(body, institution="RBC"))
        assert stage is None
        assert result == {
            "amount": 42.50,
            "company": "TEST MERCHANT",
            "transaction_type": "purchase",
            "institution": "RBC",
        }

    def test_institution_defaults_to_other(self) -> None:
        client = MagicMock()
        client.chat.return_value = _make_completion(
            "extract_transaction",
            {"amount": "10.00", "company": "Acme", "transaction_type": "purchase"},
        )
        body = "A purchase of $10.00 at Acme."
        result, stage = extract_transaction(client, _email(body))
        assert stage is None
        assert result is not None
        assert result["institution"] == "Other"

    def test_amount_is_float(self) -> None:
        client = MagicMock()
        client.chat.return_value = _make_completion(
            "extract_transaction",
            {"amount": "1,234.56", "company": "Acme", "transaction_type": "purchase"},
        )
        body = "A purchase of $1,234.56 at Acme."
        result, stage = extract_transaction(client, _email(body))
        assert stage is None
        assert result is not None
        assert isinstance(result["amount"], float)
        assert result["amount"] == 1234.56


# ---------------------------------------------------------------------------
# extract_transaction — extraction-failure fallbacks (ai_extraction_failed)
# ---------------------------------------------------------------------------


class TestExtractTransactionExtractionFailed:
    def test_no_client(self) -> None:
        result, stage = extract_transaction(None, _email("A purchase of $5.00 at Acme."))
        assert result is None
        assert stage == "ai_extraction_failed"

    def test_api_error(self) -> None:
        client = MagicMock()
        client.chat.side_effect = Exception("API timeout")
        result, stage = extract_transaction(client, _email("A purchase of $5.00 at Acme."))
        assert result is None
        assert stage == "ai_extraction_failed"

    def test_none_completion(self) -> None:
        client = MagicMock()
        client.chat.return_value = None
        result, stage = extract_transaction(client, _email("A purchase of $5.00 at Acme."))
        assert result is None
        assert stage == "ai_extraction_failed"

    def test_no_choices_completion(self) -> None:
        client = MagicMock()
        client.chat.return_value = SimpleNamespace()  # no .choices
        result, stage = extract_transaction(client, _email("A purchase of $5.00 at Acme."))
        assert result is None
        assert stage == "ai_extraction_failed"

    def test_empty_tool_calls(self) -> None:
        client = MagicMock()
        client.chat.return_value = _make_empty_completion()
        result, stage = extract_transaction(client, _email("A purchase of $5.00 at Acme."))
        assert result is None
        assert stage == "ai_extraction_failed"

    def test_parse_error_malformed_json(self) -> None:
        client = MagicMock()
        completion = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        tool_calls=[
                            SimpleNamespace(
                                function=SimpleNamespace(
                                    name="extract_transaction",
                                    arguments="not valid json",
                                )
                            )
                        ]
                    )
                )
            ]
        )
        client.chat.return_value = completion
        result, stage = extract_transaction(client, _email("A purchase of $5.00 at Acme."))
        assert result is None
        assert stage == "ai_extraction_failed"

    def test_incomplete_fields(self) -> None:
        """Model omits a required field → treated as an extraction failure."""
        client = MagicMock()
        client.chat.return_value = _make_completion(
            "extract_transaction",
            {"amount": "5.00", "transaction_type": "purchase"},  # no company
        )
        result, stage = extract_transaction(client, _email("A purchase of $5.00 at Acme."))
        assert result is None
        assert stage == "ai_extraction_failed"


# ---------------------------------------------------------------------------
# extract_transaction — validation matrix (ai_validation_failed)
# ---------------------------------------------------------------------------


class TestExtractTransactionValidation:
    def test_amount_rendering_mismatch_still_accepts(self) -> None:
        """Model said 1234.56, body renders it as 1,234.56 → accept."""
        client = MagicMock()
        client.chat.return_value = _make_completion(
            "extract_transaction",
            {"amount": "1234.56", "company": "Acme", "transaction_type": "purchase"},
        )
        body = "A purchase of $1,234.56 at Acme."
        result, stage = extract_transaction(client, _email(body))
        assert stage is None
        assert result is not None
        assert result["amount"] == 1234.56

    def test_amount_absent_from_body_rejected(self) -> None:
        client = MagicMock()
        client.chat.return_value = _make_completion(
            "extract_transaction",
            {"amount": "99.99", "company": "Acme", "transaction_type": "purchase"},
        )
        body = "A purchase of $5.00 at Acme."  # 99.99 not present
        result, stage = extract_transaction(client, _email(body))
        assert result is None
        assert stage == "ai_validation_failed"

    def test_company_absent_from_body_rejected(self) -> None:
        client = MagicMock()
        client.chat.return_value = _make_completion(
            "extract_transaction",
            {"amount": "5.00", "company": "Hallucinated Inc", "transaction_type": "purchase"},
        )
        body = "A purchase of $5.00 at Acme."  # company not present
        result, stage = extract_transaction(client, _email(body))
        assert result is None
        assert stage == "ai_validation_failed"

    def test_negative_amount_rejected(self) -> None:
        client = MagicMock()
        client.chat.return_value = _make_completion(
            "extract_transaction",
            {"amount": "-5.00", "company": "Acme", "transaction_type": "purchase"},
        )
        body = "A refund of $-5.00 at Acme."
        result, stage = extract_transaction(client, _email(body))
        assert result is None
        assert stage == "ai_validation_failed"

    def test_zero_amount_rejected(self) -> None:
        client = MagicMock()
        client.chat.return_value = _make_completion(
            "extract_transaction",
            {"amount": "0.00", "company": "Acme", "transaction_type": "purchase"},
        )
        body = "A purchase of $0.00 at Acme."
        result, stage = extract_transaction(client, _email(body))
        assert result is None
        assert stage == "ai_validation_failed"


# ---------------------------------------------------------------------------
# validate_extraction — pure-helper unit coverage
# ---------------------------------------------------------------------------


class TestValidateExtraction:
    BODY = "Your purchase of $1,234.56 at TEST  MERCHANT was approved."

    def test_accepts_comma_rendering_when_model_plain(self) -> None:
        assert validate_extraction("1234.56", "TEST MERCHANT", self.BODY) is True

    def test_accepts_raw_model_string(self) -> None:
        assert validate_extraction("1,234.56", "TEST MERCHANT", self.BODY) is True

    def test_accepts_with_dollar_prefix(self) -> None:
        assert validate_extraction("$1,234.56", "TEST MERCHANT", self.BODY) is True

    def test_company_whitespace_collapsed_match(self) -> None:
        # body has two spaces in "TEST  MERCHANT"; needle has one.
        assert validate_extraction("1234.56", "TEST MERCHANT", self.BODY) is True

    def test_company_case_insensitive(self) -> None:
        assert validate_extraction("1234.56", "test merchant", self.BODY) is True

    def test_rejects_amount_not_in_body(self) -> None:
        assert validate_extraction("9999.99", "TEST MERCHANT", self.BODY) is False

    def test_rejects_company_not_in_body(self) -> None:
        assert validate_extraction("1234.56", "Other Co", self.BODY) is False

    def test_rejects_empty_company(self) -> None:
        assert validate_extraction("1234.56", "   ", self.BODY) is False

    def test_rejects_unparseable_amount(self) -> None:
        assert validate_extraction("abc", "TEST MERCHANT", self.BODY) is False

    def test_rejects_negative_amount(self) -> None:
        assert validate_extraction("-1234.56", "TEST MERCHANT", self.BODY) is False

    def test_rejects_zero_amount(self) -> None:
        assert validate_extraction("0", "TEST MERCHANT", self.BODY) is False

    def test_accepts_integer_amount_no_decimals(self) -> None:
        body = "A withdrawal of $1,000 from your account at Acme."
        assert validate_extraction("1000", "Acme", body) is True

    def test_accepts_integer_amount_comma_rendering(self) -> None:
        body = "A withdrawal of $1,000 from your account at Acme."
        # model emits "1000.00", body shows "1,000"
        assert validate_extraction("1000.00", "Acme", body) is True
