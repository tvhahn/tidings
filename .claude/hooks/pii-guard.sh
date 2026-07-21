#!/usr/bin/env bash
#
# pii-guard.sh — Claude Code PreToolUse guard for Bash commands.
#
# Reads the PreToolUse JSON from stdin, extracts the command, and — only for
# `git commit` / `git push` — delegates the staged-diff PII scan to the shared
# .githooks/pre-commit hook. That hook owns the single implementation of the
# scan (added lines only, so scrub commits that merely remove a leaked value
# pass, plus the attribution allowlist and comment-stripped patterns file); see
# its header for the full rationale. This script is a thin adapter that maps the
# pre-commit hook's exit code onto the Claude-hook blocking code (exit 2).
#
# On a match the pre-commit hook exits nonzero with a count-only message; the
# matched text is never printed, since hook output lands in transcripts.
#
# Every other path exits 0. When .pii-patterns is absent (public clones,
# agents without the maintainer's pattern file), the delegated hook no-ops
# instantly, so public users and agents are unaffected.

command -v jq >/dev/null 2>&1 || exit 0

payload="$(cat)"
cmd="$(printf '%s' "$payload" | jq -r '.tool_input.command // empty' 2>/dev/null)"

# Only guard git commit / git push.
if ! printf '%s' "$cmd" | grep -qE 'git[[:space:]]+(commit|push)'; then
  exit 0
fi

# Resolve the pre-commit hook from THIS script's own location, not the cwd's
# repo: pii-guard lives at <repo>/.claude/hooks/, so the shared scan is at
# ../../.githooks/pre-commit relative to here. Resolving via git rev-parse
# would break when the guard runs from a scratch repo (tests) or a linked
# worktree that has no .githooks/ of its own — the script must come from the
# installed repo, while the staged diff and patterns file are resolved by the
# pre-commit hook itself against the cwd's repo (git-common-dir).
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pre_commit="${script_dir}/../../.githooks/pre-commit"
if [ ! -x "$pre_commit" ]; then
  exit 0
fi

# Run the shared scan against the cwd's repo; capture stdout+stderr combined.
# On a nonzero exit, surface the hook's count-only message and block with the
# Claude-hook code (2).
if ! scan_out="$("$pre_commit" 2>&1)"; then
  printf '%s\n' "$scan_out" >&2
  exit 2
fi

exit 0
