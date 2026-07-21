"""Provider router for AI chat completions used by background tasks.

Categorization (and future agents like journal/insights summaries) call
`get_ai_client()` and treat the result as an `OpenAIClient`-shaped object.
The router prefers the Codex CLI when the user selected the codex provider
and is signed in with ChatGPT (`codex login --device-auth` via Settings),
falls back to the `OPENAI_API_KEY` env path, and returns `None` if neither
is configured — in which case the categorizer defaults to "Miscellaneous".

The codex path shells out to `codex exec` instead of speaking HTTP: the
subscription backend only serves the Responses API with CLI-specific
headers, so the official CLI is the stable client for it. Structured output
comes from `--output-schema`, derived from the forced tool's parameters, and
is wrapped in a completions-shaped shim so callers like
`categorizer.extract_function_call_args()` work unchanged.

Embeddings are *not* routed here — they stay on the env-key path in
`src/api/dependencies.py` because the codex backend does not serve
`text-embedding-3-small`.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol

from src.finance import chatgpt_oauth
from src.finance.ai_cli import DEFAULT_OPENAI_CHAT_MODEL
from src.finance.app_config import get_config
from src.finance.openai_client import OpenAIClient

logger = logging.getLogger(__name__)

_CODEX_TIMEOUT_SECONDS = 120


class AIClientError(Exception):
    """A provider-call failure carrying a classified ``reason``.

    Lets `chat()` implementations that don't raise OpenAI SDK exceptions
    (e.g. the Codex subprocess path) still hand callers a specific audit
    reason via ``last_error``. The categorizer reads ``reason`` directly.
    """

    def __init__(self, reason: str, message: str = "") -> None:
        super().__init__(message or reason)
        self.reason = reason


class AIProviderClient(Protocol):
    """Structural type matching `OpenAIClient.chat()`."""

    # Set to the exception from the most recent failed chat(), else None.
    # chat() returns None on failure (callers stay crash-free); this exposes
    # *why* so the categorizer can record a precise audit reason.
    last_error: Exception | None

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> Any: ...


class CodexCLIClient:
    """Runs `codex exec` headlessly, billing against the ChatGPT subscription.

    `model=None` uses the CLI's default model — the subscription backend only
    serves codex-family models (`gpt-5.4-nano` is not available on this path),
    and which ones varies by plan, so the CLI default is the safe choice.
    """

    def __init__(
        self,
        model: str | None = None,
        timeout: int = _CODEX_TIMEOUT_SECONDS,
        reasoning_effort: str | None = None,
    ) -> None:
        self.model = model
        self.timeout = timeout
        self.reasoning_effort = reasoning_effort
        self.last_error: Exception | None = None

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> Any:
        self.last_error = None
        codex_bin = shutil.which("codex")
        if codex_bin is None:
            logger.warning("OpenAI Codex CLI not found in PATH; categorization will fall back")
            self.last_error = AIClientError("codex_error", "codex CLI not found in PATH")
            return None

        forced = _forced_tool(tools, tool_choice)
        prompt = _render_prompt(messages)
        try:
            with tempfile.TemporaryDirectory(prefix="codex-chat-") as tmp:
                out_path = Path(tmp) / "last_message.txt"
                args = [
                    codex_bin,
                    "exec",
                    "--skip-git-repo-check",
                    "--ephemeral",
                    "-s",
                    "read-only",
                    "--color",
                    "never",
                    "-o",
                    str(out_path),
                ]
                if forced is not None:
                    schema_path = Path(tmp) / "schema.json"
                    schema_path.write_text(json.dumps(_strict_schema(forced["parameters"])))
                    args += ["--output-schema", str(schema_path)]
                if self.model:
                    args += ["-m", self.model]
                if self.reasoning_effort:
                    # codex config override; assignment is one argv element.
                    args += ["-c", f'model_reasoning_effort="{self.reasoning_effort}"']
                args.append(prompt)

                proc = subprocess.run(  # noqa: S603 — list-form argv, no shell; codex_bin via shutil.which; prompt is a single positional arg
                    args,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    check=False,
                )
                if proc.returncode != 0:
                    stderr_tail = (proc.stderr or "").strip()[-300:]
                    logger.error("codex exec failed (exit %d): %s", proc.returncode, stderr_tail)
                    self.last_error = AIClientError("codex_error", f"codex exec exit {proc.returncode}: {stderr_tail}")
                    return None
                text = out_path.read_text().strip() if out_path.exists() else ""
        except subprocess.TimeoutExpired as e:
            logger.exception("codex exec timed out after %ds", self.timeout)
            self.last_error = AIClientError("codex_timeout", f"codex exec timed out after {self.timeout}s")
            self.last_error.__cause__ = e
            return None
        except Exception as e:
            logger.exception("codex exec call failed")
            self.last_error = AIClientError("codex_error", "codex exec call failed")
            self.last_error.__cause__ = e
            return None

        if not text:
            logger.error("codex exec produced no final message")
            self.last_error = AIClientError("codex_error", "codex exec produced no final message")
            return None
        if forced is not None:
            return _tool_call_completion(forced["name"], text)
        return _content_completion(text)


def _render_prompt(messages: list[dict[str, Any]]) -> str:
    """Flatten chat messages into a single codex exec prompt."""
    parts = [str(m.get("content", "")) for m in messages if m.get("content")]
    return "\n\n".join(parts)


def _forced_tool(
    tools: list[dict[str, Any]] | None,
    tool_choice: str | dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Resolve the tool the caller forced, as `{name, parameters}`."""
    if not tools:
        return None
    wanted: str | None = None
    if isinstance(tool_choice, dict):
        wanted = tool_choice.get("function", {}).get("name")
    for tool in tools:
        function = tool.get("function", {})
        if wanted is None or function.get("name") == wanted:
            return {"name": function.get("name"), "parameters": function.get("parameters", {})}
    return None


def _strict_schema(parameters: dict[str, Any]) -> dict[str, Any]:
    """Make the tool parameters acceptable to codex's strict output schema."""
    schema = dict(parameters)
    schema.setdefault("additionalProperties", False)
    return schema


def _tool_call_completion(tool_name: str | None, arguments_json: str) -> Any:
    """Wrap codex's schema-constrained output as a chat.completions tool call."""
    tool_call = SimpleNamespace(function=SimpleNamespace(name=tool_name, arguments=arguments_json))
    message = SimpleNamespace(content=None, tool_calls=[tool_call])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _content_completion(text: str) -> Any:
    message = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def get_ai_client() -> AIProviderClient | None:
    """Resolve the active AI provider for categorization chat completions.

    Routes on the ``categorization_provider`` config key (and its optional
    ``categorization_model``):

    - ``"codex"`` → Codex CLI, but only when the binary is present AND the user
      is signed in (a codex login used solely for summaries must not silently
      reroute categorization).
    - ``"openai"`` → the OPENAI_API_KEY path, provided a key is configured.
    - ``"disabled"`` (or an unavailable provider) → ``None``; the categorizer
      then defaults to "Miscellaneous".
    """
    config = get_config()
    provider = config.get("categorization_provider", "disabled")
    model = config.get("categorization_model")
    reasoning_effort = config.get("categorization_reasoning_effort")
    if provider == "codex" and shutil.which("codex") and chatgpt_oauth.is_connected():
        return CodexCLIClient(model=model, reasoning_effort=reasoning_effort)
    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key:
            return OpenAIClient(
                model=model or DEFAULT_OPENAI_CHAT_MODEL,
                api_key=api_key,
                reasoning_effort=reasoning_effort,
            )
    return None
