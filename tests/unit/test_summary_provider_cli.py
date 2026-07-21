"""Tests for the CLI / subprocess paths in src/finance/summary_provider.py.

`tests/unit/test_summary_provider.py` already covers the OpenAI client and
the missing-binary branches of every CLI provider. This file fills the 71%
coverage gap by exercising:

- `run_cli_provider` happy path for each provider (claude_cli, codex, gemini_cli)
- `run_cli_provider` timeout, non-zero exit, unknown provider
- `ClaudeCLISummaryProvider.generate_summaries` end-to-end with subprocess mock
- `CodexCLISummaryProvider.generate_summaries` end-to-end
- `GeminiCLISummaryProvider.generate_summaries` end-to-end
- `_codex_signed_in`, `_gemini_signed_in` env / auth-file detection
- `OpenAISummaryProvider._build_prompt` no-budget branch + empty-transactions branch

The plan called this file "test_summary_provider_dynamodb.py", but the actual
71%-covered module is the LLM provider router — there is no DynamoDB code in
summary_provider.py. The `spending_summary.py` DynamoDB module was already
at 95% coverage before Phase 2.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.finance.ai_cli import _codex_signed_in, _gemini_signed_in, run_cli_provider
from src.finance.summary_provider import (
    ClaudeCLISummaryProvider,
    CodexCLISummaryProvider,
    GeminiCLISummaryProvider,
    OpenAISummaryProvider,
)


def _make_ctx(date: str = "2026-04-15") -> dict[str, Any]:
    return {
        "date": date,
        "day_of_week": "Wednesday",
        "day_total": 50.0,
        "transaction_count": 2,
        "transactions": [
            {"company": "Grocery Store", "amount": 30.0, "category": "Groceries"},
        ],
        "mtd_total": 500.0,
        "mtd_by_category": {"Groceries": 200.0},
        "budget_ceiling_monthly": 3000.0,
        "month_day_number": 15,
        "month_total_days": 30,
    }


def _mock_proc(stdout: bytes, stderr: bytes = b"", returncode: int = 0) -> MagicMock:
    """Build a mock asyncio subprocess returning (stdout, stderr) on communicate()."""
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    proc.kill = MagicMock(name="kill")
    proc.wait = AsyncMock()
    return proc


# ---------------------------------------------------------------------------
# OpenAI prompt — branches not exercised by the existing test
# ---------------------------------------------------------------------------


class TestOpenAIBuildPromptBranches:
    def test_no_budget_yields_not_configured_line(self) -> None:
        provider = OpenAISummaryProvider(api_key="sk-test")
        ctx = _make_ctx()
        ctx["budget_ceiling_monthly"] = None  # disable budget branch
        prompt = provider._build_prompt(ctx)
        assert "Budget: not configured" in prompt

    def test_empty_transactions_yields_none_for_top_items(self) -> None:
        provider = OpenAISummaryProvider(api_key="sk-test")
        ctx = _make_ctx()
        ctx["transactions"] = []
        ctx["mtd_by_category"] = {}
        prompt = provider._build_prompt(ctx)
        # Empty txns render the top-items slot as "none" and the top MTD
        # categories line likewise.
        assert "— none" in prompt
        assert "Top MTD categories: none" in prompt


# ---------------------------------------------------------------------------
# run_cli_provider — happy path per provider, error branches
# ---------------------------------------------------------------------------


class TestRunCliProviderClaude:
    @patch("src.finance.ai_cli.asyncio.create_subprocess_exec")
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/claude")
    def test_returns_full_stdout_for_claude(self, mock_which: MagicMock, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(b"## 2026-04-15\nSpent $50.\n", b"")
        result = asyncio.run(run_cli_provider("claude_cli", "prompt"))
        assert result == "## 2026-04-15\nSpent $50.\n"
        # Confirms invocation includes the model + no-session flag.
        args = mock_exec.call_args.args
        assert "/usr/bin/claude" in args
        assert "sonnet" in args
        assert "--no-session-persistence" in args

    @patch("src.finance.ai_cli.asyncio.create_subprocess_exec")
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/claude")
    def test_model_kwarg_overrides_default(self, mock_which: MagicMock, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(b"out", b"")
        asyncio.run(run_cli_provider("claude_cli", "prompt", model="haiku"))
        args = mock_exec.call_args.args
        assert "haiku" in args
        assert "sonnet" not in args

    @patch("src.finance.ai_cli.asyncio.create_subprocess_exec")
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/claude")
    def test_none_model_falls_back_to_sonnet(self, mock_which: MagicMock, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(b"out", b"")
        asyncio.run(run_cli_provider("claude_cli", "prompt"))  # model defaults to None
        args = mock_exec.call_args.args
        assert args[args.index("--model") + 1] == "sonnet"

    @patch("src.finance.ai_cli.asyncio.create_subprocess_exec")
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/claude")
    def test_reasoning_effort_appends_effort_flag(self, mock_which: MagicMock, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(b"out", b"")
        asyncio.run(run_cli_provider("claude_cli", "prompt", reasoning_effort="high"))
        args = list(mock_exec.call_args.args)
        assert args[args.index("--effort") + 1] == "high"

    @patch("src.finance.ai_cli.asyncio.create_subprocess_exec")
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/claude")
    def test_no_reasoning_effort_omits_effort_flag(self, mock_which: MagicMock, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(b"out", b"")
        asyncio.run(run_cli_provider("claude_cli", "prompt"))
        assert "--effort" not in list(mock_exec.call_args.args)


class TestRunCliProviderCodex:
    @patch("src.finance.ai_cli.asyncio.create_subprocess_exec")
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/codex")
    def test_extracts_codex_answer_after_tokens_marker(self, mock_which: MagicMock, mock_exec: AsyncMock) -> None:
        stdout = (
            b"OpenAI Codex v0.118.0 (research preview)\n"
            b"--------\n"
            b"codex\n## 2026-04-15\nSpent $50.\n"
            b"tokens used\n17,024\n"
            b"## 2026-04-15\nSpent $50.\n"
        )
        mock_exec.return_value = _mock_proc(stdout, b"")
        result = asyncio.run(run_cli_provider("codex", "prompt"))
        assert result.startswith("## 2026-04-15")
        assert "tokens used" not in result

    @patch("src.finance.ai_cli.asyncio.create_subprocess_exec")
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/codex")
    def test_model_emits_dash_m(self, mock_which: MagicMock, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(b"tokens used\n1\nanswer", b"")
        asyncio.run(run_cli_provider("codex", "prompt", model="gpt-5.2"))
        args = list(mock_exec.call_args.args)
        assert args[args.index("-m") + 1] == "gpt-5.2"

    @patch("src.finance.ai_cli.asyncio.create_subprocess_exec")
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/codex")
    def test_no_model_omits_dash_m(self, mock_which: MagicMock, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(b"tokens used\n1\nanswer", b"")
        asyncio.run(run_cli_provider("codex", "prompt"))
        assert "-m" not in list(mock_exec.call_args.args)

    @patch("src.finance.ai_cli.asyncio.create_subprocess_exec")
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/codex")
    def test_reasoning_effort_emits_config_override(self, mock_which: MagicMock, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(b"tokens used\n1\nanswer", b"")
        asyncio.run(run_cli_provider("codex", "prompt", reasoning_effort="low"))
        args = list(mock_exec.call_args.args)
        assert args[args.index("-c") + 1] == 'model_reasoning_effort="low"'

    @patch("src.finance.ai_cli.asyncio.create_subprocess_exec")
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/codex")
    def test_no_reasoning_effort_omits_config_override(self, mock_which: MagicMock, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(b"tokens used\n1\nanswer", b"")
        asyncio.run(run_cli_provider("codex", "prompt"))
        assert "-c" not in list(mock_exec.call_args.args)


class TestRunCliProviderGemini:
    @patch("src.finance.ai_cli.asyncio.create_subprocess_exec")
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/gemini")
    def test_strips_whitespace(self, mock_which: MagicMock, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(b"  ## 2026-04-15\nSummary text.  \n", b"")
        result = asyncio.run(run_cli_provider("gemini_cli", "prompt"))
        assert result == "## 2026-04-15\nSummary text."


class TestRunCliProviderImagePaths:
    """L6 image extension: claude gets a prompt line + Read tool, codex gets -i,
    gemini refuses. Existing (no-image) callers are covered above and unchanged."""

    @patch("src.finance.ai_cli.asyncio.create_subprocess_exec")
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/claude")
    def test_claude_image_appends_prompt_line_and_read_tool(self, mock_which: MagicMock, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(b"answer", b"")
        asyncio.run(run_cli_provider("claude_cli", "PROMPT", image_paths=["/abs/receipt.jpg"]))
        args = list(mock_exec.call_args.args)
        # The prompt arg (after -p) carries the on-disk line pointing at the image.
        prompt_arg = args[args.index("-p") + 1]
        assert "The receipt image is on disk at: /abs/receipt.jpg — read it." in prompt_arg
        assert prompt_arg.startswith("PROMPT")
        # Read tool must be granted, else `claude -p` refuses (Phase 0 smoke).
        assert "--allowedTools" in args
        assert args[args.index("--allowedTools") + 1] == "Read"

    @patch("src.finance.ai_cli.asyncio.create_subprocess_exec")
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/claude")
    def test_claude_without_image_omits_read_tool(self, mock_which: MagicMock, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(b"answer", b"")
        asyncio.run(run_cli_provider("claude_cli", "PROMPT"))
        args = list(mock_exec.call_args.args)
        assert "--allowedTools" not in args
        assert "on disk at" not in args[args.index("-p") + 1]

    @patch("src.finance.ai_cli.asyncio.create_subprocess_exec")
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/codex")
    def test_codex_image_adds_dash_i_per_image(self, mock_which: MagicMock, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(b"tokens used\n1\nanswer", b"")
        asyncio.run(run_cli_provider("codex", "PROMPT", image_paths=["/abs/a.jpg", "/abs/b.jpg"]))
        args = list(mock_exec.call_args.args)
        assert args.count("-i") == 2
        assert "/abs/a.jpg" in args
        assert "/abs/b.jpg" in args
        # -i args precede the positional prompt.
        assert args.index("-i") < args.index("PROMPT")

    @patch("src.finance.ai_cli.asyncio.create_subprocess_exec")
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/codex")
    def test_codex_without_image_has_no_dash_i(self, mock_which: MagicMock, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(b"tokens used\n1\nanswer", b"")
        asyncio.run(run_cli_provider("codex", "PROMPT"))
        assert "-i" not in list(mock_exec.call_args.args)

    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/gemini")
    def test_gemini_image_raises(self, mock_which: MagicMock) -> None:
        with pytest.raises(RuntimeError, match="Gemini CLI can't read receipt images"):
            asyncio.run(run_cli_provider("gemini_cli", "PROMPT", image_paths=["/abs/a.jpg"]))


class TestRunCliProviderErrors:
    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(RuntimeError, match="Unknown CLI provider"):
            asyncio.run(run_cli_provider("nonexistent", "prompt"))

    @patch("src.finance.ai_cli.shutil.which", return_value=None)
    def test_missing_claude_binary_raises(self, mock_which: MagicMock) -> None:
        with pytest.raises(RuntimeError, match="Claude Code not found"):
            asyncio.run(run_cli_provider("claude_cli", "p"))

    @patch("src.finance.ai_cli.shutil.which", return_value=None)
    def test_missing_codex_binary_raises(self, mock_which: MagicMock) -> None:
        with pytest.raises(RuntimeError, match="OpenAI Codex not found"):
            asyncio.run(run_cli_provider("codex", "p"))

    @patch("src.finance.ai_cli.shutil.which", return_value=None)
    def test_missing_gemini_binary_raises(self, mock_which: MagicMock) -> None:
        with pytest.raises(RuntimeError, match="Google Gemini not found"):
            asyncio.run(run_cli_provider("gemini_cli", "p"))

    @patch("src.finance.ai_cli.asyncio.create_subprocess_exec")
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/codex")
    def test_nonzero_exit_with_empty_stdout_raises(self, mock_which: MagicMock, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(b"", b"login required", returncode=1)
        with pytest.raises(RuntimeError, match="OpenAI Codex error"):
            asyncio.run(run_cli_provider("codex", "p"))

    @patch("src.finance.ai_cli.asyncio.create_subprocess_exec")
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/claude")
    def test_timeout_raises_and_kills_process(
        self,
        mock_which: MagicMock,
        mock_exec: AsyncMock,
    ) -> None:
        # Raising TimeoutError from communicate() (rather than from a patched
        # asyncio.wait_for) keeps the AsyncMock coroutine awaited — patching
        # wait_for to raise before consuming the coroutine leaks it and
        # surfaces as a "coroutine was never awaited" RuntimeWarning.
        proc = _mock_proc(b"", b"")
        proc.communicate = AsyncMock(side_effect=TimeoutError)
        mock_exec.return_value = proc
        with pytest.raises(RuntimeError, match="timed out"):
            asyncio.run(run_cli_provider("claude_cli", "p", timeout=1))
        proc.kill.assert_called_once()


# ---------------------------------------------------------------------------
# Per-provider generate_summaries — full path including section parsing
# ---------------------------------------------------------------------------


class TestClaudeProviderHappyPath:
    @patch("src.finance.ai_cli.asyncio.create_subprocess_exec")
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/claude")
    def test_returns_parsed_sections_and_calls_on_complete(self, mock_which: MagicMock, mock_exec: AsyncMock) -> None:
        stdout = b"## 2026-04-15\nDay one summary.\n\n## 2026-04-16\nDay two summary.\n"
        mock_exec.return_value = _mock_proc(stdout, b"")

        completed: list[tuple[str, str]] = []
        provider = ClaudeCLISummaryProvider()
        results = asyncio.run(
            provider.generate_summaries(
                [_make_ctx("2026-04-15"), _make_ctx("2026-04-16")],
                on_complete=lambda d, t: completed.append((d, t)),
            )
        )

        assert results == {
            "2026-04-15": "Day one summary.",
            "2026-04-16": "Day two summary.",
        }
        assert sorted(completed) == [
            ("2026-04-15", "Day one summary."),
            ("2026-04-16", "Day two summary."),
        ]


class TestCodexProviderHappyPath:
    @patch("src.finance.ai_cli.asyncio.create_subprocess_exec")
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/codex")
    def test_parses_after_tokens_marker(self, mock_which: MagicMock, mock_exec: AsyncMock) -> None:
        stdout = (
            b"--------\nworkdir: /tmp\n"
            b"codex\n## 2026-04-15\nDay summary.\n"
            b"tokens used\n123\n"
            b"## 2026-04-15\nDay summary.\n"
        )
        mock_exec.return_value = _mock_proc(stdout, b"")

        provider = CodexCLISummaryProvider()
        results = asyncio.run(provider.generate_summaries([_make_ctx("2026-04-15")]))
        assert results == {"2026-04-15": "Day summary."}


class TestGeminiProviderHappyPath:
    @patch("src.finance.ai_cli.asyncio.create_subprocess_exec")
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/gemini")
    def test_parses_sections(self, mock_which: MagicMock, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(b"## 2026-04-15\nDay summary.\n", b"")

        provider = GeminiCLISummaryProvider()
        results = asyncio.run(provider.generate_summaries([_make_ctx("2026-04-15")]))
        assert results == {"2026-04-15": "Day summary."}

    @patch("src.finance.ai_cli.asyncio.create_subprocess_exec")
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/gemini")
    def test_empty_day_contexts_uses_unknown_month(self, mock_which: MagicMock, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(b"", b"")
        provider = GeminiCLISummaryProvider()
        results = asyncio.run(provider.generate_summaries([]))
        assert results == {}


# ---------------------------------------------------------------------------
# _codex_signed_in / _gemini_signed_in
# ---------------------------------------------------------------------------


class TestCodexSignedIn:
    @patch("src.finance.ai_cli.shutil.which", return_value=None)
    def test_false_when_binary_missing(self, mock_which: MagicMock) -> None:
        assert _codex_signed_in() is False

    @patch("src.finance.ai_cli.Path.exists", return_value=False)
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/codex")
    def test_false_when_auth_file_missing(self, mock_which: MagicMock, mock_exists: MagicMock) -> None:
        assert _codex_signed_in() is False

    @patch("src.finance.ai_cli.Path.exists", return_value=True)
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/codex")
    def test_true_when_binary_and_auth_present(self, mock_which: MagicMock, mock_exists: MagicMock) -> None:
        assert _codex_signed_in() is True


class TestGeminiSignedIn:
    @patch("src.finance.ai_cli.shutil.which", return_value=None)
    def test_false_when_binary_missing(self, mock_which: MagicMock) -> None:
        assert _gemini_signed_in() is False

    @patch.dict("os.environ", {}, clear=True)
    @patch("src.finance.ai_cli.Path.exists", return_value=False)
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/gemini")
    def test_false_when_no_creds_or_api_key(
        self,
        mock_which: MagicMock,
        mock_exists: MagicMock,
    ) -> None:
        assert _gemini_signed_in() is False

    @patch("src.finance.ai_cli.Path.exists", return_value=True)
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/gemini")
    def test_true_when_oauth_creds_exist(self, mock_which: MagicMock, mock_exists: MagicMock) -> None:
        assert _gemini_signed_in() is True

    @patch.dict("os.environ", {"GEMINI_API_KEY": "abc"})
    @patch("src.finance.ai_cli.Path.exists", return_value=False)
    @patch("src.finance.ai_cli.shutil.which", return_value="/usr/bin/gemini")
    def test_true_when_env_api_key_set(
        self,
        mock_which: MagicMock,
        mock_exists: MagicMock,
    ) -> None:
        assert _gemini_signed_in() is True
