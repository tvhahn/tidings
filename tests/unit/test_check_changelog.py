"""Unit tests for scripts/checks/check_changelog.py — the changelog format lint.

The script is a stdlib-only CLI under scripts/ (not an importable package), so
it is loaded by path via importlib — the same idiom as
``tests/unit/test_check_canon_links.py`` and ``test_lint_pii_patterns.py``.

Every case here lints an INLINE FIXTURE STRING via ``check(text)``, never the
live CHANGELOG.md: the real file is restructured out-of-band and its content is
not this suite's contract. ``main()`` is exercised once against a tmp-path file
to cover the CLI/exit-code seam.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "checks" / "check_changelog.py"
_spec = importlib.util.spec_from_file_location("check_changelog", _SCRIPT)
assert _spec is not None
assert _spec.loader is not None
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)

check = cc.check


# A minimal well-formed changelog. Em dash (U+2014) in the version headers.
GOOD = """# Changelog

All notable changes to this project will be documented in this file.

## Versioning

This project adheres to Semantic Versioning.

## [Unreleased]

## [0.2.0] — 2026-07-21

### Added

- A second thing.

## [0.1.0] — 2026-06-01

### Security

- Initial hardening.
"""


def _messages(text: str) -> list[str]:
    return [msg for _, msg in check(text)]


def _lines(text: str) -> list[int]:
    return [ln for ln, _ in check(text)]


# --------------------------------------------------------------------------- ok


def test_clean_file_passes() -> None:
    assert check(GOOD) == []


# ----------------------------------------------------------------- check 1: grammar


def test_bad_version_header_flagged() -> None:
    # Hyphen instead of the required em dash.
    bad = GOOD.replace("## [0.2.0] — 2026-07-21", "## [0.2.0] - 2026-07-21")
    msgs = _messages(bad)
    assert any("malformed entry header" in m for m in msgs)


def test_non_padded_or_invalid_date_flagged() -> None:
    bad = GOOD.replace("## [0.2.0] — 2026-07-21", "## [0.2.0] — 2026-13-40")
    assert any("invalid calendar date" in m for m in _messages(bad))


def test_missing_unreleased_flagged() -> None:
    bad = GOOD.replace("## [Unreleased]\n\n", "")
    assert any("missing '## [Unreleased]'" in m for m in _messages(bad))


def test_duplicate_unreleased_flagged() -> None:
    bad = GOOD.replace("## [Unreleased]\n", "## [Unreleased]\n\n## [Unreleased]\n", 1)
    assert any("duplicate '## [Unreleased]'" in m for m in _messages(bad))


def test_unreleased_after_version_entry_flagged() -> None:
    bad = """# Changelog

## [0.2.0] — 2026-07-21

### Added

- Thing.

## [Unreleased]
"""
    assert any("must appear before all version entries" in m for m in _messages(bad))


def test_versions_out_of_descending_order_flagged() -> None:
    bad = GOOD.replace("## [0.2.0] — 2026-07-21", "## [0.0.9] — 2026-07-21")
    assert any("descending semver" in m for m in _messages(bad))


# ----------------------------------------------------------------- check 2: subsections


def test_unknown_subsection_flagged() -> None:
    bad = GOOD.replace("### Added", "### Enhancements")
    assert any("unknown subsection '### Enhancements'" in m for m in _messages(bad))


# ----------------------------------------------------------------- check 3: dangling refs


def test_sha_with_digit_flagged() -> None:
    bad = GOOD.replace("- A second thing.", "- A second thing (a1b2c3d).")
    assert any("commit-hash-like ref 'a1b2c3d'" in m for m in _messages(bad))


def test_all_letter_hex_word_not_flagged() -> None:
    # "defaced" and "facade" are all-[a-f] English words with no digit — excluded.
    ok = GOOD.replace("- A second thing.", "- Restored the defaced facade of the export.")
    assert check(ok) == []


def test_bare_pr_ref_flagged() -> None:
    bad = GOOD.replace("- A second thing.", "- A second thing (see #123).")
    msgs = _messages(bad)
    assert any("PR/issue ref '#123'" in m for m in msgs)


def test_store_code_hash_in_body_is_flagged_accepted_behavior() -> None:
    # The regex flags any whitespace-preceded `#NNN`, so a merchant store code
    # like "THRIFTMART #0410" IS flagged. That is accepted: raw store codes do
    # not belong in a changelog body. This test documents the behavior.
    bad = GOOD.replace("- A second thing.", "- Parser now handles THRIFTMART #0410.")
    assert any("PR/issue ref '#0410'" in m for m in _messages(bad))


def test_refs_in_top_matter_not_scanned() -> None:
    # A `#123` above the first `## [` header (top matter) is not a body → ignored.
    ok = GOOD.replace(
        "All notable changes to this project will be documented in this file.",
        "All notable changes (tracking issue #123, sha deadbeef1) live here.",
    )
    assert check(ok) == []


# ----------------------------------------------------------------- check 4: extraction


def test_trailing_section_sweep_detected() -> None:
    # A single version entry followed by a stray non-bracket `## ` heading: the
    # awk slice for 0.1.0 sweeps the `## Versioning` heading into the notes.
    bad = """# Changelog

## [Unreleased]

## [0.1.0] — 2026-06-01

### Added

- Initial.

## Versioning

Trailing prose that should not be release notes.
"""
    assert any("sweeps in a trailing section" in m for m in _messages(bad))


def test_empty_extraction_detected() -> None:
    # Newest entry has no body before EOF → extraction is blank.
    bad = """# Changelog

## [Unreleased]

## [0.2.0] — 2026-07-21
"""
    assert any("extraction for the newest entry" in m and "is empty" in m for m in _messages(bad))


# --------------------------------------------------------------------------- CLI


def test_main_clean_returns_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(GOOD, encoding="utf-8")
    code = cc.main([str(path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "ok" in out


def test_main_findings_return_one_and_print_path_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(GOOD.replace("### Added", "### Enhancements"), encoding="utf-8")
    code = cc.main([str(path)])
    out = capsys.readouterr().out
    assert code == 1
    assert f"{path}:" in out  # `<path>:<line>: <message>` format
    assert "finding(s)" in out


def test_main_missing_file_returns_two(tmp_path: Path) -> None:
    assert cc.main([str(tmp_path / "nope.md")]) == 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
