"""Generic AI-CLI provider transport shared across the AI feature modules.

Spawns headless AI CLIs (Claude Code, OpenAI Codex, Gemini) and provides the
openai-API-vs-CLI text-invocation and JSON-extraction plumbing that the daily
summary, statement-parser, and receipt-parser modules all depend on. Lives here
(not in the summary-provider module) so those consumers share one implementation
with no import cycle: the dependency is one-way — consumers import from
``ai_cli``, ``ai_cli`` imports from none of them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.finance.openai_client import OpenAIClient

logger = logging.getLogger(__name__)

# Default OpenAI chat model, shared across every feature that talks to the
# OpenAI API (categorization, daily summaries, insights, statement/receipt
# parsing). A per-feature `*_model` config key overrides it; `None` there means
# "use this default". Kept in one place so the literal never drifts between
# features. The subscription-backed CLI providers do not serve this model.
DEFAULT_OPENAI_CHAT_MODEL = "gpt-5.4-nano"

# Cross-module surface consumed by the summary-provider, statement-parser, and
# receipt-parser modules. The signed-in probes are underscore-prefixed but
# genuinely shared, so they belong on the export list.
__all__ = [
    "DEFAULT_OPENAI_CHAT_MODEL",
    "_codex_signed_in",
    "_gemini_signed_in",
    "extract_json",
    "invoke_text_provider",
    "run_cli_provider",
]


def _extract_codex_answer(stdout: str) -> str:
    """Return the final answer from ``codex exec`` stdout.

    Codex prints a header block, ``codex\\n<answer>\\n``, ``tokens used\\n<N>\\n``, then
    the answer again. Take everything after the last ``tokens used`` marker so the
    downstream parser sees only the clean answer.
    """
    pattern = re.compile(r"^tokens used\n[\d,]+\n", re.MULTILINE)
    matches = list(pattern.finditer(stdout))
    if matches:
        return stdout[matches[-1].end() :].strip()
    return stdout.strip()


async def run_cli_provider(
    provider_name: str,
    prompt: str,
    timeout: int = 180,
    model: str | None = None,
    image_paths: list[str] | None = None,
    reasoning_effort: str | None = None,
) -> str:
    """Spawn a CLI AI provider headlessly and return the answer text.

    Supported providers: ``claude_cli``, ``codex``. Raises ``RuntimeError`` on
    missing binary, non-zero exit with empty stdout, or timeout.

    ``model`` (``None`` = provider default) applies to ``claude_cli``
    (``--model``, falling back to ``"sonnet"``) and ``codex`` (``-m``, omitted
    entirely when unset). Gemini ignores it.

    ``reasoning_effort`` (``None`` = provider default, no flag emitted) applies
    to ``claude_cli`` (``--effort <level>``) and ``codex`` (``-c
    model_reasoning_effort="<level>"``). Gemini ignores it. The value is passed
    through verbatim — an unsupported level surfaces as a provider-side error.

    ``image_paths`` (receipt parsing, L6) attaches local image files to the
    request. Codex takes ``-i <path>`` per image; Claude Code reads files with
    its Read tool, so we point it at the path in the prompt *and* grant the Read
    tool (verified in Phase 0: ``claude -p`` refuses without ``--allowedTools
    Read``). The Gemini CLI has no image path yet, so it raises.
    """
    if provider_name == "claude_cli":
        claude_bin = shutil.which("claude")
        if claude_bin is None:
            raise RuntimeError("Claude Code not found in PATH")
        effective_prompt = prompt
        if image_paths:
            effective_prompt += "".join(
                f"\n\nThe receipt image is on disk at: {path} — read it." for path in image_paths
            )
        cli_args = [
            claude_bin,
            "-p",
            effective_prompt,
            "--output-format",
            "text",
            "--model",
            model or "sonnet",
            "--no-session-persistence",
        ]
        if reasoning_effort:
            cli_args += ["--effort", reasoning_effort]
        if image_paths:
            cli_args += ["--allowedTools", "Read"]
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        label = "Claude Code"
        extract: Callable[[str], str] = lambda s: s  # noqa: E731
    elif provider_name == "codex":
        codex_bin = shutil.which("codex")
        if codex_bin is None:
            raise RuntimeError("OpenAI Codex not found in PATH")
        image_args: list[str] = []
        for path in image_paths or []:
            image_args += ["-i", path]
        model_args = ["-m", model] if model else []
        # codex takes reasoning effort as a config override: `-c` plus the
        # assignment as a single argv element (verified with codex 0.144.5).
        effort_args = ["-c", f'model_reasoning_effort="{reasoning_effort}"'] if reasoning_effort else []
        cli_args = [
            codex_bin,
            "exec",
            "--skip-git-repo-check",
            "--color",
            "never",
            "-s",
            "read-only",
            *model_args,
            *effort_args,
            *image_args,
            prompt,
        ]
        env = dict(os.environ)
        label = "OpenAI Codex"
        extract = _extract_codex_answer
    elif provider_name == "gemini_cli":
        gemini_bin = shutil.which("gemini")
        if gemini_bin is None:
            raise RuntimeError("Google Gemini not found in PATH")
        if image_paths:
            raise RuntimeError(
                "The Gemini CLI can't read receipt images yet — pick OpenAI, Codex, or Claude for photo receipts."
            )
        cli_args = [gemini_bin, "-p", prompt]
        env = dict(os.environ)
        label = "Google Gemini"
        extract = lambda s: s.strip()  # noqa: E731
    else:
        raise RuntimeError(f"Unknown CLI provider: {provider_name}")

    logger.info("Spawning %s", label)
    process = await asyncio.create_subprocess_exec(
        *cli_args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError as e:
        process.kill()
        await process.wait()
        raise RuntimeError(f"{label} timed out after {timeout}s") from e

    full_text = stdout.decode() if stdout else ""
    stderr_text = stderr.decode() if stderr else ""
    if process.returncode != 0 and not full_text:
        err = stderr_text.strip() or f"{label} failed"
        raise RuntimeError(f"{label} error: {err[:200]}")

    if stderr_text:
        logger.debug("%s stderr: %s", label, stderr_text[:500])

    return extract(full_text)


def _codex_signed_in() -> bool:
    """Codex is usable when binary is on PATH and login credentials exist."""
    return bool(shutil.which("codex")) and (Path.home() / ".codex" / "auth.json").exists()


def _gemini_signed_in() -> bool:
    """Gemini is usable when binary is on PATH and either OAuth creds or an API key exist."""
    if not shutil.which("gemini"):
        return False
    oauth_creds = (Path.home() / ".gemini" / "oauth_creds.json").exists()
    return oauth_creds or bool(os.environ.get("GEMINI_API_KEY"))


def extract_json(raw: str, *, error_cls: type[Exception]) -> dict[str, Any]:
    """Pull the JSON object out of a model reply, tolerating fences and prose.

    Shared by the statement- and receipt-parser AI paths; ``error_cls`` selects
    the caller's exception type so each surfaces a single, consistent error.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise error_cls("The AI reply contained no JSON object")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise error_cls(f"The AI reply was not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise error_cls("The AI reply was not a JSON object")
    return data


async def invoke_text_provider(
    provider: str,
    prompt: str,
    openai_client: OpenAIClient | None,
    *,
    error_cls: type[Exception],
    timeout: int,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> str:
    """Run a text-only prompt through the chosen provider (openai API or CLI).

    Consolidates the statement- and receipt-parser transports: they differ only
    in the exception type raised (``error_cls``) and the CLI ``timeout``.
    ``model`` (``None`` = the feature's provider default) threads through to
    both paths — the openai call pins ``model or DEFAULT_OPENAI_CHAT_MODEL`` (the
    injected client defaults to an embedding model the chat endpoint rejects, so
    a concrete chat model is mandatory here), and the CLI path forwards ``model``
    to ``run_cli_provider``. ``reasoning_effort`` (``None`` = provider default)
    threads through the same way. CLI ``RuntimeError``s are re-raised as
    ``error_cls``.
    """
    if provider == "openai":
        if openai_client is None:
            raise error_cls("OpenAI is selected as the AI provider but no API key is configured")
        response = await asyncio.to_thread(
            openai_client.chat,
            [{"role": "user", "content": prompt}],
            model=model or DEFAULT_OPENAI_CHAT_MODEL,
            reasoning_effort=reasoning_effort,
        )
        if response is None:
            raise error_cls(f"The OpenAI request failed: {openai_client.last_error}")
        content = response.choices[0].message.content
        if not content:
            raise error_cls("The OpenAI reply was empty")
        return content

    try:
        return await run_cli_provider(provider, prompt, timeout=timeout, model=model, reasoning_effort=reasoning_effort)
    except RuntimeError as e:
        raise error_cls(str(e)) from e
