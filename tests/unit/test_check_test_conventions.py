"""Unit tests for scripts/checks/check_test_conventions.py (the ad-hoc-TestClient ratchet).

Imports the stdlib script directly (same pattern as test_check_canon_links.py)
and drives ``check(root)`` against synthetic trees under ``tmp_path``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "check_test_conventions", REPO_ROOT / "scripts" / "checks" / "check_test_conventions.py"
)
assert _SPEC is not None
assert _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)

check = _MOD.check

# Built by concatenation so this test file itself contains zero literal
# occurrences of the pattern the ratchet counts.
ADHOC_LINE = "client = Test" + "Client(app)\n"


def make_repo(tmp_path: Path) -> Path:
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    (tmp_path / "tests" / "conftest.py").write_text(ADHOC_LINE)
    return tmp_path


def test_clean_tree_passes(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    (root / "tests" / "unit" / "test_new.py").write_text("def test_ok(api_client): ...\n")
    assert check(root) == []


def test_conftest_is_exempt(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    (root / "tests" / "unit" / "conftest.py").write_text(ADHOC_LINE)
    assert check(root) == []


def test_new_adhoc_usage_fails(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    (root / "tests" / "unit" / "test_new.py").write_text(ADHOC_LINE)
    errors = check(root)
    assert len(errors) == 1
    assert "test_new.py" in errors[0]
    assert "api_client" in errors[0]


def test_pinned_file_at_baseline_passes(tmp_path: Path, monkeypatch) -> None:
    # Synthetic pin: the live BASELINE is empty (migration finished 2026-07-17),
    # so the pin mechanics are exercised against an injected entry.
    root = make_repo(tmp_path)
    rel, pin = "tests/unit/test_legacy_sample.py", 3
    monkeypatch.setattr(_MOD, "BASELINE", {rel: pin})
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(ADHOC_LINE * pin)
    assert check(root) == []


def test_pinned_file_over_baseline_fails(tmp_path: Path, monkeypatch) -> None:
    root = make_repo(tmp_path)
    rel, pin = "tests/unit/test_legacy_sample.py", 3
    monkeypatch.setattr(_MOD, "BASELINE", {rel: pin})
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(ADHOC_LINE * (pin + 1))
    errors = check(root)
    assert len(errors) == 1
    assert f"pinned at {pin}" in errors[0]


def test_live_repo_is_clean() -> None:
    """The real tree must satisfy its own ratchet."""
    assert check(REPO_ROOT) == []
