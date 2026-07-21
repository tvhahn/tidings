#!/usr/bin/env python3
"""Lint the maintainer's untracked ``.pii-patterns`` alphabet for a disarmed gate.

The PII gate greps every consumer (ci.yml, demo-smoke.yml, release.yml, the
pre-push hook, scripts/pii/audit_oss_release.py) with the case-insensitive ERE
alternatives in ``.pii-patterns``. A malformed or silently-neutered pattern file
turns the whole gate green while it scans for nothing. Known failure modes this
catches:

  * a pattern that does not compile (ERE or Python re) — one bad alternative can
    break the combined regex the consumers assemble;
  * a pattern that matches the empty string (e.g. ``x?``) — it matches EVERY line
    downstream, so a leak is never distinguishable from a non-leak;
  * a duplicate live line — dead weight that masks an intended edit;
  * a line accidentally commented out by a leading store-code ``#`` (``#369 …``)
    — it looks like a real pattern but is silently a comment;
  * too few live patterns — a stale/truncated secret enforces a smaller alphabet.

Errors name the offending LINE NUMBER ONLY and never echo the line's content:
the alphabet is itself sensitive and this tool's output lands in CI logs and
transcripts.

Exit codes:
  0  file resolved, every live pattern valid, count >= --min-count.
  1  one or more lint errors.
  3  usage error (patterns file missing).
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path


def _is_comment_trap(raw: str) -> bool:
    """True if a line's first non-whitespace char is ``#`` NOT followed by a space,

    another ``#``, or end-of-line — i.e. it looks like a pattern accidentally
    commented out by a leading store-code ``#`` (``#369 STORECODE``). Real comments
    are written ``# like this`` or ``## header``; a bare ``#`` is fine.
    """
    stripped = raw.strip()
    if not stripped.startswith("#"):
        return False
    rest = stripped[1:]
    if rest == "":  # bare "#"
        return False
    return rest[0] not in (" ", "#")


def _grep_available() -> bool:
    return shutil.which("grep") is not None


def _grep_rejects(pattern: str) -> bool:
    """True if ``grep -E`` considers ``pattern`` an invalid ERE (exit status 2)."""
    result = subprocess.run(  # noqa: S603  # repo-local `grep` on a pattern from the maintainer's own file
        ["grep", "-qiE", pattern, "/dev/null"],  # noqa: S607  # `grep` on PATH — same as scripts/pii/audit_oss_release.py
        capture_output=True,
        check=False,
    )
    # 0 = matched, 1 = no match, 2 = invalid pattern / error.
    return result.returncode == 2


def lint(patterns_path: Path, min_count: int) -> tuple[int, list[str]]:
    """Return (live_count, errors). Each error is a message naming a line number only."""
    errors: list[str] = []
    raw_lines = patterns_path.read_text(encoding="utf-8", errors="replace").splitlines()

    grep_ok = _grep_available()
    if not grep_ok:
        print("note: grep not found — the grep -E validation check was skipped.")

    seen: dict[str, int] = {}
    live_count = 0
    for idx, raw in enumerate(raw_lines, start=1):
        # (e) comment-trap: evaluated on the raw line before the live/comment split.
        if _is_comment_trap(raw):
            errors.append(
                f"line {idx}: starts with '#' not followed by a space or '#' — "
                "looks like a pattern accidentally commented out by a leading store-code '#'"
            )
            continue

        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue

        live_count += 1

        # (a) Python re compilation.
        compiled: re.Pattern[str] | None = None
        try:
            compiled = re.compile(stripped, re.IGNORECASE)
        except re.error:
            errors.append(f"line {idx}: does not compile as a Python regex")

        # (b) grep -E compilation.
        if grep_ok and _grep_rejects(stripped):
            errors.append(f"line {idx}: rejected by 'grep -E' as an invalid pattern")

        # (c) empty-string match — an empty-matching alternative matches every line.
        if compiled is not None and compiled.search("") is not None:
            errors.append(f"line {idx}: matches the empty string — it would match every line downstream")

        # (d) exact-duplicate live line.
        if stripped in seen:
            errors.append(f"line {idx}: duplicate of the live pattern on line {seen[stripped]}")
        else:
            seen[stripped] = idx

    # (f) minimum live count.
    if live_count < min_count:
        errors.append(f"live pattern count {live_count} is below the required minimum {min_count}")

    return live_count, errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lint the .pii-patterns alphabet for a disarmed PII gate.")
    repo_root = Path(__file__).resolve().parents[2]
    ap.add_argument(
        "--patterns",
        type=Path,
        default=repo_root / ".pii-patterns",
        help="Path to the .pii-patterns file (default: <repo_root>/.pii-patterns)",
    )
    ap.add_argument("--min-count", type=int, default=0, help="Minimum number of live (non-comment) patterns required")
    args = ap.parse_args(argv)

    patterns_path = args.patterns.expanduser()
    if not patterns_path.is_file():
        print(f"error: patterns file not found: {patterns_path}", file=sys.stderr)
        return 3

    live_count, errors = lint(patterns_path, args.min_count)

    if errors:
        for err in errors:
            print(f"lint-pii-patterns: ERROR — {err}")
        print(f"lint-pii-patterns: {len(errors)} error(s)")
        return 1

    print(f"lint-pii-patterns: {live_count} live pattern(s) — ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
