"""Variant catalog for the prompt evaluation harness.

Each Variant is a frozen, hashable bundle of (prompt_template, context_field_set,
model, prior_day_summaries, parse). Phase 1 ships V0-V2; Phase 2 adds V3-V5.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from src.finance.summary_provider import DAY_PROMPT_TEMPLATE

if TYPE_CHECKING:
    from collections.abc import Callable

ModelAlias = Literal["sonnet", "opus", "haiku"]

# All 17 keys returned by gather_daily_contexts (src/finance/daily_summary_context.py:93-112).
_FULL_CONTEXT_FIELDS: tuple[str, ...] = (
    "date",
    "day_of_week",
    "day_total",
    "transaction_count",
    "transactions",
    "mtd_total",
    "mtd_by_category",
    "budget_ceiling_monthly",
    "budget_categories",
    "month_day_number",
    "month_total_days",
    "previous_month_total",
    "expected_pace_pct",
    "actual_pace_pct",
    "trend_avg_6mo",
    "top_anomalies",
    "category_deltas_top",
)


def _identity_parse(s: str) -> str:
    return s.strip()


def _v3_parse(s: str) -> str:
    """Extract the headline field from JSON output. Raises on malformed JSON."""
    return json.loads(s.strip())["headline"]


@dataclass(frozen=True)
class Variant:
    name: str
    hypothesis: str
    prompt_template: str
    context_field_set: tuple[str, ...]
    model: ModelAlias
    prior_day_summaries: int = 0
    parse: Callable[[str], str] = field(default=_identity_parse)

    def hash(self) -> str:
        """Stable identity hash. Editing prompt_template, context_field_set,
        model, or prior_day_summaries produces a new hash → only this variant's
        cells go stale.

        Note: ``prior_day_summaries`` changes the rendered prompt (V5 prepends
        a "Recent days:" block) so two variants that differ only in this field
        must hash differently.
        """
        h = hashlib.sha256()
        h.update(self.prompt_template.encode())
        h.update(",".join(sorted(self.context_field_set)).encode())
        h.update(self.model.encode())
        h.update(str(self.prior_day_summaries).encode())
        return h.hexdigest()


# ----- V1 template: ≤25 → ≤15 words ------------------------------------------

_V1_TEMPLATE = DAY_PROMPT_TEMPLATE.replace("≤25 words", "≤15 words")
assert _V1_TEMPLATE != DAY_PROMPT_TEMPLATE, "V1 word-cap swap silently no-op'd"

# ----- V3 template: instruct JSON output -------------------------------------

_V3_INSTRUCTION_REPLACEMENT = (
    'Output strictly as JSON: {{"headline": "<single sentence ≤25 words>", '
    '"why": "<one phrase naming the data point>"}}. No markdown, no preamble.'
)
# Replace the last sentence of the V0 instruction block (the "Stay neutral..." line).
_V0_TAIL = "Stay neutral and observational, never alarmist."
assert _V0_TAIL in DAY_PROMPT_TEMPLATE, "V0 tail line moved; V3 template needs updating"
_V3_TEMPLATE = DAY_PROMPT_TEMPLATE.replace(_V0_TAIL, _V3_INSTRUCTION_REPLACEMENT)

# ----- V2 context_field_set: drop the three monthly-insight keys -------------

_V2_FIELDS = tuple(
    f for f in _FULL_CONTEXT_FIELDS if f not in {"trend_avg_6mo", "top_anomalies", "category_deltas_top"}
)


# ----- Variant instances -----------------------------------------------------

V0_baseline = Variant(
    name="V0_baseline",
    hypothesis="Existing DAY_PROMPT_TEMPLATE is the production bar.",
    prompt_template=DAY_PROMPT_TEMPLATE,
    context_field_set=_FULL_CONTEXT_FIELDS,
    model="sonnet",
)

V1_terse = Variant(
    name="V1_terse",
    hypothesis="≤15 words beats ≤25.",
    prompt_template=_V1_TEMPLATE,
    context_field_set=_FULL_CONTEXT_FIELDS,
    model="sonnet",
)

V2_thin = Variant(
    name="V2_thin",
    hypothesis="Monthly insights add noise.",
    prompt_template=DAY_PROMPT_TEMPLATE,
    context_field_set=_V2_FIELDS,
    model="sonnet",
)

V3_json = Variant(
    name="V3_json",
    hypothesis="Forcing a `why` field disciplines the headline.",
    prompt_template=_V3_TEMPLATE,
    context_field_set=_FULL_CONTEXT_FIELDS,
    model="sonnet",
    parse=_v3_parse,
)

V4_haiku = Variant(
    name="V4_haiku",
    hypothesis="Haiku 4.5 is good enough at fraction of cost.",
    prompt_template=DAY_PROMPT_TEMPLATE,
    context_field_set=_FULL_CONTEXT_FIELDS,
    model="haiku",
)

V5_continuity = Variant(
    name="V5_continuity",
    hypothesis="Yesterday's summaries help today's framing.",
    prompt_template=DAY_PROMPT_TEMPLATE,
    context_field_set=_FULL_CONTEXT_FIELDS,
    model="sonnet",
    prior_day_summaries=2,
)


ALL_VARIANTS: tuple[Variant, ...] = (
    V0_baseline,
    V1_terse,
    V2_thin,
    V3_json,
    V4_haiku,
    V5_continuity,
)


def get_variant(name: str) -> Variant:
    for v in ALL_VARIANTS:
        if v.name == name:
            return v
    raise KeyError(f"Unknown variant: {name!r}. Known: {[v.name for v in ALL_VARIANTS]}")
