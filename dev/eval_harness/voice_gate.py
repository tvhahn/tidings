"""Tidings brand-voice violation detector.

Rules verbatim from docs/brand/voice.md §3 plus the four families called out
in spec §11. The harness uses this to flag prompt outputs that drift from the
Tidings observational/quiet voice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# Verbatim from docs/brand/voice.md §3 — keep in sync if voice.md changes.
FORBIDDEN_WORDS: tuple[str, ...] = (
    "unlock",
    "supercharge",
    "crush",
    "conquer",
    "boost",
    "skyrocket",
    "level up",
    "streak",
    "win",
    "level",
    "score",
    "achievement",
    "challenge",
    "urgent",
    "critical",
    "alert!",
    "warning!",
    "danger",
    "oops",
    "whoops",
    "awesome",
    "amazing",
    "magical",
    "seamless",
    "effortless",
    "revolutionary",
    "disrupt",
)

EVALUATIVE_PHRASES: tuple[str, ...] = (
    "solid start",
    "nice job",
    "great month",
    "keep an eye on",
    "you should",
    "you might want to",
    "well done",
)

# 3+ consecutive uppercase letters that aren't one of these acronyms get flagged.
ACRONYM_ALLOWLIST: frozenset[str] = frozenset(
    {"USD", "MTD", "PDT", "PST", "AWS", "CIBC", "RBC", "MBNA", "EST", "EDT", "ETF", "TFSA", "RRSP"}
)

ViolationKind = Literal["forbidden_word", "exclamation", "all_caps", "evaluative_phrase"]


@dataclass(frozen=True)
class Violation:
    kind: ViolationKind
    matched: str
    span: tuple[int, int]


# Compiled once at import. Forbidden-word patterns escape special chars (e.g.,
# "alert!") and use word boundaries that work even when ! is part of the term.
def _compile_forbidden() -> list[tuple[str, re.Pattern[str]]]:
    out: list[tuple[str, re.Pattern[str]]] = []
    for word in FORBIDDEN_WORDS:
        # ! breaks \b on its right side, so we anchor it manually for tokens
        # that end with punctuation.
        if word.endswith("!"):
            pat = re.compile(r"(?<!\w)" + re.escape(word), re.IGNORECASE)
        else:
            pat = re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
        out.append((word, pat))
    return out


_FORBIDDEN_PATTERNS = _compile_forbidden()
_EVALUATIVE_PATTERNS = [(p, re.compile(re.escape(p), re.IGNORECASE)) for p in EVALUATIVE_PHRASES]
_ALLCAPS_PATTERN = re.compile(r"\b([A-Z]{3,})\b")


def detect_voice_violations(text: str) -> list[Violation]:
    """Return all voice violations in ``text``. Empty list when clean."""
    out: list[Violation] = []

    for word, pat in _FORBIDDEN_PATTERNS:
        for m in pat.finditer(text):
            out.append(Violation("forbidden_word", word, m.span()))

    for ch_idx, ch in enumerate(text):
        if ch == "!":
            out.append(Violation("exclamation", "!", (ch_idx, ch_idx + 1)))

    for m in _ALLCAPS_PATTERN.finditer(text):
        token = m.group(1)
        if token in ACRONYM_ALLOWLIST:
            continue
        out.append(Violation("all_caps", token, m.span()))

    for phrase, pat in _EVALUATIVE_PATTERNS:
        for m in pat.finditer(text):
            out.append(Violation("evaluative_phrase", phrase, m.span()))

    out.sort(key=lambda v: v.span[0])
    return out


def violation_summary(violations: list[Violation]) -> str:
    """One-line human-readable summary, e.g., 'forbidden_word: solid; exclamation: !'."""
    if not violations:
        return ""
    by_kind: dict[ViolationKind, list[str]] = {}
    for v in violations:
        by_kind.setdefault(v.kind, []).append(v.matched)
    parts = [f"{kind}: {', '.join(matches)}" for kind, matches in by_kind.items()]
    return "; ".join(parts)
