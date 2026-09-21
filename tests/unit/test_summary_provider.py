"""Tests for summary provider abstraction — OpenAI, Claude Code, OpenAI Codex.

The OpenAI provider talks to the shared ``OpenAIClient`` (Responses API,
``store=False``) with a forced function tool derived from ``DaySummaryResult``
— it no longer goes through ``instructor``. These tests therefore fake
chat-completion-shaped replies, and one of them drives a real ``OpenAIClient``
whose SDK handle is a mock so the Responses request itself can be inspected.

Everything here uses fakes — no network, ever.
"""

import asyncio
import json
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.finance.ai_cli import DEFAULT_OPENAI_CHAT_MODEL, _extract_codex_answer
from src.finance.openai_client import OpenAIClient
from src.finance.summary_provider import (
    DAY_SUMMARY_TOOL_NAME,
    ClaudeCLISummaryProvider,
    CodexCLISummaryProvider,
    DaySummaryResult,
    GeminiCLISummaryProvider,
    OpenAISummaryProvider,
    _parse_sections,
    create_summary_provider,
)


def _make_ctx(date: str = "2026-04-15") -> dict[str, Any]:
    return {
        "date": date,
        "day_of_week": "Wednesday",
        "day_total": 50.0,
        "transaction_count": 2,
        "transactions": [
            {"company": "Grocery Store", "amount": 30.0, "category": "Groceries"},
            {"company": "Coffee Shop", "amount": 20.0, "category": "Restaurant/Dining"},
        ],
        "mtd_total": 500.0,
        "mtd_by_category": {"Groceries": 200.0, "Restaurant/Dining": 150.0},
        "budget_ceiling_monthly": 3000.0,
        "budget_categories": None,
        "month_day_number": 15,
        "month_total_days": 30,
        "previous_month_total": 2800.0,
    }


# --------------------------------------------------------------------------- #
# Fakes shaped like what OpenAIClient.chat returns (chat-completion shape)
# --------------------------------------------------------------------------- #


def _completion(tool_calls: list[Any] | None, content: str | None = None) -> SimpleNamespace:
    message = SimpleNamespace(role="assistant", content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(index=0, message=message)], usage=None)


def _tool_call(arguments: str, name: str = DAY_SUMMARY_TOOL_NAME) -> SimpleNamespace:
    return SimpleNamespace(
        id="call_1",
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _summary_completion(summary: str) -> SimpleNamespace:
    return _completion([_tool_call(json.dumps({"summary": summary}))])


def _fake_client(chat: MagicMock, last_error: Exception | None = None) -> MagicMock:
    """A stand-in for ``OpenAIClient`` with a scripted ``chat``."""
    client = MagicMock(name="openai_client")
    client.chat = chat
    client.last_error = last_error
    return client


class TestOpenAISummaryProvider:
    def test_generates_summaries(self) -> None:
        chat = MagicMock(name="chat", return_value=_summary_completion("A grocery-heavy day with $50 spent."))
        with patch("src.finance.summary_provider.OpenAIClient", return_value=_fake_client(chat)):
            provider = OpenAISummaryProvider(api_key="sk-test", model="gpt-4o-mini")
            results = asyncio.run(provider.generate_summaries([_make_ctx()]))
        assert "2026-04-15" in results
        assert results["2026-04-15"] == "A grocery-heavy day with $50 spent."

    def test_calls_on_complete(self) -> None:
        chat = MagicMock(name="chat", return_value=_summary_completion("Summary text."))
        completed = []
        with patch("src.finance.summary_provider.OpenAIClient", return_value=_fake_client(chat)):
            provider = OpenAISummaryProvider(api_key="sk-test")
            asyncio.run(provider.generate_summaries([_make_ctx()], on_complete=lambda d, t: completed.append((d, t))))
        assert completed == [("2026-04-15", "Summary text.")]

    def test_handles_api_error_gracefully(self) -> None:
        chat = MagicMock(name="chat", side_effect=Exception("API error"))
        with patch("src.finance.summary_provider.OpenAIClient", return_value=_fake_client(chat)):
            provider = OpenAISummaryProvider(api_key="sk-test")
            results = asyncio.run(provider.generate_summaries([_make_ctx()]))
        assert results == {}

    def test_one_failed_day_does_not_abort_the_others(self) -> None:
        chat = MagicMock(
            name="chat",
            side_effect=[
                _summary_completion("Day one."),
                Exception("API error"),
                _summary_completion("Day three."),
            ],
        )
        contexts = [_make_ctx("2026-04-13"), _make_ctx("2026-04-14"), _make_ctx("2026-04-15")]
        with patch("src.finance.summary_provider.OpenAIClient", return_value=_fake_client(chat)):
            provider = OpenAISummaryProvider(api_key="sk-test")
            results = asyncio.run(provider.generate_summaries(contexts))
        assert results == {"2026-04-13": "Day one.", "2026-04-15": "Day three."}

    def test_forces_a_tool_derived_from_the_pydantic_model(self) -> None:
        chat = MagicMock(name="chat", return_value=_summary_completion("Summary text."))
        with patch("src.finance.summary_provider.OpenAIClient", return_value=_fake_client(chat)):
            asyncio.run(OpenAISummaryProvider(api_key="sk-test").generate_summaries([_make_ctx()]))

        kwargs = chat.call_args.kwargs
        assert list(kwargs["messages"][0]) == ["role", "content"]
        assert kwargs["messages"][0]["role"] == "user"
        assert kwargs["messages"][0]["content"].startswith("You are a personal finance assistant.")

        expected_schema = DaySummaryResult.model_json_schema()
        expected_schema.pop("title", None)
        (tool,) = kwargs["tools"]
        assert tool["type"] == "function"
        assert tool["function"]["name"] == DAY_SUMMARY_TOOL_NAME
        assert tool["function"]["parameters"] == expected_schema
        # The field description carries the length/format instruction.
        assert tool["function"]["parameters"]["properties"]["summary"]["description"] == (
            "single sentence, ≤25 words, plain text"
        )
        assert tool["function"]["parameters"]["required"] == ["summary"]
        assert "strict" not in tool["function"]
        assert kwargs["tool_choice"] == {"type": "function", "function": {"name": DAY_SUMMARY_TOOL_NAME}}

    def test_none_completion_skips_the_day_and_logs_the_error_type(self, caplog: pytest.LogCaptureFixture) -> None:
        chat = MagicMock(name="chat", return_value=None)
        client = _fake_client(chat, last_error=TimeoutError("upstream timed out"))
        with (
            patch("src.finance.summary_provider.OpenAIClient", return_value=client),
            caplog.at_level(logging.ERROR, logger="src.finance.summary_provider"),
        ):
            results = asyncio.run(OpenAISummaryProvider(api_key="sk-test").generate_summaries([_make_ctx()]))

        assert results == {}
        assert "2026-04-15" in caplog.text
        assert "TimeoutError" in caplog.text
        # The classified reason only — never the prompt or the transactions.
        assert "upstream timed out" not in caplog.text
        assert "Grocery Store" not in caplog.text

    def test_response_without_a_tool_call_skips_the_day(self, caplog: pytest.LogCaptureFixture) -> None:
        chat = MagicMock(name="chat", return_value=_completion(None, content="I could not comply."))
        with (
            patch("src.finance.summary_provider.OpenAIClient", return_value=_fake_client(chat)),
            caplog.at_level(logging.ERROR, logger="src.finance.summary_provider"),
        ):
            results = asyncio.run(OpenAISummaryProvider(api_key="sk-test").generate_summaries([_make_ctx()]))

        assert results == {}
        assert "no tool call" in caplog.text

    def test_invalid_json_arguments_skip_the_day(self, caplog: pytest.LogCaptureFixture) -> None:
        chat = MagicMock(name="chat", return_value=_completion([_tool_call("{not json")]))
        with (
            patch("src.finance.summary_provider.OpenAIClient", return_value=_fake_client(chat)),
            caplog.at_level(logging.ERROR, logger="src.finance.summary_provider"),
        ):
            results = asyncio.run(OpenAISummaryProvider(api_key="sk-test").generate_summaries([_make_ctx()]))

        assert results == {}
        assert "failed validation" in caplog.text

    def test_missing_summary_field_skips_the_day(self, caplog: pytest.LogCaptureFixture) -> None:
        chat = MagicMock(name="chat", return_value=_completion([_tool_call(json.dumps({"text": "wrong key"}))]))
        with (
            patch("src.finance.summary_provider.OpenAIClient", return_value=_fake_client(chat)),
            caplog.at_level(logging.ERROR, logger="src.finance.summary_provider"),
        ):
            results = asyncio.run(OpenAISummaryProvider(api_key="sk-test").generate_summaries([_make_ctx()]))

        assert results == {}
        assert "failed validation" in caplog.text
        assert "missing" in caplog.text

    def test_empty_arguments_skip_the_day(self, caplog: pytest.LogCaptureFixture) -> None:
        chat = MagicMock(name="chat", return_value=_completion([_tool_call("")]))
        with (
            patch("src.finance.summary_provider.OpenAIClient", return_value=_fake_client(chat)),
            caplog.at_level(logging.ERROR, logger="src.finance.summary_provider"),
        ):
            results = asyncio.run(OpenAISummaryProvider(api_key="sk-test").generate_summaries([_make_ctx()]))

        assert results == {}
        assert "no arguments" in caplog.text

    def test_model_and_reasoning_effort_reach_the_client(self) -> None:
        chat = MagicMock(name="chat", return_value=_summary_completion("Summary text."))
        with patch("src.finance.summary_provider.OpenAIClient", return_value=_fake_client(chat)) as mock_cls:
            provider = OpenAISummaryProvider(api_key="sk-test", model="gpt-5.6-terra", reasoning_effort="high")
            asyncio.run(provider.generate_summaries([_make_ctx("2026-04-14"), _make_ctx("2026-04-15")]))

        assert mock_cls.call_args.kwargs == {
            "model": "gpt-5.6-terra",
            "api_key": "sk-test",
            "reasoning_effort": "high",
        }
        # One client per generate_summaries call, whatever the day count.
        assert mock_cls.call_count == 1

    def test_absent_reasoning_effort_is_passed_as_none(self) -> None:
        chat = MagicMock(name="chat", return_value=_summary_completion("Summary text."))
        with patch("src.finance.summary_provider.OpenAIClient", return_value=_fake_client(chat)) as mock_cls:
            asyncio.run(OpenAISummaryProvider(api_key="sk-test").generate_summaries([_make_ctx()]))

        assert mock_cls.call_args.kwargs == {
            "model": DEFAULT_OPENAI_CHAT_MODEL,
            "api_key": "sk-test",
            "reasoning_effort": None,
        }

    def test_end_to_end_through_a_real_client_sends_store_false(self) -> None:
        """Real ``OpenAIClient``, faked SDK handle: the Responses request is inspectable."""
        created: list[OpenAIClient] = []

        def _build(**kwargs: Any) -> OpenAIClient:
            client = OpenAIClient(**kwargs)
            client.client = MagicMock(name="openai_sdk")
            client.client.responses.create.return_value = SimpleNamespace(
                id="resp_1",
                object="response",
                status="completed",
                error=None,
                incomplete_details=None,
                output=[
                    SimpleNamespace(
                        type="function_call",
                        call_id="call_1",
                        id="fc_1",
                        name=DAY_SUMMARY_TOOL_NAME,
                        arguments=json.dumps({"summary": "Groceries led the day at $30."}),
                        status="completed",
                    )
                ],
                usage=None,
            )
            created.append(client)
            return client

        with patch("src.finance.summary_provider.OpenAIClient", side_effect=_build):
            provider = OpenAISummaryProvider(api_key="sk-test", reasoning_effort="low")
            results = asyncio.run(provider.generate_summaries([_make_ctx()]))

        assert results == {"2026-04-15": "Groceries led the day at $30."}
        kwargs = created[0].client.responses.create.call_args.kwargs  # type: ignore[union-attr]
        assert kwargs["store"] is False
        assert kwargs["model"] == DEFAULT_OPENAI_CHAT_MODEL
        assert kwargs["reasoning"] == {"effort": "low"}
        # Translated into Responses vocabulary: flat tool, flat tool choice.
        assert kwargs["tool_choice"] == {"type": "function", "name": DAY_SUMMARY_TOOL_NAME}
        assert kwargs["tools"][0]["name"] == DAY_SUMMARY_TOOL_NAME
        assert kwargs["tools"][0]["strict"] is False
        assert kwargs["input"][0]["role"] == "user"

    def test_empty_summary_string_is_still_recorded(self) -> None:
        """Unchanged from the instructor transport: a valid but empty string is a result."""
        chat = MagicMock(name="chat", return_value=_summary_completion(""))
        completed = []
        with patch("src.finance.summary_provider.OpenAIClient", return_value=_fake_client(chat)):
            provider = OpenAISummaryProvider(api_key="sk-test")
            results = asyncio.run(
                provider.generate_summaries([_make_ctx()], on_complete=lambda d, t: completed.append((d, t)))
            )
        assert results == {"2026-04-15": ""}
        assert completed == [("2026-04-15", "")]

    def test_build_prompt_includes_key_data(self) -> None:
        provider = OpenAISummaryProvider(api_key="sk-test")
        prompt = provider._build_prompt(_make_ctx())
        assert "Wednesday" in prompt
        assert "2026-04-15" in prompt
        assert "$50.00" in prompt
        assert "Grocery Store" in prompt
        assert "day 15/30" in prompt


class TestParseSections:
    def test_parse_sections(self) -> None:
        text = (
            "Some preamble text\n\n"
            "## 2026-04-14\n"
            "Monday was a quiet day.\n\n"
            "## 2026-04-15\n"
            "A busy Tuesday with lots of spending.\n"
        )
        results = _parse_sections(text)
        assert "2026-04-14" in results
        assert "2026-04-15" in results
        assert "quiet day" in results["2026-04-14"]
        assert "busy Tuesday" in results["2026-04-15"]

    def test_parse_sections_empty(self) -> None:
        results = _parse_sections("No sections here.")
        assert results == {}


class TestExtractCodexAnswer:
    def test_strips_header_and_tokens_preamble(self) -> None:
        stdout = (
            "OpenAI Codex v0.118.0 (research preview)\n"
            "--------\nworkdir: /tmp\nmodel: gpt-5.4\n"
            "--------\nuser\nWrite a summary\n"
            "codex\n## 2026-04-15\nSpent $50 on groceries.\n"
            "tokens used\n17,024\n"
            "## 2026-04-15\nSpent $50 on groceries.\n"
        )
        result = _extract_codex_answer(stdout)
        assert result == "## 2026-04-15\nSpent $50 on groceries."

    def test_falls_back_to_full_stdout_when_no_marker(self) -> None:
        result = _extract_codex_answer("just some text\n")
        assert result == "just some text"


class TestClaudeCLISummaryProvider:
    @patch("src.finance.ai_cli.shutil.which", return_value=None)
    def test_raises_if_no_claude_binary(self, mock_which: MagicMock) -> None:
        provider = ClaudeCLISummaryProvider()
        with pytest.raises(RuntimeError, match="Claude Code not found"):
            asyncio.run(provider.generate_summaries([_make_ctx()]))


class TestCodexCLISummaryProvider:
    @patch("src.finance.ai_cli.shutil.which", return_value=None)
    def test_raises_if_no_codex_binary(self, mock_which: MagicMock) -> None:
        provider = CodexCLISummaryProvider()
        with pytest.raises(RuntimeError, match="OpenAI Codex not found"):
            asyncio.run(provider.generate_summaries([_make_ctx()]))


class TestGeminiCLISummaryProvider:
    @patch("src.finance.ai_cli.shutil.which", return_value=None)
    def test_raises_if_no_gemini_binary(self, mock_which: MagicMock) -> None:
        provider = GeminiCLISummaryProvider()
        with pytest.raises(RuntimeError, match="Google Gemini not found"):
            asyncio.run(provider.generate_summaries([_make_ctx()]))


class TestCreateSummaryProvider:
    @patch("src.finance.secrets.get_openai_api_key", return_value="sk-test")
    def test_creates_openai_provider(self, mock_key: MagicMock) -> None:
        provider = create_summary_provider("openai")
        assert isinstance(provider, OpenAISummaryProvider)

    @patch("src.finance.secrets.get_openai_api_key", side_effect=RuntimeError("no key"))
    def test_returns_none_when_no_openai_key(self, mock_key: MagicMock) -> None:
        provider = create_summary_provider("openai")
        assert provider is None

    @patch("src.finance.summary_provider.shutil.which", return_value="/usr/bin/claude")
    def test_creates_claude_provider(self, mock_which: MagicMock) -> None:
        provider = create_summary_provider("claude_cli")
        assert isinstance(provider, ClaudeCLISummaryProvider)

    @patch("src.finance.summary_provider.shutil.which", return_value=None)
    def test_returns_none_when_no_claude_cli(self, mock_which: MagicMock) -> None:
        provider = create_summary_provider("claude_cli")
        assert provider is None

    @patch("src.finance.summary_provider._codex_signed_in", return_value=True)
    def test_creates_codex_provider(self, mock_signed: MagicMock) -> None:
        provider = create_summary_provider("codex")
        assert isinstance(provider, CodexCLISummaryProvider)

    @patch("src.finance.summary_provider._codex_signed_in", return_value=False)
    def test_returns_none_when_codex_not_signed_in(self, mock_signed: MagicMock) -> None:
        provider = create_summary_provider("codex")
        assert provider is None

    @patch("src.finance.summary_provider._gemini_signed_in", return_value=True)
    def test_creates_gemini_provider(self, mock_signed: MagicMock) -> None:
        provider = create_summary_provider("gemini_cli")
        assert isinstance(provider, GeminiCLISummaryProvider)

    @patch("src.finance.summary_provider._gemini_signed_in", return_value=False)
    def test_returns_none_when_gemini_not_signed_in(self, mock_signed: MagicMock) -> None:
        provider = create_summary_provider("gemini_cli")
        assert provider is None

    def test_returns_none_for_disabled(self) -> None:
        provider = create_summary_provider("disabled")
        assert provider is None

    def test_returns_none_for_unknown(self) -> None:
        provider = create_summary_provider("unknown")
        assert provider is None
