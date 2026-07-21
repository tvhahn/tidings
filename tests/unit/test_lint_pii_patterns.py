"""Unit tests for scripts/pii/lint_pii_patterns.py and scripts/pii/check_pii_gate_armed.sh.

The linter is a CLI under scripts/ (not an importable package), so it is loaded
by path via importlib — the same idiom as tests/unit/test_audit_script.py.

All pattern content here is synthetic (SECRETTOKEN123 style). The canary regex
source and any canary literal are ASSEMBLED AT RUNTIME by concatenation so this
file never carries at rest a string the real .pii-patterns alphabet would match —
otherwise the release audit of the tracked tree flags its own test suite. Do not
"simplify" the concatenations back into single literals.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_LINT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "pii" / "lint_pii_patterns.py"
_SHELL_PATH = Path(__file__).resolve().parents[2] / "scripts" / "pii" / "check_pii_gate_armed.sh"

_spec = importlib.util.spec_from_file_location("lint_pii_patterns", _LINT_PATH)
assert _spec is not None
assert _spec.loader is not None
lint = importlib.util.module_from_spec(_spec)
# Register before exec so any module-level namespace resolution works.
sys.modules["lint_pii_patterns"] = lint
_spec.loader.exec_module(lint)


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / ".pii-patterns"
    path.write_text(body, encoding="utf-8")
    return path


def _run(path: Path, *extra: str) -> int:
    return lint.main(["--patterns", str(path), *extra])


# ---------------------------------------------------------------------------
# Linter — happy path
# ---------------------------------------------------------------------------


def test_valid_file_exit_zero_with_count(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(tmp_path, "SECRETTOKEN123\nANOTHERTOKEN[0-9]+\nWIDGET-CODE-[A-Z]{3}\n")
    code = _run(path)
    out = capsys.readouterr().out
    assert code == 0
    assert "lint-pii-patterns: 3 live pattern(s) — ok" in out


def test_comments_and_blanks_ignored_in_count(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    body = "# normal comment\n## header\n#\n\n   \nSECRETTOKEN123\nWIDGETCODE456\n"
    path = _write(tmp_path, body)
    code = _run(path)
    out = capsys.readouterr().out
    assert code == 0
    assert "2 live pattern(s) — ok" in out


# ---------------------------------------------------------------------------
# Linter — failure modes (line numbers only, never pattern text)
# ---------------------------------------------------------------------------


def test_invalid_regex_exit_one_no_pattern_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = "SECRETTOKEN[123"  # unclosed character class → invalid regex
    path = _write(tmp_path, f"GOODTOKEN123\n{bad}\n")
    code = _run(path)
    out = capsys.readouterr().out
    assert code == 1
    assert "line 2" in out
    assert "SECRETTOKEN" not in out  # never echo the offending pattern's content
    assert bad not in out


def test_empty_matching_pattern_exit_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(tmp_path, "GOODTOKEN123\nx?\n")
    code = _run(path)
    out = capsys.readouterr().out
    assert code == 1
    assert "line 2" in out
    assert "empty string" in out


def test_duplicate_live_line_exit_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(tmp_path, "SECRETTOKEN123\nSECRETTOKEN123\n")
    code = _run(path)
    out = capsys.readouterr().out
    assert code == 1
    assert "line 2" in out
    assert "SECRETTOKEN" not in out


def test_comment_trap_hash_no_space_exit_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    trap = "#" + "369 STORECODE"  # a real pattern accidentally commented by a leading store-code '#'
    path = _write(tmp_path, f"GOODTOKEN123\n{trap}\n")
    code = _run(path)
    out = capsys.readouterr().out
    assert code == 1
    assert "line 2" in out
    assert "369" not in out
    assert "STORECODE" not in out


def test_real_comments_are_fine(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # "# text", "## header", and a bare "#" must all pass (not comment traps).
    path = _write(tmp_path, "# a real comment\n## a header\n#\nSECRETTOKEN123\n")
    code = _run(path)
    out = capsys.readouterr().out
    assert code == 0
    assert "1 live pattern(s) — ok" in out


def test_min_count_above_live_exit_one_shows_found_and_required(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, "SECRETTOKEN123\nWIDGETCODE456\n")
    code = _run(path, "--min-count", "5")
    out = capsys.readouterr().out
    assert code == 1
    assert "below the required minimum" in out
    assert "2" in out
    assert "5" in out


def test_missing_file_exit_three(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    code = lint.main(["--patterns", str(missing)])
    assert code == 3


# ---------------------------------------------------------------------------
# Shell self-test — scripts/pii/check_pii_gate_armed.sh (real audit, no mocking)
# ---------------------------------------------------------------------------

_HAVE_BASH = shutil.which("bash") is not None
_HAVE_GREP = shutil.which("grep") is not None
_shell_gate = pytest.mark.skipif(not (_HAVE_BASH and _HAVE_GREP), reason="requires bash and grep")


def _canary_regex_source() -> str:
    # Assemble the canary pattern source by concatenation — never a single literal.
    return "TIDINGS" + "[- ]?" + "PII" + "[- ]?" + "CANARY"


def _run_shell(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_SHELL_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


@_shell_gate
def test_shell_missing_patterns_skips_green(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-patterns"
    result = _run_shell("--patterns", str(missing))
    assert result.returncode == 0
    assert "self-test skipped" in result.stdout


@_shell_gate
def test_shell_with_canary_reports_armed(tmp_path: Path) -> None:
    patterns = tmp_path / "patterns"
    patterns.write_text(f"SECRETTOKEN[0-9]+\n{_canary_regex_source()}\n", encoding="utf-8")
    result = _run_shell("--patterns", str(patterns), "--min-count", "1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "armed" in result.stdout


@_shell_gate
def test_shell_without_canary_reports_self_test_failed(tmp_path: Path) -> None:
    patterns = tmp_path / "patterns"
    patterns.write_text("SECRETTOKEN[0-9]+\n", encoding="utf-8")
    result = _run_shell("--patterns", str(patterns), "--min-count", "1")
    assert result.returncode == 1
    assert "SELF-TEST FAILED" in result.stdout


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
