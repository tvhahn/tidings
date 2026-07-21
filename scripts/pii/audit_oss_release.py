#!/usr/bin/env python3
"""Exhaustive PII / secret audit for the open-source release tree.

Companion to the fresh-repo cutover spec:
docs/specs/00_open-source-migration/2026-05-10-fresh-repo-and-p2-cleanup/SPEC.md (Part 1C).

Scans a target directory for leaks the narrow CI PII scan misses. Unlike CI
(which only greps src/, tests/, docker/email_parsing/, dev/), this walks the
WHOLE target tree — which is exactly how real bank data under data/ and
notebooks/ slipped past CI for months.

Categories:
  * project-pii    — the maintainer's personal token alphabet, read from
                     .pii-patterns (NOT hard-coded here, so this script is
                     itself safe to ship). Matches inside legitimate public
                     contexts (github.com/<owner>, ghcr.io, the LICENSE
                     copyright line) are reported as `allowlisted`, not hits.
  * credential     — generic secret shapes (AWS keys, private keys, gh/npm/
                     openai/slack tokens).
  * generic-cred   — password/secret/api_key/token = "...." assignment lines.
  * lockfile-token — _authToken/_password/_auth in lockfiles.
  * email          — addresses not on the allowlist.
  * phone          — NANP-shaped numbers (high false-positive; manual review).

Severities:
  hit          — blocks; contributes to exit 1.
  review       — manual judgement; contributes to exit 2 (if no hits).
  allowlisted  — reported for transparency; no effect on exit code.

Exit codes:
  0  zero hits, zero manual-review flags. Safe to push.
  1  one or more hits. Block; investigate every hit.
  2  zero hits but some review/manual flags. An independent reading sweep
     (maintainer-local PII-SWEEP-PROMPT.md, untracked) dispositions these.

Usage:
  python scripts/pii/audit_oss_release.py --target /workspace/.release-staging/tidings
  python scripts/pii/audit_oss_release.py --target ~/tidings-stage --scan-history
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# Pattern definitions
# --------------------------------------------------------------------------

# Generic credential shapes. (name, compiled regex, severity)
#
# Ordering matters: patterns are matched top-to-bottom and overlapping matches on
# the same span are de-duplicated in favour of the FIRST (more specific) pattern.
# So `anthropic-key` (sk-ant-…) precedes the broader `openai-key` (sk-…) — an
# `sk-ant-…` token records once, as anthropic-key, not twice.
#
# `card-number` carries a placeholder severity of "review"; its real severity is
# computed per-match from the Luhn checksum (see scan_text_lines): a Luhn-valid
# 16-19-digit run is a `hit`, everything else stays `review` (never dropped, so a
# real PAN with a typo still surfaces). Float false-positives (a 16-digit mantissa
# like the 0.9115… of 268/294) are downgraded to `review` in _card_is_synthetic by
# their decimal-fraction context — NOT by relying on Luhn, since ~1 in 10 mantissas
# is coincidentally Luhn-valid and would otherwise block. (The example is truncated
# on purpose: a full matchable run here would make this audit flag its own source.)
CREDENTIAL_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}"), "hit"),
    ("aws-secret-key", re.compile(r"aws_secret_access_key\s*=\s*[A-Za-z0-9/+=]{40}", re.I), "hit"),
    ("aws-arn-account", re.compile(r"arn:aws:[a-z0-9-]+:[a-z0-9-]*:\d{12}:"), "hit"),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----"), "hit"),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"), "hit"),
    ("npm-token", re.compile(r"npm_[A-Za-z0-9]{36,}"), "hit"),
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "hit"),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), "hit"),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "hit"),
    ("slack-token", re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"), "hit"),
    # Anchored like the scrubber's card regex (fixture_scrub.py) so a decimal
    # money amount can't start/end mid-number. Severity resolved via Luhn below.
    ("card-number", re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"), "review"),
]

# Opaque high-entropy token embedded in a filename (e.g. an SES message id or
# receipt hash carried over from a real email). Flagged only under a `test`
# directory — see walk().
FILENAME_TOKEN_RE = re.compile(r"(?i)[a-z0-9]{35,}")
GENERIC_CRED = re.compile(r"""(?i)(?:password|secret|api[_-]?key|token)\s*[:=]\s*["'][^"'\s]{16,}["']""")
LOCKFILE_KEY = re.compile(r"(_authToken|_password|_auth)\s*[:=]")
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")

# Project-token matches inside these contexts are legitimate public attribution
# (the repo owner appears in clone/badge URLs, the container registry path, and
# the pre-push hook's remote-allowlist regex, whose `github\.com[:/]` form is
# escaped), so they are downgraded to `allowlisted` rather than blocking.
PROJECT_TOKEN_ALLOW_CONTEXT = re.compile(
    r"github\\?\.com[\[\]:/\\A-Za-z0-9_-]*|ghcr\.io|Copyright|SPDX-FileCopyrightText", re.I
)
# Files where the maintainer's name legitimately appears (canonical attribution).
ALLOWLIST_FILES = {"LICENSE", "LICENSE.md", "LICENSE.txt"}

# Email local-parts / domains that are clearly placeholders or project-namespace.
EMAIL_ALLOW_LOCALS = {
    "noreply",
    "no-reply",
    "donotreply",
    "support",
    "hello",
    "info",
    "you",
    "your-email",
    "user",
    "username",
    "admin",
    "example",
    "test",
    "demo",
    "name",
    "email",
    "me",
}
EMAIL_ALLOW_DOMAINS = {
    "example.com",
    "example.org",
    "example.net",
    "email.com",
    "domain.com",
    "tidings.local",
    "localhost",
    "sentry.io",
    "schemas.openxmlformats.org",
    "w3.org",
    "python.org",
}

LOCKFILES = {"uv.lock", "pnpm-lock.yaml", "package-lock.json", "poetry.lock"}

# Meta files this script (or a prior run) writes into the target — never scan.
SKIP_NAMES = {
    "audit-report.json",
    "audit-report.md",
    "audit-report-reviewed.md",
    ".release-manifest.txt",
    ".release-source-sha.txt",
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".svg"}
BINARY_HINT_EXTS = {".xlsx", ".xls", ".zip", ".woff", ".woff2", ".ttf", ".eot", ".db", ".rdb"}

IMAGE_FLAG_BYTES = 100 * 1024
BIG_FILE_BYTES = 5 * 1024 * 1024


def _md_cell(value: str) -> str:
    """Render a raw matched value as a single Markdown table cell.

    Escapes the characters that would otherwise break the table row (`|` and
    newlines) and wraps the value in a code span so leading/trailing whitespace
    survives. Used only when --include-matches un-redacts the report.
    """
    escaped = value.replace("\\", "\\\\").replace("`", "\\`").replace("|", "\\|")
    escaped = escaped.replace("\r", " ").replace("\n", " ")
    return f"`{escaped}`"


@dataclass
class Finding:
    file: str
    line: int
    category: str
    severity: str
    match: str  # full match (only emitted to JSON when --include-matches)

    def redacted(self) -> str:
        return f"<REDACTED:{len(self.match)} chars>"


@dataclass
class Report:
    target: str
    findings: list[Finding] = field(default_factory=list)
    manual_review: list[dict] = field(default_factory=list)
    files_scanned: int = 0
    files_skipped: int = 0
    history: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    patterns_missing: bool = False


# --------------------------------------------------------------------------
# Pattern loading
# --------------------------------------------------------------------------


def load_project_regex(target: Path, explicit: Path | None) -> tuple[re.Pattern[str] | None, str]:
    """Resolve the .pii-patterns file and compile a combined case-insensitive regex.

    Resolution order: --patterns > <target>/.pii-patterns > <script_dir>/../.pii-patterns.
    Returns (regex_or_None, source_description). The patterns file is
    export-ignored, so a staged tree won't contain it; we fall back to the
    source repo's copy (next to this script) so the staged tree is still
    scanned for project tokens.
    """
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)
    candidates.append(target / ".pii-patterns")
    candidates.append(Path(__file__).resolve().parents[2] / ".pii-patterns")

    for path in candidates:
        if path.is_file():
            tokens = []
            for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                tokens.append(line)
            if tokens:
                return re.compile("|".join(f"(?:{t})" for t in tokens), re.I), str(path)
    return None, "(none found — project-token scan skipped)"


# --------------------------------------------------------------------------
# Card-number validation
# --------------------------------------------------------------------------


def luhn_valid(digits: str) -> bool:
    """Return True if ``digits`` (bare 0-9, no separators) passes the Luhn checksum.

    Used to grade a card-shaped match: a Luhn-valid 16-19-digit run is a real-PAN
    ``hit``; anything else is a ``review`` flag (never silently dropped).
    """
    if not digits or not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = ord(ch) - 48
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# --------------------------------------------------------------------------
# File classification + content scanning
# --------------------------------------------------------------------------


def is_binary(path: Path) -> bool:
    try:
        chunk = path.open("rb").read(8192)
    except OSError:
        return True
    return b"\x00" in chunk


def _card_is_synthetic(digits: str, text: str, span: tuple[int, int], matched: str, relpath: str) -> bool:
    """True if a Luhn-valid card-shaped run is obviously *not* a real PAN.

    Generalises trap 8's "the float false-positive must not block": a Luhn-valid
    run that is a placeholder, the fractional part of a decimal number, embedded in
    a hash, or sitting in synthetic test / generated data is downgraded from ``hit``
    to ``review`` — still surfaced (never dropped), just not release-blocking. Real
    standalone PANs in real source/config/data files remain hits.
    """
    # All-identical digits → a placeholder like "0000 0000 0000 0000".
    if len(set(digits)) == 1:
        return True
    # Adjacent to a letter → a digit slice of a longer hex/base32 token (a hash),
    # not a card: real card numbers are bounded by whitespace/punctuation. Measure
    # against the first/last *digit* — the pattern can greedily eat a trailing
    # separator, so span[1] may point past a space to an unrelated next word.
    last_digit_end = span[0] + len(matched.rstrip(" -"))
    before = text[span[0] - 1] if span[0] > 0 else ""
    after = text[last_digit_end] if last_digit_end < len(text) else ""
    if before.isalpha() or after.isalpha():
        return True
    # Fractional part of a decimal number literal (e.g. the mantissa of a capture
    # rate like 0.9115… = 268/294) → never a PAN. The signal is a "." immediately
    # before the run whose own predecessor is a digit, i.e. the run is the tail of
    # `<int>.<frac>`. A PAN is never written `<digit>.<16-19 digits>`, so this is
    # safe; it catches the float false-positive regardless of Luhn. (The example is
    # truncated so this audit does not flag its own source.)
    before2 = text[span[0] - 2] if span[0] > 1 else ""
    if before == "." and before2.isdigit():
        return True
    # Synthetic corpora: test fixtures and dependency lockfiles are full of
    # Luhn-valid card-shaped strings (test PANs, package hashes) that are not PANs.
    p = Path(relpath)
    if any("test" in part.lower() for part in p.parent.parts):
        return True
    return p.name in LOCKFILES


def _credential_findings(text: str, relpath: str, lineno: int) -> list[Finding]:
    """Run every credential pattern over ``text``, de-duplicating overlapping spans.

    Overlaps resolve to the FIRST (more specific) pattern — so an ``sk-ant-…``
    token is recorded once as anthropic-key, not also as the broader openai-key.
    The card-number pattern's severity is graded per-match by Luhn, with a
    synthetic-value guard (see _card_is_synthetic) so placeholders / hash slices /
    test PANs surface as ``review`` rather than block as ``hit``.
    """
    found: list[Finding] = []
    seen: list[tuple[int, int]] = []
    for name, rx, sev in CREDENTIAL_PATTERNS:
        for m in rx.finditer(text):
            span = m.span()
            if any(span[0] < e and s < span[1] for s, e in seen):
                continue  # overlaps a higher-priority credential match
            actual_sev = sev
            if name == "card-number":
                digits = re.sub(r"[ -]", "", m.group(0))
                real_pan = (
                    16 <= len(digits) <= 19
                    and luhn_valid(digits)
                    and not _card_is_synthetic(digits, text, span, m.group(0), relpath)
                )
                actual_sev = "hit" if real_pan else "review"
            seen.append(span)
            found.append(Finding(relpath, lineno, name, actual_sev, m.group(0)))
    return found


def scan_text_lines(lines, relpath, project_re, report, strict_only=False):
    """Scan an iterable of (lineno, text); append findings to report."""
    for lineno, text in lines:
        if project_re:
            for m in project_re.finditer(text):
                allow = bool(PROJECT_TOKEN_ALLOW_CONTEXT.search(text)) or (Path(relpath).name in ALLOWLIST_FILES)
                report.findings.append(
                    Finding(
                        relpath,
                        lineno,
                        "project-pii",
                        "allowlisted" if allow else "hit",
                        m.group(0),
                    )
                )
        for f in _credential_findings(text, relpath, lineno):
            report.findings.append(f)
        if strict_only:
            continue
        for m in GENERIC_CRED.finditer(text):
            report.findings.append(Finding(relpath, lineno, "generic-cred", "review", m.group(0)))
        for m in EMAIL.finditer(text):
            local, _, domain = m.group(0).partition("@")
            if local.lower() in EMAIL_ALLOW_LOCALS or domain.lower() in EMAIL_ALLOW_DOMAINS:
                continue
            report.findings.append(Finding(relpath, lineno, "email", "review", m.group(0)))
        for m in PHONE.finditer(text):
            report.findings.append(Finding(relpath, lineno, "phone", "review", m.group(0)))


def scan_ipynb(path, relpath, project_re, report):
    try:
        nb = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (ValueError, OSError):
        report.manual_review.append({"file": relpath, "reason": "unparseable .ipynb"})
        return
    blob_lines = []
    n = 0
    for cell in nb.get("cells", []):
        for src in cell.get("source", []):
            n += 1
            blob_lines.append((n, src))
        for out in cell.get("outputs", []):
            for src in out.get("text", []) or []:
                n += 1
                blob_lines.append((n, src))
            data = out.get("data", {})
            for v in data.values():
                if isinstance(v, list):
                    for src in v:
                        n += 1
                        blob_lines.append((n, str(src)))
    scan_text_lines(blob_lines, relpath, project_re, report)


def scan_pdf(path, relpath, project_re, report):
    try:
        out = subprocess.run(
            ["pdftotext", str(path), "-"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except FileNotFoundError:
        report.manual_review.append({"file": relpath, "reason": "PDF — pdftotext not installed; inspect manually"})
        return
    except subprocess.SubprocessError:
        report.manual_review.append({"file": relpath, "reason": "PDF — pdftotext failed; inspect manually"})
        return
    lines = list(enumerate(out.stdout.splitlines(), start=1))
    scan_text_lines(lines, relpath, project_re, report)


def scan_binary(path, relpath, project_re, report):
    """Extract printable runs (>=4 chars) and scan strict patterns only."""
    try:
        data = path.read_bytes()
    except OSError:
        report.manual_review.append({"file": relpath, "reason": "unreadable binary"})
        return
    runs = re.findall(rb"[\x20-\x7e]{4,}", data)
    text = b"\n".join(runs).decode("ascii", errors="replace")
    scan_text_lines(enumerate(text.splitlines(), start=1), relpath, project_re, report, strict_only=True)


def scan_file(path: Path, relpath: str, project_re, report: Report):
    try:
        size = path.stat().st_size
    except OSError:
        report.files_skipped += 1
        return
    ext = path.suffix.lower()

    if ext in IMAGE_EXTS:
        report.files_scanned += 1
        if ext == ".svg":  # SVG is text — scan it
            pass
        else:
            if size > IMAGE_FLAG_BYTES:
                report.manual_review.append(
                    {"file": relpath, "reason": f"image {size // 1024}KB — open to confirm not a screenshot"}
                )
            return

    if size > BIG_FILE_BYTES:
        report.files_scanned += 1
        report.manual_review.append(
            {"file": relpath, "reason": f"oversize {size // (1024 * 1024)}MB — inspect manually"}
        )
        return

    report.files_scanned += 1
    if ext == ".ipynb":
        scan_ipynb(path, relpath, project_re, report)
    elif ext == ".pdf":
        scan_pdf(path, relpath, project_re, report)
    elif ext in BINARY_HINT_EXTS or is_binary(path):
        scan_binary(path, relpath, project_re, report)
    else:
        try:
            lines = list(enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1))
        except OSError:
            report.manual_review.append({"file": relpath, "reason": "unreadable text file"})
            return
        scan_text_lines(lines, relpath, project_re, report)


def _scan_filename_tokens(rel: Path, report: Report):
    """Flag long opaque tokens (>=35 alnum) in a path segment under a `test` dir.

    Catches real SES message ids / receipt hashes carried into fixture filenames,
    which content scanning never sees because the residue is in the *name*.
    """
    if not any("test" in part.lower() for part in rel.parent.parts):
        return
    for seg in rel.parts:
        m = FILENAME_TOKEN_RE.search(seg)
        if m:
            report.findings.append(Finding(str(rel), 0, "filename-token", "review", m.group(0)))


def walk(target: Path, project_re, report: Report):
    for path in sorted(target.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(target)
        parts = set(rel.parts)
        if ".git" in parts:
            continue
        if path.name in SKIP_NAMES:
            continue
        _scan_filename_tokens(rel, report)
        scan_file(path, str(rel), project_re, report)


# --------------------------------------------------------------------------
# History scan
# --------------------------------------------------------------------------

HISTORY_MAX_BLOB_BYTES = 20 * 1024 * 1024


def _git(target: Path, args: list[str], *, timeout: int = 300, binary: bool = False):
    return subprocess.run(
        ["git", "-C", str(target), *args],
        capture_output=True,
        timeout=timeout,
        text=not binary,
        check=False,
    )


def _scan_history_blob(sha, content, paths_by_sha, head_shas, project_re, report):
    """Scan one blob's content and append de-duplicated history findings.

    Runs the same line-level scanner as the tree scan (``scan_text_lines``,
    strict credential shapes + project tokens), with the blob's own path as
    context — so attribution allowlisting and Luhn/test-dir severity grading
    match the tree scan instead of re-flagging content the tree scan already
    graded down.
    """
    paths = sorted(paths_by_sha.get(sha, set())) or ["<unnamed/unreachable blob>"]
    in_head = sha in head_shas
    recorded: set[tuple[str, str]] = set()

    scratch = Report(target=report.target)
    scan_text_lines(enumerate(content.splitlines(), start=1), paths[0], project_re, scratch, strict_only=True)
    for f in scratch.findings:
        key = (f.category, f.match)
        if key in recorded:
            continue
        recorded.add(key)
        report.history.append(
            {
                "sha_redacted": f"{sha[:8]}…",
                "paths": paths,
                "category": f.category,
                "severity": f.severity,
                "in_head": in_head,
                "redacted_match": f"<REDACTED:{len(f.match)} chars>",
                "match": f.match,  # emitted to JSON/MD only under --include-matches
            }
        )


def scan_history(target: Path, project_re, report: Report):
    """Blob-level history scan.

    Enumerates every object across all refs, reads each blob (<=20 MB) with
    ``git cat-file``, runs the credential patterns + project regex over its
    content, and records hits with the path(s) the blob appears under and whether
    it is reachable from HEAD. Matched text is redacted, exactly like the tree scan.
    """
    if not (target / ".git").exists():
        report.notes.append("--scan-history requested but target has no .git/; skipped.")
        return
    try:
        all_objs = _git(target, ["rev-list", "--all", "--objects"])
        head_objs = _git(target, ["rev-list", "--objects", "HEAD"])
        batch = _git(
            target,
            ["cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)", "--batch-all-objects"],
        )
    except (subprocess.SubprocessError, OSError) as exc:
        report.notes.append(f"--scan-history: git enumeration failed ({exc}); skipped.")
        return

    paths_by_sha: dict[str, set[str]] = {}
    for line in all_objs.stdout.splitlines():
        sha, _, pth = line.partition(" ")
        if pth:
            paths_by_sha.setdefault(sha, set()).add(pth)
    head_shas = {ln.split(" ", 1)[0] for ln in head_objs.stdout.splitlines() if ln.strip()}

    for line in batch.stdout.splitlines():
        fields = line.split()
        if len(fields) != 3:
            continue
        sha, otype, size = fields
        if otype != "blob":
            continue
        try:
            if int(size) > HISTORY_MAX_BLOB_BYTES:
                continue
        except ValueError:
            continue
        try:
            blob = _git(target, ["cat-file", "blob", sha], timeout=120, binary=True)
        except (subprocess.SubprocessError, OSError):
            continue
        content = blob.stdout.decode("utf-8", errors="replace")
        _scan_history_blob(sha, content, paths_by_sha, head_shas, project_re, report)


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

VERDICTS = {
    0: "✅ clean — safe to push",
    1: "🛑 BLOCK — hits found",
    2: "⚠️ review — manual flags only",
}


def write_reports(report: Report, base: Path, include_matches: bool) -> int:
    hits = [f for f in report.findings if f.severity == "hit"]
    reviews = [f for f in report.findings if f.severity == "review"]
    allowed = [f for f in report.findings if f.severity == "allowlisted"]
    history_hits = [h for h in report.history if h.get("severity") == "hit"]
    history_reviews = [h for h in report.history if h.get("severity") != "hit"]

    if hits or history_hits:
        exit_code = 1
    elif reviews or report.manual_review or history_reviews:
        exit_code = 2
    else:
        exit_code = 0

    by_cat: dict[str, int] = {}
    for f in report.findings:
        by_cat[f.category] = by_cat.get(f.category, 0) + 1

    def to_dict(f: Finding):
        d = {
            "file": f.file,
            "line": f.line,
            "category": f.category,
            "severity": f.severity,
            "redacted_match": f.redacted(),
        }
        if include_matches:
            d["match"] = f.match
        return d

    payload = {
        "target": report.target,
        "summary": {
            "files_scanned": report.files_scanned,
            "files_skipped": report.files_skipped,
            "hits": len(hits),
            "reviews": len(reviews),
            "allowlisted": len(allowed),
            "manual_review_flags": len(report.manual_review),
            "history_hits": len(history_hits),
            "history_reviews": len(history_reviews),
            "exit_code": exit_code,
        },
        "by_category": by_cat,
        "findings": [to_dict(f) for f in report.findings],
        "manual_review": report.manual_review,
        "history": (
            report.history
            if include_matches
            else [{k: v for k, v in h.items() if k != "match"} for h in report.history]
        ),
        "notes": report.notes,
    }
    # --output may point outside the scan target (e.g. the hook writes into
    # logs/audit/); make sure the destination directory exists first.
    base.parent.mkdir(parents=True, exist_ok=True)
    (base.parent / (base.name + ".json")).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    verdict = VERDICTS[exit_code]
    md = [
        f"# OSS release audit — `{report.target}`",
        "",
    ]
    if report.patterns_missing:
        md += [
            "> ⚠️ **No `.pii-patterns` file resolved — the maintainer project-token scan was "
            "SKIPPED.** Generic credential/email/phone scans still ran; personal-token coverage "
            "was not applied to this tree.",
            "",
        ]
    md += [
        f"**Verdict:** {verdict} (exit {exit_code})",
        f"**Files scanned:** {report.files_scanned}  |  **skipped:** {report.files_skipped}",
        f"**Hits:** {len(hits)}  |  **Review:** {len(reviews)}  |  "
        f"**Allowlisted:** {len(allowed)}  |  **Manual flags:** {len(report.manual_review)}",
        "",
        *(
            [
                "Matched text is shown in full below — this report lives in the gitignored",
                "`logs/audit/` tree and is never committed. Re-run without `--include-matches`",
                "to redact.",
            ]
            if include_matches
            else [
                "Matched text is redacted here. Re-run with `--include-matches` to write full",
                "matches into the JSON and Markdown reports for inspection.",
            ]
        ),
        "",
        "## Counts by category",
        "",
        "| Category | Count |",
        "|----------|-------|",
    ]
    for cat, n in sorted(by_cat.items(), key=lambda kv: -kv[1]):
        md.append(f"| {cat} | {n} |")

    match_col = "Match" if include_matches else "Redacted"

    def cell(f: Finding) -> str:
        return _md_cell(f.match) if include_matches else f.redacted()

    def table(title, items):
        md.extend(["", f"## {title}", ""])
        if not items:
            md.append("_none_")
            return
        md.append(f"| File | Line | Category | {match_col} |")
        md.append("|------|------|----------|----------|")
        for f in items:
            md.append(f"| `{f.file}` | {f.line} | {f.category} | {cell(f)} |")

    table(f"Hits (block list) — {len(hits)}", hits)
    table(f"Review (manual judgement) — {len(reviews)}", reviews)

    md.extend(["", f"## Manual-review flags — {len(report.manual_review)}", ""])
    if report.manual_review:
        md.append("| File | Reason |")
        md.append("|------|--------|")
        for item in report.manual_review:
            md.append(f"| `{item['file']}` | {item['reason']} |")
    else:
        md.append("_none_")

    table(f"Allowlisted (acceptable attribution / public URLs) — {len(allowed)}", allowed)

    if report.history:
        md.extend(
            [
                "",
                "## History findings (--scan-history)",
                "",
                f"| SHA | In HEAD | Category | Severity | Paths | {match_col} |",
                "|-----|---------|----------|----------|-------|----------|",
            ]
        )
        for h in report.history:
            paths = ", ".join(h.get("paths", []))
            shown = _md_cell(h.get("match", "")) if include_matches else h.get("redacted_match", "")
            md.append(
                f"| {h.get('sha_redacted', '?')} | {h.get('in_head')} | {h.get('category', '?')} | "
                f"{h.get('severity', '?')} | {paths} | {shown} |"
            )
    if report.notes:
        md.extend(["", "## Notes", ""] + [f"- {n}" for n in report.notes])

    (base.parent / (base.name + ".md")).write_text("\n".join(md) + "\n", encoding="utf-8")
    return exit_code


def main() -> int:
    ap = argparse.ArgumentParser(description="Exhaustive PII/secret audit for the OSS release tree.")
    ap.add_argument("--target", required=True, type=Path, help="Directory to scan")
    ap.add_argument("--scan-history", action="store_true", help="Also scan git history if target has .git/")
    ap.add_argument("--output", type=Path, default=None, help="Report basename (default <target>/audit-report)")
    ap.add_argument("--patterns", type=Path, default=None, help="Explicit .pii-patterns file")
    ap.add_argument(
        "--include-matches",
        action="store_true",
        help="Write full (unredacted) matches into the JSON and Markdown reports",
    )
    args = ap.parse_args()

    target = args.target.expanduser().resolve()
    if not target.is_dir():
        print(f"error: target is not a directory: {target}", file=sys.stderr)
        return 3

    project_re, patterns_src = load_project_regex(target, args.patterns)
    report = Report(target=str(target))
    if project_re is None:
        # Loud skip: warn on stdout AND promote the warning to the report header
        # (write_reports) so a missing patterns file can never pass unnoticed.
        print(
            "WARNING: no .pii-patterns file resolved — the maintainer project-token scan "
            "was SKIPPED. Generic credential/email/phone scans still ran."
        )
        report.patterns_missing = True
        report.notes.append("No .pii-patterns file resolved — project-token category was NOT scanned.")
    else:
        report.notes.append(f"Project tokens from: {patterns_src}")

    walk(target, project_re, report)
    if args.scan_history:
        scan_history(target, project_re, report)

    base = args.output if args.output else (target / "audit-report")
    exit_code = write_reports(report, base, args.include_matches)

    # Terminal summary: redacted aggregates only — counts by severity and by
    # category, never the matched text (that stays in the redacted reports).
    actionable = [f for f in report.findings if f.severity in ("hit", "review")]
    by_cat: dict[str, int] = {}
    for f in actionable:
        by_cat[f.category] = by_cat.get(f.category, 0) + 1
    hits = sum(1 for f in report.findings if f.severity == "hit")
    reviews = sum(1 for f in report.findings if f.severity == "review")

    print(f"audit: scanned {report.files_scanned} files → exit {exit_code}  ({VERDICTS[exit_code]})")
    print(f"  severity:  hits {hits} · review {reviews} · manual-flags {len(report.manual_review)}")
    if by_cat:
        top = sorted(by_cat.items(), key=lambda kv: -kv[1])[:8]
        print("  category:  " + " · ".join(f"{cat} {n}" for cat, n in top))
    if report.history:
        h_hits = sum(1 for h in report.history if h.get("severity") == "hit")
        print(f"  history:   {len(report.history)} finding(s), {h_hits} hit(s)")
    print(f"  reports:   {base}.md / {base}.json")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
