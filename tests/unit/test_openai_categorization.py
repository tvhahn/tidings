"""Mocked unit tests for OpenAI categorization and transaction alert detection.

Tests cover error/fallback paths in categorize_transactions() and
email_is_transaction_alert() — the happy-path integration test lives in
tests/integration/test_openai_categorization.py.
"""

import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import APIError, AuthenticationError, PermissionDeniedError, RateLimitError

from src.finance.ai_client import AIClientError
from src.finance.categorizer import _classify_ai_error, categorize_transactions, email_is_transaction_alert
from src.finance.openai_client import OpenAIClient

_REQ = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


def _openai_error(cls: type, status: int, body: dict[str, Any] | None) -> Exception:
    """Construct a real OpenAI SDK error so isinstance-based classification runs."""
    return cls("msg", response=httpx.Response(status, request=_REQ), body=body)


# ---------------------------------------------------------------------------
# Helpers to build mock OpenAI completion objects
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


def _make_no_choices_completion() -> SimpleNamespace:
    """Build a completion with an empty choices list."""
    return SimpleNamespace(choices=[])


# ---------------------------------------------------------------------------
# OpenAIClient.chat() error handling
# ---------------------------------------------------------------------------


class TestOpenAIClientChat:
    """Tests for OpenAIClient.chat() exception path (lines 14-24)."""

    @patch("src.finance.openai_client.OpenAI")
    def test_api_exception_returns_none(self, mock_openai_class: MagicMock) -> None:
        """When the underlying API call raises, chat() should return None and capture last_error."""
        boom = Exception("Connection timeout")
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = boom
        mock_openai_class.return_value = mock_client

        client = OpenAIClient(model="gpt-5.4-nano", api_key="test-key")
        result = client.chat(messages=[{"role": "user", "content": "test"}])
        assert result is None
        assert client.last_error is boom

    @patch("src.finance.openai_client.OpenAI")
    def test_successful_call_returns_response(self, mock_openai_class: MagicMock) -> None:
        """When the API call succeeds, chat() should return the response and clear last_error."""
        mock_client = MagicMock()
        expected = MagicMock()
        mock_client.chat.completions.create.return_value = expected
        mock_openai_class.return_value = mock_client

        client = OpenAIClient(model="gpt-5.4-nano", api_key="test-key")
        client.last_error = Exception("stale error from a previous call")
        result = client.chat(messages=[{"role": "user", "content": "test"}])
        assert result is expected
        assert client.last_error is None


# ---------------------------------------------------------------------------
# categorize_transactions tests
# ---------------------------------------------------------------------------


@pytest.fixture
def ai_categorization_on() -> Iterator[MagicMock]:
    """Pin ai_categorization_enabled=True so categorizer tests exercise the OpenAI path."""
    with patch(
        "src.finance.categorizer.get_config",
        return_value={"ai_categorization_enabled": True},
    ) as m:
        yield m


class TestCategorizeTransactions:
    """Unit tests for categorize_transactions() fallback/error paths."""

    TRANSACTION = {"amount": 50.00, "company": "Starbucks"}

    @pytest.fixture(autouse=True)
    def _enable_ai(self, ai_categorization_on: MagicMock) -> MagicMock:
        """All tests in this class run with AI categorization enabled."""
        return ai_categorization_on

    def test_successful_categorization(self) -> None:
        client = MagicMock()
        client.chat.return_value = _make_completion("categorize_transaction", {"category": "Restaurant/Dining"})
        result = categorize_transactions(client, self.TRANSACTION)
        assert result == "Restaurant/Dining"

    def test_api_exception_returns_miscellaneous(self) -> None:
        """When the API call raises an exception, return 'Miscellaneous'."""
        client = MagicMock()
        client.chat.side_effect = Exception("API timeout")
        result = categorize_transactions(client, self.TRANSACTION)
        assert result == "Miscellaneous"

    def test_none_completion_returns_miscellaneous(self) -> None:
        """When the API returns None, return 'Miscellaneous'."""
        client = MagicMock()
        client.chat.return_value = None
        result = categorize_transactions(client, self.TRANSACTION)
        assert result == "Miscellaneous"

    def test_no_choices_returns_miscellaneous(self) -> None:
        """When the completion has no choices attribute, return 'Miscellaneous'."""
        client = MagicMock()
        client.chat.return_value = SimpleNamespace()  # no .choices
        result = categorize_transactions(client, self.TRANSACTION)
        assert result == "Miscellaneous"

    def test_empty_tool_calls_returns_miscellaneous(self) -> None:
        """When tool_calls is None/empty, return 'Miscellaneous'."""
        client = MagicMock()
        client.chat.return_value = _make_empty_completion()
        result = categorize_transactions(client, self.TRANSACTION)
        assert result == "Miscellaneous"

    def test_malformed_arguments_json_returns_miscellaneous(self) -> None:
        """When function arguments contain invalid JSON, return 'Miscellaneous'."""
        client = MagicMock()
        completion = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        tool_calls=[
                            SimpleNamespace(
                                function=SimpleNamespace(
                                    name="categorize_transaction",
                                    arguments="not valid json",
                                )
                            )
                        ]
                    )
                )
            ]
        )
        client.chat.return_value = completion
        result = categorize_transactions(client, self.TRANSACTION)
        assert result == "Miscellaneous"

    def test_missing_category_key_returns_miscellaneous(self) -> None:
        """When function args don't contain 'category', return 'Miscellaneous'."""
        client = MagicMock()
        client.chat.return_value = _make_completion("categorize_transaction", {"wrong_key": "Groceries"})
        result = categorize_transactions(client, self.TRANSACTION)
        assert result == "Miscellaneous"

    def test_empty_category_returns_miscellaneous(self) -> None:
        """When category is empty string, return 'Miscellaneous'."""
        client = MagicMock()
        client.chat.return_value = _make_completion("categorize_transaction", {"category": ""})
        result = categorize_transactions(client, self.TRANSACTION)
        assert result == "Miscellaneous"

    @patch("src.finance.categorizer.get_override_context", return_value=({"Starbucks": "Restaurant/Dining"}, {}))
    def test_override_skips_api_call(self, _mock_ctx: MagicMock) -> None:
        """When an override matches, the API should not be called."""
        client = MagicMock(name="client")
        result = categorize_transactions(client, self.TRANSACTION)
        assert result == "Restaurant/Dining"
        client.chat.assert_not_called()

    @patch("src.finance.categorizer.get_override_context", return_value=({"starbucks": "Restaurant/Dining"}, {}))
    def test_override_case_insensitive(self, _mock_ctx: MagicMock) -> None:
        """Override matching should be case-insensitive."""
        client = MagicMock(name="client")
        transaction = {"amount": 50.00, "company": "STARBUCKS"}
        result = categorize_transactions(client, transaction)
        assert result == "Restaurant/Dining"
        client.chat.assert_not_called()

    @patch("src.finance.categorizer.get_override_context", return_value=({"Tim Hortons": "Restaurant/Dining"}, {}))
    def test_no_override_falls_through_to_api(self, _mock_ctx: MagicMock) -> None:
        """When no override matches, the normal API flow should proceed."""
        client = MagicMock(name="client")
        client.chat.return_value = _make_completion("categorize_transaction", {"category": "Groceries"})
        result = categorize_transactions(client, self.TRANSACTION)
        assert result == "Groceries"
        client.chat.assert_called_once()

    def test_custom_categories_list_passed_to_tools(self) -> None:
        """Verify custom categories are forwarded to the API call."""
        client = MagicMock(name="client")
        client.chat.return_value = _make_completion("categorize_transaction", {"category": "CustomCat"})
        result = categorize_transactions(client, self.TRANSACTION, categories=["CustomCat", "Other"])
        assert result == "CustomCat"
        # Verify the categories were included in the tools spec
        call_args = client.chat.call_args
        tools = call_args.kwargs.get("tools") or call_args[0][1]
        enum_values = tools[0]["function"]["parameters"]["properties"]["category"]["enum"]
        assert enum_values == ["CustomCat", "Other"]


class TestCategoryAuditPayload:
    """Verify categorize_transactions stamps _category_audit on the transaction dict per tier."""

    @pytest.fixture(autouse=True)
    def _enable_ai(self, ai_categorization_on: MagicMock) -> MagicMock:
        """All tests in this class run with AI categorization enabled."""
        return ai_categorization_on

    @patch("src.finance.categorizer.get_override_context", return_value=({"Starbucks": "Restaurant/Dining"}, {}))
    def test_exact_match_stamps_override_source(self, _mock_ctx: MagicMock) -> None:
        txn = {"amount": 5.0, "company": "Starbucks"}
        categorize_transactions(MagicMock(), txn)
        audit = txn["_category_audit"]
        assert audit["source"] == "override"
        assert audit["tier"] == "exact"
        assert audit["matched_rule"] == "Starbucks"
        assert audit["confidence"] == 1.0
        assert audit["reviewed_at"]  # ISO timestamp
        assert audit["schema_version"] == 2

    @patch(
        "src.finance.categorizer.get_override_context",
        return_value=({"BOOSTER JUICE #232": "Restaurant/Dining"}, {}),
    )
    def test_normalized_match_stamps_override_normalized_tier(self, _mock_ctx: MagicMock) -> None:
        txn = {"amount": 5.0, "company": "BOOSTER JUICE #999"}
        categorize_transactions(MagicMock(), txn)
        audit = txn["_category_audit"]
        assert audit["source"] == "override"
        assert audit["tier"] == "normalized"
        assert audit["matched_rule"] == "BOOSTER JUICE #232"
        assert audit["confidence"] == 1.0

    @patch(
        "src.finance.categorizer.get_override_context",
        return_value=({"AMAZON.CA": "Miscellaneous"}, {"amzn mktp": "AMAZON.CA"}),
    )
    def test_alias_match_stamps_override_alias_tier(self, _mock_ctx: MagicMock) -> None:
        txn = {"amount": 5.0, "company": "AMZN MKTP CA #8888"}
        result = categorize_transactions(MagicMock(), txn)
        assert result == "Miscellaneous"
        audit = txn["_category_audit"]
        assert audit["source"] == "override"
        assert audit["tier"] == "alias"
        assert audit["matched_rule"] == "AMAZON.CA"

    @patch("src.finance.categorizer.get_override_context", return_value=({}, {}))
    def test_ai_success_stamps_ai_source(self, _mock_ctx: MagicMock) -> None:
        client = MagicMock()
        client.model = "gpt-5.4-nano"
        client.chat.return_value = _make_completion("categorize_transaction", {"category": "Groceries"})
        txn = {"amount": 5.0, "company": "Unknown Merchant"}
        result = categorize_transactions(client, txn)
        assert result == "Groceries"
        audit = txn["_category_audit"]
        assert audit["source"] == "ai"
        assert audit["model"] == "gpt-5.4-nano"
        assert audit["schema_version"] == 2

    @patch("src.finance.categorizer.get_override_context", return_value=({}, {}))
    def test_ai_disabled_stamps_fallback_disabled(self, _mock_ctx: MagicMock) -> None:
        with patch(
            "src.finance.categorizer.get_config",
            return_value={"ai_categorization_enabled": False},
        ):
            client = MagicMock()
            client.model = "gpt-5.4-nano"
            txn = {"amount": 5.0, "company": "Unknown Merchant"}
            result = categorize_transactions(client, txn)
        assert result == "Miscellaneous"
        audit = txn["_category_audit"]
        assert audit["source"] == "ai_fallback"
        assert audit["fallback_reason"] == "disabled"
        assert audit["model"] == "gpt-5.4-nano"

    @patch("src.finance.categorizer.get_override_context", return_value=({}, {}))
    def test_no_client_stamps_fallback_no_client(self, _mock_ctx: MagicMock) -> None:
        txn = {"amount": 5.0, "company": "Unknown Merchant"}
        result = categorize_transactions(None, txn)
        assert result == "Miscellaneous"
        audit = txn["_category_audit"]
        assert audit["source"] == "ai_fallback"
        assert audit["fallback_reason"] == "no_client"
        assert "model" not in audit

    @patch("src.finance.categorizer.get_override_context", return_value=({}, {}))
    def test_api_error_stamps_fallback_api_error(self, _mock_ctx: MagicMock) -> None:
        client = MagicMock()
        client.model = "gpt-5.4-nano"
        client.chat.side_effect = RuntimeError("boom")
        txn = {"amount": 5.0, "company": "Unknown Merchant"}
        result = categorize_transactions(client, txn)
        assert result == "Miscellaneous"
        audit = txn["_category_audit"]
        assert audit["source"] == "ai_fallback"
        assert audit["fallback_reason"] == "api_error"

    @patch("src.finance.categorizer.get_override_context", return_value=({}, {}))
    def test_empty_completion_stamps_fallback_empty(self, _mock_ctx: MagicMock) -> None:
        client = MagicMock()
        client.model = "gpt-5.4-nano"
        client.chat.return_value = None
        txn = {"amount": 5.0, "company": "Unknown Merchant"}
        result = categorize_transactions(client, txn)
        assert result == "Miscellaneous"
        audit = txn["_category_audit"]
        assert audit["source"] == "ai_fallback"
        assert audit["fallback_reason"] == "empty_completion"

    @patch("src.finance.categorizer.get_override_context", return_value=({}, {}))
    def test_parse_error_stamps_fallback_parse_error(self, _mock_ctx: MagicMock) -> None:
        # Completion that looks valid but extract_function_call_args raises.
        client = MagicMock()
        client.model = "gpt-5.4-nano"
        bad = MagicMock()
        bad.choices = MagicMock()  # truthy but accessing [0] will raise
        bad.choices.__getitem__.side_effect = TypeError("nope")
        client.chat.return_value = bad
        txn = {"amount": 5.0, "company": "Unknown Merchant"}
        result = categorize_transactions(client, txn)
        assert result == "Miscellaneous"
        audit = txn["_category_audit"]
        assert audit["source"] == "ai_fallback"
        assert audit["fallback_reason"] == "parse_error"


class TestAiCategorizationOptOut:
    """Verify the `ai_categorization_enabled` privacy flag gates OpenAI calls."""

    TRANSACTION = {"amount": 50.00, "company": "Starbucks"}

    @patch("src.finance.categorizer.get_override_context", return_value=({}, {}))
    @patch(
        "src.finance.categorizer.get_config",
        return_value={"ai_categorization_enabled": False},
    )
    def test_flag_off_skips_openai_and_returns_miscellaneous(self, _mock_cfg: MagicMock, _mock_ctx: MagicMock) -> None:
        """When the flag is off, the OpenAI client is never invoked and we return Miscellaneous."""
        client = MagicMock(name="client")
        result = categorize_transactions(client, self.TRANSACTION)
        assert result == "Miscellaneous"
        client.chat.assert_not_called()

    @patch(
        "src.finance.categorizer.get_override_context",
        return_value=({"Starbucks": "Restaurant/Dining"}, {}),
    )
    @patch(
        "src.finance.categorizer.get_config",
        return_value={"ai_categorization_enabled": False},
    )
    def test_flag_off_still_honours_overrides(self, _mock_cfg: MagicMock, _mock_ctx: MagicMock) -> None:
        """Manual overrides are local-only and must still apply when AI is disabled."""
        client = MagicMock(name="client")
        result = categorize_transactions(client, self.TRANSACTION)
        assert result == "Restaurant/Dining"
        client.chat.assert_not_called()

    @patch("src.finance.categorizer.get_override_context", return_value=({}, {}))
    @patch(
        "src.finance.categorizer.get_config",
        return_value={"ai_categorization_enabled": True},
    )
    def test_flag_on_calls_openai(self, _mock_cfg: MagicMock, _mock_ctx: MagicMock) -> None:
        """When the flag is on, the OpenAI client is invoked and its result returned."""
        client = MagicMock(name="client")
        client.chat.return_value = _make_completion("categorize_transaction", {"category": "Groceries"})
        result = categorize_transactions(client, self.TRANSACTION)
        assert result == "Groceries"
        client.chat.assert_called_once()

    @patch("src.finance.categorizer.get_override_context", return_value=({}, {}))
    @patch("src.finance.categorizer.get_config", return_value={})
    def test_flag_missing_defaults_to_disabled(self, _mock_cfg: MagicMock, _mock_ctx: MagicMock) -> None:
        """If the key is absent from config (belt-and-braces), default to disabled/private."""
        client = MagicMock(name="client")
        result = categorize_transactions(client, self.TRANSACTION)
        assert result == "Miscellaneous"
        client.chat.assert_not_called()


# ---------------------------------------------------------------------------
# email_is_transaction_alert tests
# ---------------------------------------------------------------------------


class TestEmailIsTransactionAlert:
    """Unit tests for email_is_transaction_alert() paths."""

    HISTORY = [
        {"role": "system", "content": "You are an expert."},
        {"role": "user", "content": "Is this a transaction alert?"},
    ]

    def test_returns_true(self):
        client = MagicMock()
        client.chat.return_value = _make_completion("detect_if_transaction_alert", {"true_or_false": "True"})
        result = email_is_transaction_alert(client, self.HISTORY)
        assert result is True

    def test_returns_false(self):
        client = MagicMock()
        client.chat.return_value = _make_completion("detect_if_transaction_alert", {"true_or_false": "False"})
        result = email_is_transaction_alert(client, self.HISTORY)
        assert result is False

    def test_none_completion_returns_none(self):
        """API client returning None should yield None."""
        client = MagicMock()
        client.chat.return_value = None
        result = email_is_transaction_alert(client, self.HISTORY)
        assert result is None

    def test_empty_tool_calls_returns_none(self):
        """When tool_calls is None, return None."""
        client = MagicMock()
        client.chat.return_value = _make_empty_completion()
        result = email_is_transaction_alert(client, self.HISTORY)
        assert result is None

    def test_malformed_arguments_returns_none(self):
        """When function arguments contain invalid JSON, return None."""
        client = MagicMock()
        completion = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        tool_calls=[
                            SimpleNamespace(
                                function=SimpleNamespace(
                                    name="detect_if_transaction_alert",
                                    arguments="bad json",
                                )
                            )
                        ]
                    )
                )
            ]
        )
        client.chat.return_value = completion
        result = email_is_transaction_alert(client, self.HISTORY)
        assert result is None

    def test_unexpected_boolean_value_returns_none(self):
        """When true_or_false is not 'True'/'False', return None."""
        client = MagicMock()
        client.chat.return_value = _make_completion("detect_if_transaction_alert", {"true_or_false": "Maybe"})
        result = email_is_transaction_alert(client, self.HISTORY)
        assert result is None


# ---------------------------------------------------------------------------
# _classify_ai_error — maps a failed call to a specific audit reason
# ---------------------------------------------------------------------------


class TestClassifyAiError:
    """Unit tests for the audit-reason classifier."""

    def test_none_is_empty_completion(self) -> None:
        assert _classify_ai_error(None) == "empty_completion"

    def test_non_exception_is_empty_completion(self) -> None:
        # A MagicMock's .last_error attribute is a truthy non-exception — it must
        # not be misread as a transport error.
        assert _classify_ai_error(MagicMock()) == "empty_completion"
        assert _classify_ai_error("nope") == "empty_completion"

    def test_codex_reason_passthrough(self) -> None:
        assert _classify_ai_error(AIClientError("codex_timeout")) == "codex_timeout"
        assert _classify_ai_error(AIClientError("codex_error")) == "codex_error"

    def test_insufficient_quota_is_quota_exceeded(self) -> None:
        err = _openai_error(
            RateLimitError, 429, {"error": {"code": "insufficient_quota", "type": "insufficient_quota"}}
        )
        assert _classify_ai_error(err) == "quota_exceeded"

    def test_plain_rate_limit_is_rate_limited(self) -> None:
        err = _openai_error(RateLimitError, 429, {"error": {"code": "rate_limit_exceeded"}})
        assert _classify_ai_error(err) == "rate_limited"

    def test_auth_errors_are_auth_error(self) -> None:
        assert _classify_ai_error(_openai_error(AuthenticationError, 401, {"error": {}})) == "auth_error"
        assert _classify_ai_error(_openai_error(PermissionDeniedError, 403, {"error": {}})) == "auth_error"

    def test_other_api_error_is_api_error(self) -> None:
        assert _classify_ai_error(APIError("boom", _REQ, body=None)) == "api_error"

    def test_unknown_exception_is_api_error(self) -> None:
        assert _classify_ai_error(RuntimeError("boom")) == "api_error"


class TestCategorizeAuditErrorReasons:
    """The audit must record *why* an AI call failed, not a blanket empty_completion."""

    @pytest.fixture(autouse=True)
    def _enable_ai(self, ai_categorization_on: MagicMock) -> MagicMock:
        return ai_categorization_on

    @patch("src.finance.categorizer.get_override_context", return_value=({}, {}))
    def test_none_completion_with_quota_error_stamps_quota_exceeded(self, _ctx: MagicMock) -> None:
        client = MagicMock()
        client.model = "gpt-5.4-nano"
        client.chat.return_value = None
        client.last_error = _openai_error(RateLimitError, 429, {"error": {"code": "insufficient_quota"}})
        txn = {"amount": 5.0, "company": "Unknown Merchant"}
        result = categorize_transactions(client, txn)
        assert result == "Miscellaneous"
        assert txn["_category_audit"]["fallback_reason"] == "quota_exceeded"

    @patch("src.finance.categorizer.get_override_context", return_value=({}, {}))
    def test_none_completion_with_codex_timeout_stamps_codex_timeout(self, _ctx: MagicMock) -> None:
        client = MagicMock()
        client.model = None
        client.chat.return_value = None
        client.last_error = AIClientError("codex_timeout")
        txn = {"amount": 5.0, "company": "Unknown Merchant"}
        result = categorize_transactions(client, txn)
        assert result == "Miscellaneous"
        assert txn["_category_audit"]["fallback_reason"] == "codex_timeout"

    @patch("src.finance.categorizer.get_override_context", return_value=({}, {}))
    def test_raised_quota_error_stamps_quota_exceeded(self, _ctx: MagicMock) -> None:
        client = MagicMock()
        client.model = "gpt-5.4-nano"
        client.chat.side_effect = _openai_error(RateLimitError, 429, {"error": {"type": "insufficient_quota"}})
        txn = {"amount": 5.0, "company": "Unknown Merchant"}
        result = categorize_transactions(client, txn)
        assert result == "Miscellaneous"
        assert txn["_category_audit"]["fallback_reason"] == "quota_exceeded"

    @patch("src.finance.categorizer.get_override_context", return_value=({}, {}))
    def test_none_completion_without_last_error_stays_empty_completion(self, _ctx: MagicMock) -> None:
        # A client that returns None but exposes no last_error (e.g. a bare mock)
        # is a genuine empty completion — not a transport error.
        client = MagicMock()
        client.model = "gpt-5.4-nano"
        client.chat.return_value = None
        client.last_error = None
        txn = {"amount": 5.0, "company": "Unknown Merchant"}
        result = categorize_transactions(client, txn)
        assert result == "Miscellaneous"
        assert txn["_category_audit"]["fallback_reason"] == "empty_completion"
