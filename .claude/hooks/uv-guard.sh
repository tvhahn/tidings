#!/usr/bin/env bash
#
# uv-guard.sh — Claude Code PreToolUse guard for Bash commands.
#
# Reads the PreToolUse JSON from stdin, extracts the command, and blocks
# (exit 2) when it invokes a BARE interpreter — `python`, `python3`, `pip`,
# or `pip3` — as a command word. Bare invocations hit the system interpreter,
# which lacks the project's dependencies; the repo's first rule (CLAUDE.md
# Quick Start) is to always go through `uv` (`uv run …`, `uv pip …`, `uvx …`).
#
# A "command word" is the interpreter at the start of the whole command or
# right after a separator (`;`, `&&`, `||`, `|`, `(`, newline). Anything routed
# through `uv`/`uvx`, path-qualified interpreters (`.venv/bin/python`), and the
# words appearing as plain arguments (`command -v python3`, `echo python`,
# `git commit -m "python fix"`) all pass through untouched.
#
# Every other path exits 0 — false negatives are acceptable, false positives
# are not; when in doubt, allow.

command -v jq >/dev/null 2>&1 || exit 0

payload="$(cat)"

# Only inspect Bash tool calls; every other tool passes straight through.
tool="$(printf '%s' "$payload" | jq -r '.tool_name // empty' 2>/dev/null)"
[ "$tool" = "Bash" ] || exit 0

cmd="$(printf '%s' "$payload" | jq -r '.tool_input.command // empty' 2>/dev/null)"
[ -n "$cmd" ] || exit 0

# Match a bare interpreter only at a command-word boundary: the start of a line
# (grep splits multi-line commands on newlines, so `^` covers the newline
# separator too) or immediately after `;`, `&`, `|`, or `(`, allowing optional
# whitespace. A trailing whitespace-or-end boundary keeps `python3-config` and
# path-qualified forms from matching.
if printf '%s' "$cmd" | grep -qE '(^|[;&|(])[[:space:]]*(python3?|pip3?)([[:space:]]|$)'; then
  echo "uv-guard: use \`uv run python|pytest|pip\` — bare python/pip lacks the project's deps (CLAUDE.md Quick Start)" >&2
  exit 2
fi

exit 0
