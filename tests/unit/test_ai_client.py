"""Unit tests for the AI provider router (`src.finance.ai_client`)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from src.finance import ai_client
from src.finance.openai_client import OpenAIClient

if TYPE_CHECKING:
    import pytest

CATEGORIZE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "categorize_transaction",
            "description": "Categorize a transaction.",
            "parameters": {
                "type": "object",
                "properties": {"category": {"type": "string", "enum": ["Groceries", "Miscellaneous"]}},
                "required": ["category"],
            },
        },
    }
]
CATEGORIZE_TOOL_CHOICE = {"type": "function", "function": {"name": "categorize_transaction"}}
MESSAGES = [
    {"role": "system", "content": "You are an expert."},
    {"role": "user", "content": "Categorize this transaction."},
]


def _codex_selected(connected: bool = True, provider: str = "codex", model: str | None = None):
    """Patch context: categorization provider selection + codex availability + login state."""
    cfg: dict[str, object] = {"categorization_provider": provider}
    if model is not None:
        cfg["categorization_model"] = model
    return (
        patch("src.finance.ai_client.get_config", return_value=cfg),
        patch("src.finance.ai_client.shutil.which", return_value="/usr/bin/codex"),
        patch("src.finance.ai_client.chatgpt_oauth.is_connected", return_value=connected),
    )


class TestGetAIClient:
    def test_returns_codex_client_when_provider_selected_and_connected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        cfg, which, connected = _codex_selected()
        with cfg, which, connected:
            client = ai_client.get_ai_client()
        assert isinstance(client, ai_client.CodexCLIClient)

    def test_codex_takes_precedence_over_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        cfg, which, connected = _codex_selected()
        with cfg, which, connected:
            client = ai_client.get_ai_client()
        assert isinstance(client, ai_client.CodexCLIClient)

    def test_categorization_model_threads_to_codex_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        cfg, which, connected = _codex_selected(model="gpt-5.2")
        with cfg, which, connected:
            client = ai_client.get_ai_client()
        assert isinstance(client, ai_client.CodexCLIClient)
        assert client.model == "gpt-5.2"

    def test_openai_provider_returns_openai_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """categorization_provider=openai uses the API key path even when codex is signed in."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        cfg, which, connected = _codex_selected(provider="openai")
        with cfg, which, connected, patch("src.finance.openai_client.OpenAI"):
            client = ai_client.get_ai_client()
        assert isinstance(client, OpenAIClient)
        # Falls back to the shared default chat model when no override is set.
        assert client.model == ai_client.DEFAULT_OPENAI_CHAT_MODEL

    def test_categorization_model_threads_to_openai_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        cfg, which, connected = _codex_selected(provider="openai", model="gpt-5.6-luna")
        with cfg, which, connected, patch("src.finance.openai_client.OpenAI"):
            client = ai_client.get_ai_client()
        assert isinstance(client, OpenAIClient)
        assert client.model == "gpt-5.6-luna"

    def test_codex_selected_but_not_connected_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Per-feature routing is explicit: a codex pick that isn't signed in does
        NOT silently reroute to the OpenAI key path — it returns None."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        cfg, which, connected = _codex_selected(connected=False)
        with cfg, which, connected:
            assert ai_client.get_ai_client() is None

    def test_openai_provider_without_key_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        cfg, which, connected = _codex_selected(provider="openai", connected=False)
        with cfg, which, connected:
            assert ai_client.get_ai_client() is None

    def test_returns_none_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        cfg, which, connected = _codex_selected(connected=False, provider="disabled")
        with cfg, which, connected:
            assert ai_client.get_ai_client() is None


class _FakeRun:
    """Mimics `codex exec` by writing the final message to the `-o` file."""

    def __init__(self, output: str | None, returncode: int = 0, stderr: str = "") -> None:
        self.output = output
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[list[str]] = []
        self.schemas: list[dict[str, Any]] = []

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if "--output-schema" in args:
            # Read now — the temp dir is gone by the time the test asserts.
            self.schemas.append(json.loads(Path(args[args.index("--output-schema") + 1]).read_text()))
        if self.output is not None:
            out_path = Path(args[args.index("-o") + 1])
            out_path.write_text(self.output)
        return subprocess.CompletedProcess(args, self.returncode, stdout="", stderr=self.stderr)


class TestCodexCLIClient:
    def test_forced_tool_call_round_trip(self) -> None:
        fake_run = _FakeRun(output='{"category": "Groceries"}')
        with (
            patch("src.finance.ai_client.shutil.which", return_value="/usr/bin/codex"),
            patch("src.finance.ai_client.subprocess.run", side_effect=fake_run),
        ):
            completion = ai_client.CodexCLIClient().chat(
                MESSAGES, tools=CATEGORIZE_TOOLS, tool_choice=CATEGORIZE_TOOL_CHOICE
            )

        tool_call = completion.choices[0].message.tool_calls[0]
        assert tool_call.function.name == "categorize_transaction"
        assert json.loads(tool_call.function.arguments) == {"category": "Groceries"}

        args = fake_run.calls[0]
        assert args[1] == "exec"
        assert "--output-schema" in args
        schema = fake_run.schemas[0]
        assert schema["properties"]["category"]["enum"] == ["Groceries", "Miscellaneous"]
        assert schema["additionalProperties"] is False
        # Prompt is the flattened message contents, passed as the last arg.
        assert "Categorize this transaction." in args[-1]

    def test_plain_chat_returns_content(self) -> None:
        fake_run = _FakeRun(output="A short answer.")
        with (
            patch("src.finance.ai_client.shutil.which", return_value="/usr/bin/codex"),
            patch("src.finance.ai_client.subprocess.run", side_effect=fake_run),
        ):
            completion = ai_client.CodexCLIClient().chat(MESSAGES)
        assert completion.choices[0].message.content == "A short answer."
        assert completion.choices[0].message.tool_calls is None
        assert "--output-schema" not in fake_run.calls[0]

    def test_model_override_is_passed(self) -> None:
        fake_run = _FakeRun(output='{"category": "Groceries"}')
        with (
            patch("src.finance.ai_client.shutil.which", return_value="/usr/bin/codex"),
            patch("src.finance.ai_client.subprocess.run", side_effect=fake_run),
        ):
            ai_client.CodexCLIClient(model="gpt-5.2").chat(
                MESSAGES, tools=CATEGORIZE_TOOLS, tool_choice=CATEGORIZE_TOOL_CHOICE
            )
        args = fake_run.calls[0]
        assert args[args.index("-m") + 1] == "gpt-5.2"

    def test_reasoning_effort_is_passed_as_config_override(self) -> None:
        fake_run = _FakeRun(output='{"category": "Groceries"}')
        with (
            patch("src.finance.ai_client.shutil.which", return_value="/usr/bin/codex"),
            patch("src.finance.ai_client.subprocess.run", side_effect=fake_run),
        ):
            ai_client.CodexCLIClient(reasoning_effort="low").chat(
                MESSAGES, tools=CATEGORIZE_TOOLS, tool_choice=CATEGORIZE_TOOL_CHOICE
            )
        args = fake_run.calls[0]
        assert args[args.index("-c") + 1] == 'model_reasoning_effort="low"'

    def test_no_reasoning_effort_omits_config_override(self) -> None:
        fake_run = _FakeRun(output='{"category": "Groceries"}')
        with (
            patch("src.finance.ai_client.shutil.which", return_value="/usr/bin/codex"),
            patch("src.finance.ai_client.subprocess.run", side_effect=fake_run),
        ):
            ai_client.CodexCLIClient().chat(MESSAGES, tools=CATEGORIZE_TOOLS, tool_choice=CATEGORIZE_TOOL_CHOICE)
        assert "-c" not in fake_run.calls[0]

    def test_returns_none_when_cli_missing(self) -> None:
        with patch("src.finance.ai_client.shutil.which", return_value=None):
            assert ai_client.CodexCLIClient().chat(MESSAGES) is None

    def test_returns_none_on_nonzero_exit(self) -> None:
        fake_run = _FakeRun(output=None, returncode=1, stderr="boom")
        with (
            patch("src.finance.ai_client.shutil.which", return_value="/usr/bin/codex"),
            patch("src.finance.ai_client.subprocess.run", side_effect=fake_run),
        ):
            assert ai_client.CodexCLIClient().chat(MESSAGES) is None

    def test_returns_none_on_timeout(self) -> None:
        with (
            patch("src.finance.ai_client.shutil.which", return_value="/usr/bin/codex"),
            patch(
                "src.finance.ai_client.subprocess.run",
                side_effect=subprocess.TimeoutExpired("codex", 120),
            ),
        ):
            assert ai_client.CodexCLIClient().chat(MESSAGES) is None

    def test_returns_none_on_empty_output(self) -> None:
        fake_run = _FakeRun(output="")
        with (
            patch("src.finance.ai_client.shutil.which", return_value="/usr/bin/codex"),
            patch("src.finance.ai_client.subprocess.run", side_effect=fake_run),
        ):
            assert ai_client.CodexCLIClient().chat(MESSAGES) is None
