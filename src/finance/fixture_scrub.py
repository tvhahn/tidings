"""Scrub PII from a captured bank-email body before it becomes a test fixture.

Pure, with the single optional side-read of ``.pii-patterns`` at the repo root
(untracked — gitignored, so absent from the public tree; there is no
``.gitattributes`` / export-ignore in this repo). When that file is present, its
rules apply *in addition* to the always-on hard redactions; when absent, only the
hard redactions run.

The always-on redactions replace matches with clearly-synthetic placeholders so a
committed fixture is obviously scrubbed:

- email addresses          → ``redacted@example.com``
- 13-to-19-digit card numbers → ``0000 0000 0000 0000``
- card last-4 in ``ending in NNNN`` / ``Card number: ****NNNN`` context → ``0000``
- Interac e-Transfer reference numbers (only in an ``INTERAC`` body) → ``[INTERAC_REF]``
- ``To:`` / ``From:`` header address parts → ``[redacted]``
- any literal ``forwarded_to`` token       → ``[redacted]``

**NOT scrubbed** (deliberately kept — fixtures assert against them, and they are
not personally identifying on their own): merchant names, dollar amounts, and
transaction dates; free-text memo bodies; and *filenames* (message-id / receipt
residue in a filename is out of scope here — the audit script's filename scan and
``tests/unit/test_fixture_hygiene.py`` cover that). See the 2026-07-11 PII audit +
remediation spec under ``docs/specs/00_open-source-migration/`` for the rationale.

Dollar amounts are **never** redacted — fixtures need them to assert against.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Repo root: src/finance/fixture_scrub.py → parents[2] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Clearly-synthetic placeholders — a scrubbed fixture should read as obviously
# redacted, never as a plausible-but-wrong real value.
_EMAIL_PLACEHOLDER = "redacted@example.com"
_CARD_PLACEHOLDER = "0000 0000 0000 0000"
_LAST4_PLACEHOLDER = "0000"
_INTERAC_REF_PLACEHOLDER = "[INTERAC_REF]"
_REDACTED = "[redacted]"

# Email addresses. Deliberately broad — over-redaction is safe for fixtures.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# 13-to-19-digit card numbers, allowing a single space or dash between groups.
# Anchored with digit lookaround so it can't start/end mid-number, and so a
# decimal money amount (max ~9 digits, broken by a comma/period) never matches.
_CARD_RE = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")

# ``To:`` / ``From:`` header lines — redact everything after the header name.
# This covers both the address and any display name (both PII).
_HEADER_RE = re.compile(r"(?im)^(To|From):[ \t]*.+$")

# Card last-4 in a purchase-alert context: ``ending in 1234`` or
# ``Card number: ****1234``. Only the 4-digit group is masked, the context kept.
# Run *after* _CARD_RE so a full PAN is masked as a whole first.
_LAST4_RE = re.compile(r"(?i)(ending in\s+|Card number:\s*\**)(\d{4})(?!\d)")

# Interac e-Transfer reference number, e.g. ``C1Ab3Kf9TrQ2``: an upper-case
# letter, a digit, then 8-12 alphanumerics. Applied only when the body actually
# mentions ``INTERAC`` (case-insensitive) — the shape is common enough that an
# unconditional mask would eat unrelated tokens.
_INTERAC_REF_RE = re.compile(r"\b[A-Z]\d[A-Za-z0-9]{8,12}\b")

# Synthetic last-4s that are safe to keep in tracked fixtures/tests: demo
# constants, the locked resynthesized-fixture values, and documented fakes. A
# last-4 *outside* this set in a masking context is unknown residue → flag it.
_LAST4_ALLOWLIST = frozenset({"0000", "1234", "5678", "2210", "3345", "8804", "7126", "3308", "9054", "6611", "4021"})

# Interac reference numbers that are invented, locked fixture values (the RBC
# set from the 2026-07-11 remediation plus the pre-existing synthetic Simplii
# pair) — safe to keep tracked. Any other ref in an INTERAC body is unknown
# residue → flag it.
_INTERAC_REF_ALLOWLIST = frozenset(
    {
        "C1Ab3Kf9TrQ2",
        "C1XyLmNoPq22",
        "H4NwTqBv7pK3",
        "C1QrStUv8wX4",
        "D4BpQrStUv55",
        "D4F8jklMNoPq",
        "E7G2rstUVwXy",
    }
)


def _pii_patterns_path() -> Path:
    """Resolve the optional ``.pii-patterns`` file at the repo root.

    Monkeypatch this in tests to point at a temporary patterns file.
    """
    return _REPO_ROOT / ".pii-patterns"


def _load_pii_patterns(patterns_path: Path | None) -> list[str]:
    """Read regex rules from ``.pii-patterns`` (one per line; ``#`` comments and
    blank lines skipped — the same format the CI PII scan uses). Missing file →
    empty list.
    """
    path = patterns_path if patterns_path is not None else _pii_patterns_path()
    if not path.is_file():
        return []
    rules: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        rules.append(line)
    return rules


def scrub_body(
    body: str,
    *,
    forwarded_to: str | None = None,
    extra_patterns: list[str] | None = None,
    patterns_path: Path | None = None,
) -> str:
    """Return ``body`` with PII redacted; dollar amounts are preserved.

    Parameters
    ----------
    body:
        The raw email body to scrub.
    forwarded_to:
        The failure's ``forwarded_to`` token, redacted wherever it appears
        verbatim (belt-and-suspenders on top of the email redaction).
    extra_patterns:
        Additional regex rules to apply, same semantics as ``.pii-patterns``.
    patterns_path:
        Override the ``.pii-patterns`` location (injectable for tests). When
        ``None`` the repo-root file is used if it exists.
    """
    if not body:
        return body

    text = body
    # Header address/display-name parts first, so their emails don't survive as
    # a partial placeholder inside a line we then blank anyway.
    text = _HEADER_RE.sub(lambda m: f"{m.group(1)}: {_REDACTED}", text)
    # Full PANs first, so a whole card-number line (e.g. the standard 16-digit
    # test PAN) is masked as one run before the last-4 rule could nibble its
    # leading group.
    text = _CARD_RE.sub(_CARD_PLACEHOLDER, text)
    # Card last-4 in an "ending in" / "Card number:" context → 0000 (context kept).
    text = _LAST4_RE.sub(r"\g<1>" + _LAST4_PLACEHOLDER, text)
    # Interac reference numbers — only when the body is an Interac notification.
    if "interac" in text.lower():
        text = _INTERAC_REF_RE.sub(_INTERAC_REF_PLACEHOLDER, text)
    # Card numbers before emails is irrelevant (disjoint), order kept stable.
    text = _EMAIL_RE.sub(_EMAIL_PLACEHOLDER, text)

    if forwarded_to:
        text = text.replace(forwarded_to, _REDACTED)

    rules = _load_pii_patterns(patterns_path)
    if extra_patterns:
        rules = [*rules, *extra_patterns]
    for rule in rules:
        try:
            text = re.sub(rule, _REDACTED, text, flags=re.IGNORECASE)
        except re.error:
            # A malformed rule in a user-supplied patterns file must not crash
            # the scrub — skip it and keep going.
            continue
    return text


# The scrubber's own synthetic placeholders. A properly-scrubbed fixture is full
# of these, so a PII scan must treat them as clean rather than re-flagging them.
_SCRUB_PLACEHOLDERS = frozenset(
    {_EMAIL_PLACEHOLDER, _CARD_PLACEHOLDER, _LAST4_PLACEHOLDER, _INTERAC_REF_PLACEHOLDER, _REDACTED}
)


def scan_for_pii(text: str, patterns_path: Path | None = None) -> list[str]:
    """Return the PII-looking substrings in ``text``, or an empty list if clean.

    Applies the module's own always-on regexes (emails, card numbers) plus any
    ``.pii-patterns`` rules, and **excludes the scrubber's own placeholders** so a
    body that has already been through :func:`scrub_body` scans clean. Use this
    from checklists/tooling instead of re-inlining the regexes — it stays in
    lockstep with the scrubber when the patterns are tightened.

    Parameters
    ----------
    text:
        The (typically already-scrubbed) fixture body to scan.
    patterns_path:
        Override the ``.pii-patterns`` location (injectable for tests). When
        ``None`` the repo-root file is used if it exists.
    """
    if not text:
        return []

    hits: list[str] = []
    for pattern in (_EMAIL_RE, _CARD_RE):
        for match in pattern.finditer(text):
            value = match.group(0)
            if value not in _SCRUB_PLACEHOLDERS:
                hits.append(value)

    # Card last-4 in a masking context — flag only values outside the synthetic
    # allowlist (so resynthesized fixtures with locked last-4s scan clean).
    hits.extend(match.group(0) for match in _LAST4_RE.finditer(text) if match.group(2) not in _LAST4_ALLOWLIST)

    # Interac reference numbers — only in an INTERAC body, and only unknown refs.
    if "interac" in text.lower():
        for match in _INTERAC_REF_RE.finditer(text):
            ref = match.group(0)
            if ref not in _INTERAC_REF_ALLOWLIST and ref not in _SCRUB_PLACEHOLDERS:
                hits.append(ref)

    for rule in _load_pii_patterns(patterns_path):
        try:
            compiled = re.compile(rule, re.IGNORECASE)
        except re.error:
            continue
        for match in compiled.finditer(text):
            value = match.group(0)
            if value not in _SCRUB_PLACEHOLDERS:
                hits.append(value)

    return hits


def write_fixture_pair(
    *,
    test_data_root: Path,
    dir_slug: str,
    file_slug: str,
    scrubbed_body: str,
    institution: str,
) -> tuple[str, str]:
    """Write a scrubbed ``.txt`` body + ``.json`` skeleton fixture pair.

    Pure filesystem concern — no HTTP. The caller supplies an already-scrubbed
    body and pre-slugified ``dir_slug`` / ``file_slug``. The pair is written under
    ``test_data_root / dir_slug`` (``test_data_root`` is injectable so tests can
    point it at a tmp dir); the returned paths are always the canonical
    repo-relative ``tests/test_data/...`` strings the fixture ``.json`` references.

    Never overwrites: raises :class:`FileExistsError` if either target exists, so
    the caller can disambiguate or surface a conflict.

    Returns
    -------
    tuple[str, str]
        ``(txt_path, json_path)`` — repo-relative paths.
    """
    rel_txt = f"tests/test_data/{dir_slug}/{file_slug}.txt"
    rel_json = f"tests/test_data/{dir_slug}/{file_slug}.json"
    dir_path = test_data_root / dir_slug
    abs_txt = dir_path / f"{file_slug}.txt"
    abs_json = dir_path / f"{file_slug}.json"

    if abs_txt.exists() or abs_json.exists():
        raise FileExistsError(f"A fixture named {file_slug!r} already exists under {dir_slug!r}.")

    dir_path.mkdir(parents=True, exist_ok=True)
    abs_txt.write_text(scrubbed_body, encoding="utf-8")
    # Skeleton mirrors the tests/test_data/<bank>/*.json shape/key order; the
    # author completes the "TODO" fields from the scrubbed body.
    skeleton = {
        "institution": institution,
        "name": "TODO",
        "amount": "TODO",
        "company": "TODO",
        "transaction_type": "TODO",
        "email_filepath": rel_txt,
    }
    abs_json.write_text(json.dumps(skeleton, indent=4) + "\n", encoding="utf-8")

    return rel_txt, rel_json
