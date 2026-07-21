"""Subprocess-driven tests for the repo's git / Claude Code hooks.

Covers two hooks:
  * ``.githooks/pre-push`` — maintainer-gated remote allowlist + archive-audit
    of HEAD.
  * ``.claude/hooks/pii-guard.sh`` — Claude Code PreToolUse Bash guard.

Every test builds its OWN scratch git repo and/or temp patterns file inside
``tmp_path``. Nothing here reads the maintainer's real ``.pii-patterns`` — the
hooks must behave identically on a public clone that has no such file, and the
PII-guard tests supply a synthetic patterns file they create themselves.

Skipped cleanly when ``jq`` is unavailable (the PII guard shells out to it).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_PUSH = REPO_ROOT / ".githooks" / "pre-push"
PRE_COMMIT = REPO_ROOT / ".githooks" / "pre-commit"
PII_GUARD = REPO_ROOT / ".claude" / "hooks" / "pii-guard.sh"
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "pii" / "audit_oss_release.py"

# A synthetic token caught by the current audit script's ``sk-`` openai-key
# pattern AND the hardened ``sk-ant-`` pattern — so the pre-push audit test is
# independent of which audit-script version has merged. Assembled at runtime so
# this file never contains a literal the audit flags at rest — don't inline it.
FAKE_SK_ANT = "sk-ant-" + "abc012345678901234567890"

requires_jq = pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required by pii-guard.sh")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _init_scratch_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")


# --------------------------------------------------------------------------
# .githooks/pre-push
# --------------------------------------------------------------------------


def _run_pre_push(repo: Path, remote_name: str, remote_url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PRE_PUSH), remote_name, remote_url],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_pre_push_rejects_foreign_remote_on_maintainer_clone(tmp_path: Path) -> None:
    """With the local-only ``.pii-patterns`` marker present (maintainer clone),
    a push to a non-allowlisted remote is refused before the audit runs."""
    repo = tmp_path / "repo"
    _init_scratch_repo(repo)
    (repo / ".pii-patterns").write_text("SECRETTOKEN123\n")
    (repo / "readme.txt").write_text("hello\n")
    _git(repo, "add", "readme.txt")
    _git(repo, "commit", "-q", "-m", "init")

    result = _run_pre_push(repo, "origin", "https://github.com/evil/repo")
    assert result.returncode == 1, result.stderr


def test_pre_push_allows_foreign_remote_without_patterns_file(tmp_path: Path) -> None:
    """Public clones and forks have no ``.pii-patterns``, so the allowlist is
    dormant — a contributor pushing to their own fork only runs the audit."""
    repo = tmp_path / "repo"
    _init_scratch_repo(repo)
    (repo / "scripts" / "pii").mkdir(parents=True)
    shutil.copy(AUDIT_SCRIPT, repo / "scripts" / "pii" / "audit_oss_release.py")
    (repo / "benign.txt").write_text("a perfectly ordinary file\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")

    result = _run_pre_push(repo, "origin", "https://github.com/contributor/tidings-fork")
    assert result.returncode == 0, result.stderr + result.stdout


def test_pre_push_allows_tidings_remote_clean_tree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_scratch_repo(repo)
    # The hook runs ``scripts/pii/audit_oss_release.py`` relative to the repo root,
    # so the scratch repo needs its own copy of the audit script.
    (repo / "scripts" / "pii").mkdir(parents=True)
    shutil.copy(AUDIT_SCRIPT, repo / "scripts" / "pii" / "audit_oss_release.py")
    (repo / "benign.txt").write_text("a perfectly ordinary file\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")

    result = _run_pre_push(repo, "origin", "https://github.com/tvhahn/tidings.git")
    assert result.returncode == 0, result.stderr + result.stdout


def test_pre_push_blocks_on_audit_hit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_scratch_repo(repo)
    (repo / "scripts" / "pii").mkdir(parents=True)
    shutil.copy(AUDIT_SCRIPT, repo / "scripts" / "pii" / "audit_oss_release.py")
    (repo / "leak.py").write_text(f'key = "{FAKE_SK_ANT}"\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")

    result = _run_pre_push(repo, "origin", "https://github.com/tvhahn/tidings.git")
    assert result.returncode == 1, result.stderr + result.stdout


def _setup_staleness_repo(tmp_path: Path) -> tuple[Path, str]:
    """A clean scratch repo (audit script copied in) with a synthetic
    ``.pii-patterns``; returns the repo and the patterns file's content."""
    repo = tmp_path / "repo"
    _init_scratch_repo(repo)
    (repo / "scripts" / "pii").mkdir(parents=True)
    shutil.copy(AUDIT_SCRIPT, repo / "scripts" / "pii" / "audit_oss_release.py")
    (repo / "benign.txt").write_text("a perfectly ordinary file\n")
    _git(repo, "add", "benign.txt", "scripts/pii/audit_oss_release.py")
    _git(repo, "commit", "-q", "-m", "init")
    # .pii-patterns (and its stamp) are local-only/untracked in the real repo —
    # written to the working tree, never committed, so the archive-audit of HEAD
    # never sees the synthetic token.
    patterns_body = "SECRETTOKEN123\n"
    (repo / ".pii-patterns").write_text(patterns_body)
    return repo, patterns_body


def test_pre_push_staleness_warns_without_stamp(tmp_path: Path) -> None:
    """Patterns present but no ``.pii-patterns.sha256`` stamp — the push is still
    allowed (warn-only) and the staleness notice appears on stderr."""
    repo, _ = _setup_staleness_repo(tmp_path)

    result = _run_pre_push(repo, "origin", "https://github.com/tvhahn/tidings.git")
    assert result.returncode == 0, result.stderr + result.stdout
    assert "make sync-pii-patterns" in result.stderr


def test_pre_push_no_staleness_warning_when_stamp_matches(tmp_path: Path) -> None:
    """A stamp whose hex matches the current file's sha256 — no warning."""
    repo, patterns_body = _setup_staleness_repo(tmp_path)
    digest = hashlib.sha256(patterns_body.encode()).hexdigest()
    (repo / ".pii-patterns.sha256").write_text(digest + "\n")

    result = _run_pre_push(repo, "origin", "https://github.com/tvhahn/tidings.git")
    assert result.returncode == 0, result.stderr + result.stdout
    assert "WARN" not in result.stderr


def test_pre_push_staleness_warns_when_stamp_differs(tmp_path: Path) -> None:
    """A stamp whose hex no longer matches the current file — warning present,
    push still allowed."""
    repo, _ = _setup_staleness_repo(tmp_path)
    (repo / ".pii-patterns.sha256").write_text("0" * 64 + "\n")

    result = _run_pre_push(repo, "origin", "https://github.com/tvhahn/tidings.git")
    assert result.returncode == 0, result.stderr + result.stdout
    assert "make sync-pii-patterns" in result.stderr


# --------------------------------------------------------------------------
# .githooks/pre-commit
# --------------------------------------------------------------------------


def _run_pre_commit(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PRE_COMMIT)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_pre_commit_blocks_staged_added_token(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_scratch_repo(repo)
    (repo / ".pii-patterns").write_text("SECRETTOKEN123\n")
    (repo / "notes.txt").write_text("contains SECRETTOKEN123 in the body\n")
    _git(repo, "add", "notes.txt")

    result = _run_pre_commit(repo)
    assert result.returncode == 1, result.stderr + result.stdout
    # The matched token must never appear in hook output (transcripts).
    assert "SECRETTOKEN123" not in (result.stdout + result.stderr)


def test_pre_commit_allows_scrub_commit(tmp_path: Path) -> None:
    """A scrub commit removes the leaked value: it appears only on `-` lines of
    the staged diff, so the added-lines-only scan must let it through."""
    repo = tmp_path / "repo"
    _init_scratch_repo(repo)
    (repo / ".pii-patterns").write_text("SECRETTOKEN123\n")
    # Scratch repos install no hooks, so committing the token here is fine.
    (repo / "notes.txt").write_text("leaked SECRETTOKEN123 here\nkeep this line\n")
    _git(repo, "add", "notes.txt")
    _git(repo, "commit", "-q", "-m", "seed")
    # Stage the scrub: the token line is removed, only benign content remains.
    (repo / "notes.txt").write_text("keep this line\n")
    _git(repo, "add", "notes.txt")

    result = _run_pre_commit(repo)
    assert result.returncode == 0, result.stderr + result.stdout


def test_pre_commit_silent_without_patterns_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_scratch_repo(repo)
    (repo / "notes.txt").write_text("contains SECRETTOKEN123 in the body\n")
    _git(repo, "add", "notes.txt")

    result = _run_pre_commit(repo)
    assert result.returncode == 0, result.stderr + result.stdout


def test_pre_commit_respects_attribution_allowlist(tmp_path: Path) -> None:
    """A token appearing only on a github.com attribution line must not block;
    the same token on a plain added line still blocks."""
    repo = tmp_path / "repo"
    _init_scratch_repo(repo)
    (repo / ".pii-patterns").write_text("SECRETTOKEN123\n")
    (repo / "notes.txt").write_text("clone it from github.com/SECRETTOKEN123/somerepo\n")
    _git(repo, "add", "notes.txt")

    allowed = _run_pre_commit(repo)
    assert allowed.returncode == 0, allowed.stderr + allowed.stdout

    (repo / "notes.txt").write_text(
        "clone it from github.com/SECRETTOKEN123/somerepo\ncall SECRETTOKEN123 at the office\n"
    )
    _git(repo, "add", "notes.txt")

    blocked = _run_pre_commit(repo)
    assert blocked.returncode == 1, blocked.stderr + blocked.stdout
    assert "SECRETTOKEN123" not in (blocked.stdout + blocked.stderr)


def test_pre_commit_tolerates_comment_lines_in_patterns(tmp_path: Path) -> None:
    """Comment lines with regex metacharacters must not error grep out — a grep
    failure would read as "no match" and silently disarm the guard."""
    repo = tmp_path / "repo"
    _init_scratch_repo(repo)
    (repo / ".pii-patterns").write_text("# comment with ( unmatched paren\nSECRETTOKEN123\n")
    (repo / "notes.txt").write_text("contains SECRETTOKEN123 in the body\n")
    _git(repo, "add", "notes.txt")

    result = _run_pre_commit(repo)
    assert result.returncode == 1, result.stderr + result.stdout
    assert "SECRETTOKEN123" not in (result.stdout + result.stderr)


# --------------------------------------------------------------------------
# .claude/hooks/pii-guard.sh
# --------------------------------------------------------------------------


def _run_pii_guard(repo: Path, command: str) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"tool_input": {"command": command}})
    return subprocess.run(
        [str(PII_GUARD)],
        cwd=repo,
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )


@requires_jq
def test_pii_guard_blocks_staged_token(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_scratch_repo(repo)
    # A synthetic patterns file created here in tmp_path — never the real one.
    (repo / ".pii-patterns").write_text("SECRETTOKEN123\n")
    (repo / "notes.txt").write_text("contains SECRETTOKEN123 in the body\n")
    _git(repo, "add", "notes.txt")

    result = _run_pii_guard(repo, "git commit -m wip")
    assert result.returncode == 2, result.stderr + result.stdout
    # The matched token must never appear in hook output (transcripts).
    assert "SECRETTOKEN123" not in (result.stdout + result.stderr)


@requires_jq
def test_pii_guard_silent_without_patterns_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_scratch_repo(repo)
    (repo / "notes.txt").write_text("contains SECRETTOKEN123 in the body\n")
    _git(repo, "add", "notes.txt")

    result = _run_pii_guard(repo, "git commit -m wip")
    assert result.returncode == 0, result.stderr + result.stdout


@requires_jq
def test_pii_guard_ignores_non_git_commands(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_scratch_repo(repo)
    (repo / ".pii-patterns").write_text("SECRETTOKEN123\n")
    (repo / "notes.txt").write_text("contains SECRETTOKEN123 in the body\n")
    _git(repo, "add", "notes.txt")

    result = _run_pii_guard(repo, "ls -la")
    assert result.returncode == 0, result.stderr + result.stdout


@requires_jq
def test_pii_guard_allowlists_attribution_context(tmp_path: Path) -> None:
    """A token appearing only in public-attribution context (github.com/<owner>
    URLs, including the regex-escaped form used by the pre-push allowlist) must
    not block — mirroring PROJECT_TOKEN_ALLOW_CONTEXT in audit_oss_release.py."""
    repo = tmp_path / "repo"
    _init_scratch_repo(repo)
    (repo / ".pii-patterns").write_text("SECRETTOKEN123\n")
    (repo / "notes.txt").write_text(
        "clone it from github.com/SECRETTOKEN123/somerepo\n"
        "grep -qE 'github\\.com[:/]SECRETTOKEN123/somerepo(\\.git)?/?$'\n"
    )
    _git(repo, "add", "notes.txt")

    result = _run_pii_guard(repo, "git commit -m wip")
    assert result.returncode == 0, result.stderr + result.stdout


@requires_jq
def test_pii_guard_still_blocks_token_outside_attribution_context(tmp_path: Path) -> None:
    """The attribution allowlist must not disarm the guard: a token on a plain
    line still blocks even when another staged line is attribution-context."""
    repo = tmp_path / "repo"
    _init_scratch_repo(repo)
    (repo / ".pii-patterns").write_text("SECRETTOKEN123\n")
    (repo / "notes.txt").write_text(
        "clone it from github.com/SECRETTOKEN123/somerepo\ncall SECRETTOKEN123 at the office\n"
    )
    _git(repo, "add", "notes.txt")

    result = _run_pii_guard(repo, "git commit -m wip")
    assert result.returncode == 2, result.stderr + result.stdout
    assert "SECRETTOKEN123" not in (result.stdout + result.stderr)


@requires_jq
def test_pii_guard_allows_scrub_commit(tmp_path: Path) -> None:
    """The footgun fix, exercised through pii-guard's delegation: a scrub commit
    that only removes the leaked value (token on `-` lines) must exit 0, not
    block the very commit that fixes the leak."""
    repo = tmp_path / "repo"
    _init_scratch_repo(repo)
    (repo / ".pii-patterns").write_text("SECRETTOKEN123\n")
    (repo / "notes.txt").write_text("leaked SECRETTOKEN123 here\nkeep this line\n")
    _git(repo, "add", "notes.txt")
    _git(repo, "commit", "-q", "-m", "seed")
    (repo / "notes.txt").write_text("keep this line\n")
    _git(repo, "add", "notes.txt")

    result = _run_pii_guard(repo, "git commit -m scrub")
    assert result.returncode == 0, result.stderr + result.stdout


@requires_jq
def test_pii_guard_tolerates_comment_lines_in_patterns(tmp_path: Path) -> None:
    """Comment lines with regex metacharacters must not error grep out —
    a grep failure would read as "no match" and silently disarm the guard."""
    repo = tmp_path / "repo"
    _init_scratch_repo(repo)
    (repo / ".pii-patterns").write_text("# comment with ( unmatched paren\nSECRETTOKEN123\n")
    (repo / "notes.txt").write_text("contains SECRETTOKEN123 in the body\n")
    _git(repo, "add", "notes.txt")

    result = _run_pii_guard(repo, "git commit -m wip")
    assert result.returncode == 2, result.stderr + result.stdout
    assert "SECRETTOKEN123" not in (result.stdout + result.stderr)
