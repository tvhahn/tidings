#!/usr/bin/env python3
"""Deterministic CHANGELOG.md lint — mechanical format-contract enforcement.

The release workflow (`.github/workflows/release.yml`) extracts a tagged
version's GitHub Release notes by awk-slicing the matching `## [X.Y.Z]` section
out of CHANGELOG.md. That extraction is silent about a malformed file: a broken
header, a mis-ordered section, or a stray `## ` heading can blank the notes or
sweep an unrelated section into them, and nobody notices until the release is
already cut. This gate makes the format a build-time invariant instead.

It enforces only mechanical structure — never tone/voice (that is a human /
brand-voice concern). Checks:

  1. Heading grammar. Every `## [` header is either `## [Unreleased]` or
     `## [X.Y.Z] — YYYY-MM-DD` exactly (em dash, zero-padded valid date, numeric
     X/Y/Z). Exactly one `[Unreleased]`, appearing before all version entries.
     Version entries in strictly descending semver order.
  2. Subsection whitelist. `### ` headings inside entries only from the
     Keep-a-Changelog set: Added, Changed, Deprecated, Removed, Fixed, Security.
  3. Dangling refs in entry/Unreleased bodies (not top matter): (a) raw
     commit-hash-like hex words `\b[0-9a-f]{7,40}\b` that contain at least one
     digit — the digit rule kills English false positives like "defaced"; (b)
     bare `#NNN` PR/issue refs (a `#` + digits at line start or after
     whitespace).
  4. Extraction safety. Replicates release.yml's awk notes-extraction against
     the newest version entry: the slice must be non-empty and must not contain
     a line starting `## ` (the awk stops only at `## [`, so a plain `## `
     heading would leak a whole trailing section into the release notes).

Findings are printed one per line as ``<path>:<line>: <message>``.

Usage: python3 scripts/checks/check_changelog.py [path]   (default CHANGELOG.md)
Exit 0 = clean, 1 = findings, 2 = usage error (file missing).
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from itertools import pairwise
from pathlib import Path

ALLOWED_SUBSECTIONS = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")

# `## [` starts any entry header (Unreleased or a version). Used both to find
# entries and — critically — to replicate the awk slice terminator in check 4.
ENTRY_HEADER_RE = re.compile(r"^## \[")
UNRELEASED_RE = re.compile(r"^## \[Unreleased\]\s*$")
# Em dash (U+2014), zero-padded date. strptime below validates the calendar date.
VERSION_HEADER_RE = re.compile(r"^## \[(\d+)\.(\d+)\.(\d+)\] — (\d{4})-(\d{2})-(\d{2})\s*$")
# A real ATX heading needs a space after the hashes; `#123` is therefore NOT a
# heading and stays scannable for dangling-ref check 3.
HEADING_RE = re.compile(r"^#{1,6}\s")
SUBSECTION_RE = re.compile(r"^### (.*)$")
# Commit-hash-like: a whole hex word, 7-40 chars. `\b…\b` forces the entire
# bounded word to be hex, so "abc1234ghij" does not match. Digit-presence is
# checked separately so all-letter words ("defaced") are excluded.
HEX_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
# `#NNN` at line start or immediately after whitespace.
PR_REF_RE = re.compile(r"(?:^|\s)(#\d+)")

Finding = tuple[int, str]


def _fmt_version(v: tuple[int, int, int]) -> str:
    return ".".join(str(n) for n in v)


def check(text: str) -> list[Finding]:
    """Lint changelog *content*. Returns (line_number, message) findings, sorted.

    Operates on a string so callers (and tests) can lint inline fixtures without
    touching the live file.
    """
    findings: list[Finding] = []
    lines = text.splitlines()

    header_idxs = [i for i, line in enumerate(lines) if ENTRY_HEADER_RE.match(line)]
    if not header_idxs:
        return [(1, "no '## [' entry headers found — expected an [Unreleased] section and version entries")]

    first_entry = header_idxs[0]

    # ------------------------------------------------------------------ check 1
    unreleased_lines: list[int] = []
    version_entries: list[tuple[int, tuple[int, int, int]]] = []
    for i in header_idxs:
        lineno = i + 1
        line = lines[i]
        if UNRELEASED_RE.match(line):
            unreleased_lines.append(lineno)
            continue
        m = VERSION_HEADER_RE.match(line)
        if not m:
            findings.append(
                (
                    lineno,
                    "malformed entry header: expected '## [Unreleased]' or "
                    f"'## [X.Y.Z] — YYYY-MM-DD' (em dash, zero-padded date), got {line!r}",
                )
            )
            continue
        x, y, z, year, month, day = m.groups()
        datestr = f"{year}-{month}-{day}"
        try:
            datetime.strptime(datestr, "%Y-%m-%d")  # noqa: DTZ007  # date-only, no tz needed
        except ValueError:
            findings.append((lineno, f"invalid calendar date in entry header: {datestr!r}"))
        version_entries.append((lineno, (int(x), int(y), int(z))))

    if not unreleased_lines:
        findings.append((first_entry + 1, "missing '## [Unreleased]' section"))
    else:
        findings.extend(
            (ln, "duplicate '## [Unreleased]' section — exactly one allowed") for ln in unreleased_lines[1:]
        )

    if unreleased_lines and version_entries:
        first_unrel = unreleased_lines[0]
        if any(ln < first_unrel for ln, _ in version_entries):
            findings.append((first_unrel, "'## [Unreleased]' must appear before all version entries"))

    for (_, v_prev), (ln, v) in pairwise(version_entries):
        if v_prev <= v:
            findings.append(
                (
                    ln,
                    f"version entries out of order: [{_fmt_version(v)}] must come "
                    f"after (lower than) the preceding [{_fmt_version(v_prev)}] — descending semver",
                )
            )

    # -------------------------------------------------------- checks 2 & 3 (body)
    for i in range(first_entry, len(lines)):
        line = lines[i]
        lineno = i + 1

        sub = SUBSECTION_RE.match(line)
        if sub:
            title = sub.group(1).strip()
            if title not in ALLOWED_SUBSECTIONS:
                findings.append(
                    (
                        lineno,
                        f"unknown subsection '### {title}' — allowed: {', '.join(ALLOWED_SUBSECTIONS)}",
                    )
                )

        if HEADING_RE.match(line):
            continue  # dangling-ref scan is body-only, skip heading lines

        for m in HEX_RE.finditer(line):
            word = m.group()
            if any(c.isdigit() for c in word):
                findings.append(
                    (lineno, f"dangling commit-hash-like ref {word!r} — changelog entries should not embed raw SHAs")
                )
        findings.extend(
            (lineno, f"dangling PR/issue ref {m.group(1)!r} — link the number, do not embed a bare '#NNN'")
            for m in PR_REF_RE.finditer(line)
        )

    # ------------------------------------------------------------------ check 4
    if version_entries:
        newest_ln, newest_v = max(version_entries, key=lambda t: t[1])
        # Mirror release.yml awk: print every line after the entry header, stop at
        # the next `## [`. `-s` treats any output as non-empty; we require a
        # non-blank line, which is strictly safer (blank-only notes are useless).
        sliced: list[Finding] = []
        for j in range(newest_ln, len(lines)):
            if ENTRY_HEADER_RE.match(lines[j]):
                break
            sliced.append((j + 1, lines[j]))

        if not any(body.strip() for _, body in sliced):
            findings.append(
                (
                    newest_ln,
                    f"release-notes extraction for the newest entry [{_fmt_version(newest_v)}] is empty — "
                    "the GitHub Release body would be blank",
                )
            )
        for ln, body in sliced:
            if body.startswith("## "):
                findings.append(
                    (
                        ln,
                        f"release-notes extraction for [{_fmt_version(newest_v)}] sweeps in a trailing "
                        f"section {body!r} — awk stops only at '## [', so a plain '## ' heading leaks "
                        "into the release notes",
                    )
                )

    return sorted(findings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lint CHANGELOG.md against the fixed format contract.")
    parser.add_argument(
        "path", nargs="?", default=Path("CHANGELOG.md"), type=Path, help="Changelog file (default: CHANGELOG.md)"
    )
    args = parser.parse_args(argv)

    path: Path = args.path
    if not path.is_file():
        print(f"error: changelog not found: {path}", file=sys.stderr)
        return 2

    findings = check(path.read_text(encoding="utf-8"))
    if findings:
        for lineno, msg in findings:
            print(f"{path}:{lineno}: {msg}")
        print(f"check-changelog: {len(findings)} finding(s) in {path}")
        return 1

    print(f"check-changelog: {path} — ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
