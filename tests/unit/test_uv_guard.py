"""Subprocess-driven tests for the ``uv-guard`` Claude Code hook.

Covers ``.claude/hooks/uv-guard.sh`` — a PreToolUse Bash guard that blocks
bare ``python`` / ``python3`` / ``pip`` / ``pip3`` command words (they hit the
system interpreter, which lacks the project's deps) while letting anything
routed through ``uv`` / ``uvx`` — and the words as plain arguments — pass.

Each test feeds the hook a stdin JSON fixture and asserts only the exit code:
2 blocks the call (stderr shown to the model), 0 allows it. Skipped cleanly
when ``jq`` is unavailable (the guard shells out to it, like the PII guard).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UV_GUARD = REPO_ROOT / ".claude" / "hooks" / "uv-guard.sh"

requires_jq = pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required by uv-guard.sh")


def _run_uv_guard(payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(UV_GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )


def _bash(command: str) -> dict[str, object]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


# --------------------------------------------------------------------------
# Blocked — bare interpreter as a command word
# --------------------------------------------------------------------------


@requires_jq
@pytest.mark.parametrize(
    "command",
    [
        "python script.py",
        "python3 -m pytest",
        "pip install x",
        "cd foo && python x.py",
        "echo hi | python3 -",
    ],
)
def test_uv_guard_blocks_bare_interpreter(command: str) -> None:
    result = _run_uv_guard(_bash(command))
    assert result.returncode == 2, result.stderr + result.stdout
    assert "uv-guard" in result.stderr


# --------------------------------------------------------------------------
# Allowed — uv-routed, path-qualified, or the words as arguments
# --------------------------------------------------------------------------


@requires_jq
@pytest.mark.parametrize(
    "command",
    [
        "uv run python script.py",
        "uv run pytest tests/",
        "uvx ruff",
        "uv pip list",
        ".venv/bin/python x.py",
        "command -v python3",
        "which python",
        'git commit -m "python fix"',
    ],
)
def test_uv_guard_allows_non_bare_invocations(command: str) -> None:
    result = _run_uv_guard(_bash(command))
    assert result.returncode == 0, result.stderr + result.stdout


@requires_jq
def test_uv_guard_ignores_non_bash_tool() -> None:
    payload = {"tool_name": "Edit", "tool_input": {"file_path": "python.py"}}
    result = _run_uv_guard(payload)
    assert result.returncode == 0, result.stderr + result.stdout


@requires_jq
def test_uv_guard_ignores_empty_command() -> None:
    result = _run_uv_guard(_bash(""))
    assert result.returncode == 0, result.stderr + result.stdout
