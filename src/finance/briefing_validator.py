"""Verify that every figure in an AI briefing traces back to its context data.

The monthly insights briefing (``src/api/routers/insights.py``) is generated
from a context JSON assembled by ``src.finance.insights_context.gather_context``.
That context is built so *every* legitimate figure the briefing may cite exists
somewhere in it, and ``BRIEFING_PROMPT`` hard-requires that "every dollar amount
and percentage in the briefing must appear verbatim in the data". That turns
hallucination into a checkable invariant: extract every figure from the
generated markdown, confirm each one appears in the context payload, flag the
rest.

Pure, dependency-free, deterministic. No I/O, no network, no clock. The router
and the ``dev/cli/regen_insights.py`` eval harness both call
:func:`validate_briefing`; the router persists :meth:`ValidationResult.to_sidecar_dict`
next to the saved ``.md``.

Matching rules (exact — no tolerance windows)
---------------------------------------------
A printed figure counts as "in the data" when, after the documented rounding,
it equals one of the presentation forms of some numeric leaf in the context:

1. Every numeric leaf ``v`` in the context (recursively; booleans excluded)
   contributes three *presentation forms*: its absolute value rounded to 0, 1,
   and 2 decimal places. Briefings drop the sign on variances (a ``-1,320``
   context delta is printed ``$1,320``), so the absolute value is what we index.
   Context floats carry 2 decimals; briefings routinely print the integer
   dollars (``$12,480`` for ``12480.09``) or the 1-decimal percent (``12.0%``
   for a ``11.95`` or ``12.04`` leaf), so rounding to 0/1/2 dp covers the forms
   a briefing actually uses.
2. Each form is canonicalised to a fixed 2-decimal string (``12480.09`` →
   ``"12480.09"``, ``round(12480.09, 0)`` → ``"12480.00"``). Canonicalising the
   printed figure the same way and testing set membership is an exact,
   float-dust-free comparison.
3. Percentages validate against numeric leaves on the *same* percent scale
   (``pace`` ``variance_pct``, ``delta.percent``, ``delta_pct`` …): a printed
   ``12.0%`` matches a context ``12.0`` or an ``11.95`` that rounds to it. Both
   ``$`` and ``%`` figures draw from one shared index of numeric leaves — the
   sigil only affects extraction, not matching.

Deliberately out of scope (documented blind spots)
---------------------------------------------------
- **Multipliers** ("6x"/"10x", including the unicode times-sign variant briefings
  actually print): never extracted — they carry no ``$`` or ``%`` sigil.
- **Bare numbers**: transaction counts ("nine fewer"), years ("2026-2027"),
  ordinals, and dates carry no sigil and are not extracted.
- **Compound phrases** ("$85 of $745"): the two dollar figures are extracted and
  matched independently; the ratio between them is not interpreted.
- **Scale conversions**: a context *share* of ``0.83`` printed as ``83%`` does
  not match — percentages match only leaves already expressed on a percent
  scale. We never multiply a leaf by 100 to manufacture a match.
- **Truncation vs. rounding**: a briefing that floors ``12480.60`` to ``12480``
  is flagged; only standard rounding to 0/1/2 dp is accommodated.
- **Code fences**: figures inside triple-backtick fenced blocks are ignored
  (illustrative, not asserted).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

__all__ = [
    "Figure",
    "FigureVerdict",
    "ValidationResult",
    "collect_context_numbers",
    "extract_figures",
    "validate_briefing",
]

FigureKind = Literal["dollar", "percent"]

# A dollar amount: a `$`, optional space, then either a comma-grouped integer
# (12,480 / 2,950) or a plain run of digits (85 / 4021), with an optional
# fractional part of one or two places (.00 / .99). Matches $12,480, $2,950.00,
# $85, $1,240.00. A bare number with neither sigil is intentionally never caught.
_DOLLAR_RE = re.compile(r"\$\s?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?")

# A percentage: a run of digits with an optional single fractional group, an
# optional space, then `%`. Matches 12.0%, 19.6%, 132.4%, 6%.
_PERCENT_RE = re.compile(r"\d+(?:\.\d+)?\s?%")

# Triple-backtick fenced code blocks — their figures are illustrative, not
# asserted, so they are excised before extraction.
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)

_SNIPPET_PAD = 30  # chars of context kept on each side of a matched figure


@dataclass(frozen=True)
class Figure:
    """A dollar amount or percentage lifted verbatim from a briefing.

    ``value`` is the parsed magnitude (``$2,950.00`` → ``2950.0``, ``12.0%`` →
    ``12.0``). ``snippet`` is the surrounding ~60 chars, whitespace-collapsed,
    for human-readable reporting. ``start`` is the offset in the source markdown.
    """

    kind: FigureKind
    raw: str
    value: float
    snippet: str
    start: int


@dataclass(frozen=True)
class FigureVerdict:
    """One figure paired with whether it was found in the context."""

    figure: Figure
    matched: bool


@dataclass(frozen=True)
class ValidationResult:
    """The per-figure verdicts for a briefing plus roll-up counts."""

    verdicts: list[FigureVerdict]

    @property
    def total(self) -> int:
        return len(self.verdicts)

    @property
    def matched_count(self) -> int:
        return sum(1 for v in self.verdicts if v.matched)

    @property
    def unmatched_count(self) -> int:
        return self.total - self.matched_count

    @property
    def ok(self) -> bool:
        """True when every extracted figure traces to the context."""
        return self.unmatched_count == 0

    @property
    def unmatched(self) -> list[FigureVerdict]:
        return [v for v in self.verdicts if not v.matched]

    def to_sidecar_dict(self) -> dict[str, Any]:
        """Serialise to the ``<ts>.validation.json`` sidecar shape.

        Carries every figure (with its ``matched`` verdict and snippet) plus a
        summary block, so the router can project the unmatched subset onto the
        API model and the eval CLI can print the full ledger.
        """
        return {
            "ok": self.ok,
            "summary": {
                "total": self.total,
                "matched": self.matched_count,
                "unmatched": self.unmatched_count,
            },
            "figures": [
                {
                    "raw": v.figure.raw,
                    "kind": v.figure.kind,
                    "value": v.figure.value,
                    "snippet": v.figure.snippet,
                    "matched": v.matched,
                }
                for v in self.verdicts
            ],
        }


def _canon(x: float) -> str:
    """Canonical 2-decimal string key, with ``-0.00`` normalised to ``0.00``."""
    s = f"{x:.2f}"
    return "0.00" if s == "-0.00" else s


def _presentation_forms(value: float) -> set[str]:
    """The canonical keys a numeric leaf ``value`` can legitimately print as.

    Absolute value (briefings drop variance signs), rounded to 0, 1, and 2
    decimals, each as a canonical 2-decimal string.
    """
    a = abs(float(value))
    return {_canon(round(a, digits)) for digits in (0, 1, 2)}


def _snippet(text: str, start: int, end: int) -> str:
    """~60-char window around ``[start, end)``, whitespace-collapsed and trimmed."""
    lo = max(0, start - _SNIPPET_PAD)
    hi = min(len(text), end + _SNIPPET_PAD)
    return re.sub(r"\s+", " ", text[lo:hi]).strip()


def _fence_spans(markdown: str) -> list[tuple[int, int]]:
    """Character spans covered by triple-backtick fenced code blocks."""
    return [(m.start(), m.end()) for m in _FENCE_RE.finditer(markdown)]


def _in_any_span(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(lo <= pos < hi for lo, hi in spans)


def _parse_dollar(raw: str) -> float:
    return float(raw.replace("$", "").replace(",", "").replace(" ", ""))


def _parse_percent(raw: str) -> float:
    return float(raw.replace("%", "").replace(" ", ""))


def extract_figures(markdown: str) -> list[Figure]:
    """Every dollar amount and percentage in ``markdown``, in document order.

    Figures inside triple-backtick fenced code blocks are skipped. Multipliers
    ("6x"), bare numbers, years, and dates are never matched (see module
    docstring). Each figure carries a ~60-char snippet for reporting.
    """
    spans = _fence_spans(markdown)
    figures: list[Figure] = []

    for rx, kind, parse in (
        (_DOLLAR_RE, "dollar", _parse_dollar),
        (_PERCENT_RE, "percent", _parse_percent),
    ):
        for m in rx.finditer(markdown):
            if _in_any_span(m.start(), spans):
                continue
            figures.append(
                Figure(
                    kind=kind,  # type: ignore[arg-type]
                    raw=m.group(0).strip(),
                    value=parse(m.group(0)),
                    snippet=_snippet(markdown, m.start(), m.end()),
                    start=m.start(),
                )
            )

    figures.sort(key=lambda f: f.start)
    return figures


def collect_context_numbers(context: Any) -> set[str]:
    """Every numeric leaf in ``context`` expanded to its canonical presentation forms.

    Walks the JSON structure (dicts, lists, tuples) recursively, collecting each
    ``int``/``float`` leaf — booleans excluded, since ``bool`` is an ``int``
    subclass and ``True``/``False`` are not figures. Each leaf contributes the
    keys from :func:`_presentation_forms`. String leaves are scanned for the
    same dollar/percent figures the extractor finds in briefings — context
    prose (anomaly ``reason`` strings, ``method_note``) is data the model is
    encouraged to quote, so a figure that appears only there still counts as
    appearing in the data. The returned set is the index a printed figure is
    tested against.
    """
    forms: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, bool):
            return
        if isinstance(node, (int, float)):
            forms.update(_presentation_forms(node))
            return
        if isinstance(node, str):
            for m in _DOLLAR_RE.finditer(node):
                forms.update(_presentation_forms(_parse_dollar(m.group(0))))
            for m in _PERCENT_RE.finditer(node):
                forms.update(_presentation_forms(_parse_percent(m.group(0))))
            return
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
            return
        if isinstance(node, (list, tuple)):
            for v in node:
                walk(v)

    walk(context)
    return forms


def validate_briefing(markdown: str, context: dict[str, Any]) -> ValidationResult:
    """Check every figure in ``markdown`` against ``context``.

    Extracts figures, builds the context index once, and renders a per-figure
    ``matched``/``unmatched`` verdict. A figure matches when its canonical
    2-decimal key is one of the presentation forms of some context numeric leaf.
    """
    context_forms = collect_context_numbers(context)
    verdicts = [
        FigureVerdict(figure=fig, matched=_canon(fig.value) in context_forms) for fig in extract_figures(markdown)
    ]
    return ValidationResult(verdicts=verdicts)
