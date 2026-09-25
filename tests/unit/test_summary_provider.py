"""Tests for summary provider abstraction — OpenAI, Claude Code, OpenAI Codex."""

import asyncio
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from src.finance.ai_cli import _extract_codex_answer
from src.finance.summary_provider import (
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


def _completion(summary: str | None, refusal: str | None = None) -> MagicMock:
    """A stand-in for the SDK's ParsedChatCompletion with one choice."""
    message = MagicMock()
    message.parsed = DaySummaryResult(summary=summary) if summary is not None else None
    message.refusal = refusal
    completion = MagicMock()
    completion.choices = [MagicMock(message=message)]
    return completion


def _validation_error() -> ValidationError:
    try:
        DaySummaryResult.model_validate_json("{}")
    except ValidationError as exc:
        return exc
    raise AssertionError("expected a ValidationError")


@pytest.fixture
def openai_client() -> Iterator[MagicMock]:
    """Patch the SDK constructor; yields the client the provider builds."""
    with patch("openai.OpenAI") as mock_cls:
        yield mock_cls.return_value


class TestOpenAISummaryProvider:
    def test_generates_summaries(self, openai_client: MagicMock) -> None:
        openai_client.chat.completions.parse.return_value = _completion("A grocery-heavy day with $50 spent.")

        provider = OpenAISummaryProvider(api_key="sk-test", model="gpt-4o-mini")
        results = asyncio.run(provider.generate_summaries([_make_ctx()]))
        assert results == {"2026-04-15": "A grocery-heavy day with $50 spent."}

        kwargs = openai_client.chat.completions.parse.call_args.kwargs
        assert kwargs["model"] == "gpt-4o-mini"
        assert kwargs["response_format"] is DaySummaryResult
        assert "reasoning_effort" not in kwargs

    def test_passes_reasoning_effort_when_set(self, openai_client: MagicMock) -> None:
        openai_client.chat.completions.parse.return_value = _completion("Summary text.")

        provider = OpenAISummaryProvider(api_key="sk-test", reasoning_effort="low")
        asyncio.run(provider.generate_summaries([_make_ctx()]))
        assert openai_client.chat.completions.parse.call_args.kwargs["reasoning_effort"] == "low"

    def test_calls_on_complete(self, openai_client: MagicMock) -> None:
        openai_client.chat.completions.parse.return_value = _completion("Summary text.")

        completed = []
        provider = OpenAISummaryProvider(api_key="sk-test")
        asyncio.run(provider.generate_summaries([_make_ctx()], on_complete=lambda d, t: completed.append((d, t))))
        assert completed == [("2026-04-15", "Summary text.")]

    def test_retries_once_on_validation_error(self, openai_client: MagicMock) -> None:
        openai_client.chat.completions.parse.side_effect = [_validation_error(), _completion("Second try.")]

        provider = OpenAISummaryProvider(api_key="sk-test")
        results = asyncio.run(provider.generate_summaries([_make_ctx()]))
        assert results == {"2026-04-15": "Second try."}
        assert openai_client.chat.completions.parse.call_count == 2

    def test_retries_once_on_refusal(self, openai_client: MagicMock) -> None:
        openai_client.chat.completions.parse.side_effect = [_completion(None, refusal="no"), _completion("Retry.")]

        provider = OpenAISummaryProvider(api_key="sk-test")
        results = asyncio.run(provider.generate_summaries([_make_ctx()]))
        assert results == {"2026-04-15": "Retry."}

    def test_gives_up_after_second_parse_failure(self, openai_client: MagicMock) -> None:
        openai_client.chat.completions.parse.side_effect = [_validation_error(), _validation_error()]

        provider = OpenAISummaryProvider(api_key="sk-test")
        results = asyncio.run(provider.generate_summaries([_make_ctx()]))
        assert results == {}
        assert openai_client.chat.completions.parse.call_count == 2

    def test_handles_api_error_gracefully(self, openai_client: MagicMock) -> None:
        openai_client.chat.completions.parse.side_effect = Exception("API error")

        provider = OpenAISummaryProvider(api_key="sk-test")
        results = asyncio.run(provider.generate_summaries([_make_ctx()]))
        assert results == {}
        # Transport/API errors are not parse failures — no retry.
        assert openai_client.chat.completions.parse.call_count == 1

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
