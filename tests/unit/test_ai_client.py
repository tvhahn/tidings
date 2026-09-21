"""Unit tests for the AI provider router (`src.finance.ai_client`)."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from src.finance import ai_client
from src.finance.ai_cli import DEFAULT_CATEGORIZATION_REASONING_EFFORT, DEFAULT_OPENAI_CHAT_MODEL
from src.finance.openai_client import OpenAIClient

# A model that is deliberately NOT the shared default, used to prove the
# "foreign model gets no tuned effort" rule.
FOREIGN_MODEL = "gpt-5.4-nano"

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


def _codex_selected(
    connected: bool = True,
    provider: str = "codex",
    model: str | None = None,
    reasoning_effort: str | None = None,
):
    """Patch context: categorization provider selection + codex availability + login state."""
    cfg: dict[str, object] = {"categorization_provider": provider}
    if model is not None:
        cfg["categorization_model"] = model
    if reasoning_effort is not None:
        cfg["categorization_reasoning_effort"] = reasoning_effort
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
        # Falls back to the shared default chat model when no override is set,
        # and with it the effort tuned for that model.
        assert client.model == ai_client.DEFAULT_OPENAI_CHAT_MODEL
        assert client.reasoning_effort == DEFAULT_CATEGORIZATION_REASONING_EFFORT

    def test_categorization_model_threads_to_openai_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        cfg, which, connected = _codex_selected(provider="openai", model=FOREIGN_MODEL)
        with cfg, which, connected, patch("src.finance.openai_client.OpenAI"):
            client = ai_client.get_ai_client()
        assert isinstance(client, OpenAIClient)
        assert client.model == FOREIGN_MODEL

    def test_foreign_model_gets_no_tuned_effort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The tuned effort is measured on the default model only — never sent with another."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        cfg, which, connected = _codex_selected(provider="openai", model=FOREIGN_MODEL)
        with cfg, which, connected, patch("src.finance.openai_client.OpenAI"):
            client = ai_client.get_ai_client()
        assert isinstance(client, OpenAIClient)
        assert client.reasoning_effort is None

    def test_default_model_picked_explicitly_still_gets_tuned_effort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        cfg, which, connected = _codex_selected(provider="openai", model=DEFAULT_OPENAI_CHAT_MODEL)
        with cfg, which, connected, patch("src.finance.openai_client.OpenAI"):
            client = ai_client.get_ai_client()
        assert isinstance(client, OpenAIClient)
        assert client.model == DEFAULT_OPENAI_CHAT_MODEL
        assert client.reasoning_effort == DEFAULT_CATEGORIZATION_REASONING_EFFORT

    def test_explicit_reasoning_effort_threads_to_openai_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        cfg, which, connected = _codex_selected(provider="openai", model=FOREIGN_MODEL, reasoning_effort="high")
        with cfg, which, connected, patch("src.finance.openai_client.OpenAI"):
            client = ai_client.get_ai_client()
        assert isinstance(client, OpenAIClient)
        assert client.model == FOREIGN_MODEL
        assert client.reasoning_effort == "high"

    def test_codex_client_gets_raw_config_effort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The codex branch is untouched by the API-tuned default — it has its own."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        cfg, which, connected = _codex_selected(reasoning_effort="medium")
        with cfg, which, connected:
            client = ai_client.get_ai_client()
        assert isinstance(client, ai_client.CodexCLIClient)
        assert client.reasoning_effort == "medium"

    def test_codex_client_gets_no_effort_when_config_omits_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        cfg, which, connected = _codex_selected()
        with cfg, which, connected:
            client = ai_client.get_ai_client()
        assert isinstance(client, ai_client.CodexCLIClient)
        assert client.model is None
        assert client.reasoning_effort is None

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


class TestCoerceReasoningEffort:
    """Operator-supplied effort strings are normalized, never trusted blindly."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (" LOW ", "low"),
            ("low", "low"),
            ("Medium", "medium"),
            ("", None),
            ("   ", None),
            (None, None),
        ],
    )
    def test_normalization(self, raw: str | None, expected: str | None) -> None:
        assert ai_client.coerce_reasoning_effort(raw) == expected

    def test_unknown_value_warns_and_returns_none(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="src.finance.ai_client"):
            assert ai_client.coerce_reasoning_effort("turbo") is None
        assert "turbo" in caplog.text
        assert any(record.levelno == logging.WARNING for record in caplog.records)

    def test_every_accepted_spelling_round_trips(self) -> None:
        for value in ai_client.OPENAI_REASONING_EFFORTS:
            assert ai_client.coerce_reasoning_effort(value.upper()) == value


class TestResolveOpenAICategorizationSettings:
    """The one resolver shared by the config path and the Lambda."""

    @pytest.mark.parametrize(
        ("model", "effort", "expected"),
        [
            # Nothing chosen: shared default model + the effort tuned for it.
            (None, None, (DEFAULT_OPENAI_CHAT_MODEL, DEFAULT_CATEGORIZATION_REASONING_EFFORT)),
            # The default model chosen explicitly behaves identically.
            (
                DEFAULT_OPENAI_CHAT_MODEL,
                None,
                (DEFAULT_OPENAI_CHAT_MODEL, DEFAULT_CATEGORIZATION_REASONING_EFFORT),
            ),
            # A foreign model must never inherit the tuned effort.
            (FOREIGN_MODEL, None, (FOREIGN_MODEL, None)),
            # Explicit effort always wins, with or without a model override.
            (None, "high", (DEFAULT_OPENAI_CHAT_MODEL, "high")),
            (FOREIGN_MODEL, "high", (FOREIGN_MODEL, "high")),
            # Empty strings mean "unset", not "a value".
            ("", None, (DEFAULT_OPENAI_CHAT_MODEL, DEFAULT_CATEGORIZATION_REASONING_EFFORT)),
            (None, "", (DEFAULT_OPENAI_CHAT_MODEL, DEFAULT_CATEGORIZATION_REASONING_EFFORT)),
            ("", "", (DEFAULT_OPENAI_CHAT_MODEL, DEFAULT_CATEGORIZATION_REASONING_EFFORT)),
            (FOREIGN_MODEL, "", (FOREIGN_MODEL, None)),
        ],
    )
    def test_resolution_table(self, model: str | None, effort: str | None, expected: tuple[str, str | None]) -> None:
        assert ai_client.resolve_openai_categorization_settings(model, effort) == expected

    def test_default_effort_is_an_accepted_spelling(self) -> None:
        """Guards the tuned constant against a typo the API would reject."""
        assert DEFAULT_CATEGORIZATION_REASONING_EFFORT in ai_client.OPENAI_REASONING_EFFORTS
