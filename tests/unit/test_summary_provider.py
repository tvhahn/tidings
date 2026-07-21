"""Tests for summary provider abstraction — OpenAI, Claude Code, OpenAI Codex."""

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.finance.ai_cli import _extract_codex_answer
from src.finance.summary_provider import (
    ClaudeCLISummaryProvider,
    CodexCLISummaryProvider,
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


class TestOpenAISummaryProvider:
    @patch("src.finance.summary_provider.asyncio.to_thread")
    def test_generates_summaries(self, mock_to_thread: MagicMock) -> None:
        mock_result = MagicMock()
        mock_result.summary = "A grocery-heavy day with $50 spent."
        mock_to_thread.return_value = mock_result

        provider = OpenAISummaryProvider(api_key="sk-test", model="gpt-4o-mini")
        results = asyncio.run(provider.generate_summaries([_make_ctx()]))
        assert "2026-04-15" in results
        assert results["2026-04-15"] == "A grocery-heavy day with $50 spent."

    @patch("src.finance.summary_provider.asyncio.to_thread")
    def test_calls_on_complete(self, mock_to_thread: MagicMock) -> None:
        mock_result = MagicMock()
        mock_result.summary = "Summary text."
        mock_to_thread.return_value = mock_result

        completed = []
        provider = OpenAISummaryProvider(api_key="sk-test")
        asyncio.run(provider.generate_summaries([_make_ctx()], on_complete=lambda d, t: completed.append((d, t))))
        assert completed == [("2026-04-15", "Summary text.")]

    @patch("src.finance.summary_provider.asyncio.to_thread", side_effect=Exception("API error"))
    def test_handles_api_error_gracefully(self, mock_to_thread: MagicMock) -> None:
        provider = OpenAISummaryProvider(api_key="sk-test")
        results = asyncio.run(provider.generate_summaries([_make_ctx()]))
        assert results == {}

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
