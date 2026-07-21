"""Unit tests for scripts/checks/check_canon_links.py — the canon link/intent checker.

The script is a stdlib-only CLI under scripts/, not an importable package
module, so it is loaded by path via importlib (same pattern as
``tests/unit/test_audit_script.py``). Rather than shelling out, each test
builds a synthetic canon tree in ``tmp_path`` and calls ``check(root)`` /
``skill_descriptions(root)`` directly, asserting on error-message substrings
and specific counts.

``make_repo`` returns a minimal *clean* tree (a root CLAUDE.md with its
AGENTS.md symlink, plus a benign docs/ page); individual tests mutate it to
introduce exactly one class of violation.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "checks" / "check_canon_links.py"
_spec = importlib.util.spec_from_file_location("check_canon_links", _SCRIPT)
assert _spec is not None
assert _spec.loader is not None
canon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(canon)

check = canon.check
skill_descriptions = canon.skill_descriptions


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def make_repo(tmp_path: Path) -> Path:
    """Minimal clean canon tree: root CLAUDE.md + AGENTS.md symlink + a docs page."""
    root = tmp_path / "repo"
    _write(root / "CLAUDE.md", "# Repo\n\nThe parser returns None.\n")
    os.symlink("CLAUDE.md", root / "AGENTS.md")
    _write(root / "docs" / "guide.md", "# Guide\n\nAll good here.\n")
    return root


def _add_skill(root: Path, name: str, body: str) -> Path:
    """Create .claude/skills/<name>/SKILL.md with the given frontmatter/body."""
    path = root / ".claude" / "skills" / name / "SKILL.md"
    _write(path, body)
    return path


# --------------------------------------------------------------------------
# Rule 1: relative markdown links must resolve on disk.
# --------------------------------------------------------------------------


def test_broken_markdown_link(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    _write(root / "docs" / "guide.md", "# Guide\n\nSee [the missing page](nope.md).\n")

    errors = check(root)
    assert len(errors) == 1, errors
    assert "broken link" in errors[0]


# --------------------------------------------------------------------------
# Rule 3: backtick `.md` path spans must resolve.
# --------------------------------------------------------------------------


def test_backtick_md_path_broken(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    _write(root / "docs" / "guide.md", "# Guide\n\nEdit `docs/nope.md` for details.\n")

    errors = check(root)
    assert len(errors) == 1, errors
    assert "broken path" in errors[0]


def test_backtick_md_path_resolving_is_clean(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    _write(root / "docs" / "real.md", "# Real\n")
    _write(root / "docs" / "guide.md", "# Guide\n\nEdit `docs/real.md` for details.\n")

    assert check(root) == []


# --------------------------------------------------------------------------
# Rule 2: references into git-excluded docs/specs/ need a "local-only" marker.
# --------------------------------------------------------------------------


def test_specs_link_without_marker_errors(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    _write(
        root / "docs" / "guide.md",
        "# Guide\n\nSee [the spec](docs/specs/foo/README.md).\n",
    )

    errors = check(root)
    assert len(errors) == 1, errors
    assert "local-only" in errors[0]
    assert "docs/specs/" in errors[0]


def test_specs_link_with_marker_is_clean(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    _write(
        root / "docs" / "guide.md",
        "# Guide\n\nSee [the spec](docs/specs/foo/README.md) (local-only).\n",
    )

    assert check(root) == []


# --------------------------------------------------------------------------
# Rule 2 (bare-dir case): backtick `docs/specs/` directory spans.
# --------------------------------------------------------------------------


def test_bare_specs_span_without_marker_errors(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    _write(root / "docs" / "guide.md", "# Guide\n\nSpecs live under `docs/specs/`.\n")

    errors = check(root)
    assert len(errors) == 1, errors
    assert "bare reference" in errors[0]


def test_bare_specs_span_with_marker_is_clean(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    _write(
        root / "docs" / "guide.md",
        "# Guide\n\nSpecs live under `docs/specs/` (local-only).\n",
    )

    assert check(root) == []


def test_bare_specs_span_with_placeholder_is_skipped(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    _write(
        root / "docs" / "guide.md",
        "# Guide\n\nDated folders `docs/specs/YYYY-MM-DD-<name>/` hold specs.\n",
    )

    assert check(root) == []


def test_specs_public_span_is_clean(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    _write(
        root / "docs" / "guide.md",
        "# Guide\n\nPublished assets live under `docs/specs-public/2026-01-01-foo/`.\n",
    )

    assert check(root) == []


# --------------------------------------------------------------------------
# Rule 4: every CLAUDE.md needs a sibling AGENTS.md symlink pointing at it.
# --------------------------------------------------------------------------


def test_nested_claude_without_agents_errors(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    _write(root / "src" / "CLAUDE.md", "# Src\n")

    errors = check(root)
    assert len(errors) == 1, errors
    assert "missing sibling AGENTS.md" in errors[0]


def test_nested_claude_with_correct_symlink_is_clean(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    _write(root / "src" / "CLAUDE.md", "# Src\n")
    os.symlink("CLAUDE.md", root / "src" / "AGENTS.md")

    assert check(root) == []


def test_nested_claude_with_wrong_symlink_target_errors(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    _write(root / "src" / "CLAUDE.md", "# Src\n")
    # Target must exist, else AGENTS.md.exists() is False (broken-link) and the
    # check reports "missing sibling" instead of the wrong-target branch.
    _write(root / "src" / "OTHER.md", "# Other\n")
    os.symlink("OTHER.md", root / "src" / "AGENTS.md")

    errors = check(root)
    assert len(errors) == 1, errors
    assert "does not point at CLAUDE.md" in errors[0]


# --------------------------------------------------------------------------
# Rule 5: intent phrasing does not belong in canon.
# --------------------------------------------------------------------------


def test_intent_phrasing_roadmap_errors(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    _write(root / "docs" / "guide.md", "# Guide\n\nThis feature is on the roadmap.\n")

    errors = check(root)
    assert len(errors) == 1, errors
    assert "intent phrasing" in errors[0]


def test_intent_phrasing_with_ok_marker_is_clean(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    _write(
        root / "docs" / "guide.md",
        "# Guide\n\nThis feature is on the roadmap. <!-- canon: intent-ok -->\n",
    )

    assert check(root) == []


def test_intent_phrasing_future_heading_errors(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    _write(root / "docs" / "guide.md", "# Guide\n\n## Future automation\n")

    errors = check(root)
    assert len(errors) == 1, errors
    assert "intent phrasing" in errors[0]


def test_intent_phrasing_not_yet_shipped_errors(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    _write(root / "docs" / "guide.md", "# Guide\n\nThat path is not yet shipped.\n")

    errors = check(root)
    assert len(errors) == 1, errors
    assert "intent phrasing" in errors[0]


def test_benign_prose_is_clean(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    _write(root / "docs" / "guide.md", "# Guide\n\nThe parser returns None.\n")

    assert check(root) == []


# --------------------------------------------------------------------------
# Rule 6: skill descriptions cap at 60 words.
# --------------------------------------------------------------------------


def test_skill_description_over_limit_errors(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    desc = " ".join(f"w{i}" for i in range(61))  # 61 words
    _add_skill(root, "foo", f"---\ndescription: {desc}\n---\n\nBody.\n")

    errors = check(root)
    assert len(errors) == 1, errors
    assert "61 words" in errors[0]


def test_skill_description_at_limit_is_clean(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    desc = " ".join(f"w{i}" for i in range(60))  # 60 words
    _add_skill(root, "foo", f"---\ndescription: {desc}\n---\n\nBody.\n")

    assert check(root) == []


def test_skill_description_folded_counts_across_lines(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    # A folded (`>-`) description spread over three indented lines: the word
    # count must sum across the continuation lines, not just the first.
    path = _add_skill(
        root,
        "foo",
        "---\ndescription: >-\n  alpha beta gamma\n  delta epsilon zeta\n  eta theta iota\n---\n\nBody.\n",
    )

    descriptions = {p: (words, text) for p, words, text in skill_descriptions(root)}
    words, text = descriptions[path]
    assert words == 9, text
    assert ">-" not in text
    assert text == "alpha beta gamma delta epsilon zeta eta theta iota"


# --------------------------------------------------------------------------
# Rule 7: fenced directory trees in CLAUDE.md restate ls-discoverable structure.
# --------------------------------------------------------------------------


def test_fenced_tree_in_claude_md_errors(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    _write(
        root / "CLAUDE.md",
        "# Repo\n\n## File layout\n\n```\n"
        "src/pages/       route components\n"
        "src/hooks/       React Query hooks\n"
        "src/stores/      zustand stores\n"
        "```\n",
    )

    errors = check(root)
    assert len(errors) == 1, errors
    assert "fenced directory tree" in errors[0]


def test_fenced_tree_with_ok_marker_is_clean(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    _write(
        root / "CLAUDE.md",
        "# Repo\n\n<!-- canon: tree-ok -->\n```\n"
        "src/pages/       route components\n"
        "src/hooks/       React Query hooks\n"
        "src/stores/      zustand stores\n"
        "```\n",
    )

    assert check(root) == []


def test_fenced_shell_commands_is_clean(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    # Commands have slash tokens (`tests/`) but single-space separation, so the
    # tree regex never matches — a shell block is not a directory tree.
    _write(
        root / "CLAUDE.md",
        '# Repo\n\n```\nuv sync\nmake dev\nuv run pytest tests/ -m "not integration"\n```\n',
    )

    assert check(root) == []


def test_fenced_tree_below_threshold_is_clean(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    # Two tree-like lines is under TREE_LINE_THRESHOLD (3) — boundary stays clean.
    _write(
        root / "CLAUDE.md",
        "# Repo\n\n```\nsrc/pages/       route components\nsrc/hooks/       React Query hooks\n```\n",
    )

    assert check(root) == []


# --------------------------------------------------------------------------
# docs-site/CLAUDE.md is special-cased into the canon set despite docs-site
# being in EXCLUDED_PARTS — the rules still apply to it.
# --------------------------------------------------------------------------


def test_docs_site_claude_without_agents_errors(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    _write(root / "docs-site" / "CLAUDE.md", "# Docs site\n")

    errors = check(root)
    assert len(errors) == 1, errors
    assert "missing sibling AGENTS.md" in errors[0]


def test_docs_site_claude_with_symlink_is_clean(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    _write(root / "docs-site" / "CLAUDE.md", "# Docs site\n")
    os.symlink("CLAUDE.md", root / "docs-site" / "AGENTS.md")

    assert check(root) == []


# --------------------------------------------------------------------------
# Rule 8: a fully-clean synthetic repo has no violations.
# --------------------------------------------------------------------------


def test_clean_repo_has_no_errors(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    assert check(root) == []
