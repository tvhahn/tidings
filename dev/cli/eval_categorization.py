"""Categorization bake-off — replay real transactions through several (model, effort) arms.

Usage:
    uv run dev/cli/eval_categorization.py --dry-run
    uv run dev/cli/eval_categorization.py --months 6 --limit 100
    uv run dev/cli/eval_categorization.py --arms luna/none luna/low --repeats 3
    uv run dev/cli/eval_categorization.py --show-rows          # PII: prints merchants

Picks the cheapest reasoning effort for the production categorization call
empirically instead of by vibe. Reads the last N months of real transactions
out of the configured storage backend, keeps only the rows whose *final*
category is trustworthy ground truth, and replays each one through every arm
via `src.finance.categorizer.categorize_with_ai` — the exact prompt, tool
schema and forced `tool_choice` production uses, with the override and
privacy-gate layers deliberately out of the loop (that is why
`categorize_with_ai` exists as its own function; the harness never calls
`categorize_transactions` and never monkeypatches overrides or config).

Ground truth is stratified by how the stored category came to be, because the
strata are not equally trustworthy:

- `override_at_ingest` — a deterministic override rule matched at ingestion
  (`CategoryAudit.source == "override"` with no `previous_source`). The model
  never saw these rows, so they are the only *unbiased* human labels.
- `corrected`      — a human overwrote an AI label (manual source with
  `previous_source == "ai"`). Unbiased, and adversarially selected: these are
  the rows the incumbent model got wrong.
- `confirmed`      — a human reviewed a row and left the category alone
  (`mark_category_reviewed`, which writes a manual source with no
  `previous_source`).
- `ai_unreviewed`  — still carries whatever the incumbent model said. Useful
  only as an *agreement* signal, never as correctness.
- `excluded`       — fallbacks, statement import/enrichment, bulk renames,
  deleted/ignored rows, rows missing Company/Amount, and rows whose category
  has since left the vocabulary.

The nano arm is reported for context but can never win: nano is the incumbent
labeler, so every `ai_unreviewed` row agrees with it by construction.

**Read-only.** No database handle reaches `run_arm`, so a write is
structurally impossible; the harness refuses to run in demo mode; and by
default no merchant name or amount appears in stdout or in the JSON report
(pass `--show-rows` to opt in). Maintainer-only, not shipped UX. The pure
parts (stratification, replay shaping, dedupe, summarization, winner rule,
report rendering) are unit-tested with the provider mocked
(`tests/unit/test_eval_categorization_cli.py`).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import logging
import math
import sys
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from dateutil.relativedelta import relativedelta

from src.finance.app_config import get_config
from src.finance.app_timezone import now_local
from src.finance.categorizer import categorize_with_ai
from src.finance.category_audit import MANUAL_SOURCES, normalize_audit
from src.finance.config_loader import get_category_list
from src.finance.merchant_normalizer import normalize_merchant
from src.finance.openai_client import OpenAIClient
from src.finance.secrets import get_openai_api_key
from src.finance.storage import create_spending_summary

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Arms
# --------------------------------------------------------------------------- #

# Model ids are hardcoded literals on purpose: the harness exists to *decide*
# what the production default should be, so it must not import
# DEFAULT_OPENAI_CHAT_MODEL (or any other production default) — otherwise
# flipping the default silently reshapes the experiment.
_NANO_MODEL = "gpt-5.4-nano"
_LUNA_MODEL = "gpt-5.6-luna"


@dataclass(frozen=True)
class Arm:
    """One (model, reasoning-effort) cell of the bake-off."""

    name: str
    model: str
    reasoning_effort: str | None

    @property
    def effort_label(self) -> str:
        """`none`/`low`/`medium`, or `default` when no effort is sent at all."""
        return self.reasoning_effort or "default"

    @property
    def is_luna(self) -> bool:
        return self.model == _LUNA_MODEL


ARMS: dict[str, Arm] = {
    "nano/default": Arm("nano/default", _NANO_MODEL, None),
    "luna/default": Arm("luna/default", _LUNA_MODEL, None),
    "luna/none": Arm("luna/none", _LUNA_MODEL, "none"),
    "luna/low": Arm("luna/low", _LUNA_MODEL, "low"),
    "luna/medium": Arm("luna/medium", _LUNA_MODEL, "medium"),
}

# Ordered cheapest-first. `default` is deliberately absent: it is reported for
# context but is never eligible to win, because "whatever the model happens to
# default to" is not a setting we can pin in production.
EFFORT_ORDER: tuple[str, ...] = ("none", "low", "medium")

# --------------------------------------------------------------------------- #
# Strata
# --------------------------------------------------------------------------- #

Stratum = Literal["override_at_ingest", "corrected", "confirmed", "ai_unreviewed", "excluded"]

#: Strata whose stored category a human actually stands behind.
HUMAN_VERIFIED_STRATA: tuple[Stratum, ...] = ("override_at_ingest", "corrected", "confirmed")
#: Every stratum that is replayed (human-verified plus the agreement-only one).
SCORED_STRATA: tuple[Stratum, ...] = (*HUMAN_VERIFIED_STRATA, "ai_unreviewed")
ALL_STRATA: tuple[Stratum, ...] = (*SCORED_STRATA, "excluded")

#: Audit sources that never represent a trustworthy per-row label: machine
#: fallbacks, statement ingestion/enrichment rewrites, and bulk renames.
EXCLUDED_SOURCES: frozenset[str] = frozenset({"ai_fallback", "statement_import", "statement_enrich", "category_rename"})

# --------------------------------------------------------------------------- #
# Winner rule thresholds
# --------------------------------------------------------------------------- #

MAX_FALLBACK_RATE = 0.01
MIN_HUMAN_VERIFIED_MARGIN_ROWS = 2
HUMAN_VERIFIED_MARGIN_FRACTION = 0.02
AGREEMENT_MARGIN = 0.03
MAX_P95_LATENCY_S = 8.0

DEFAULT_JSON_DIR = Path("data/eval-harness/categorization")


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested)
# --------------------------------------------------------------------------- #


def classify_ground_truth(item: dict[str, Any], categories: list[str] | None = None) -> Stratum:
    """Bucket one stored transaction by how trustworthy its category is.

    `categories` is the *current* vocabulary; when supplied, a row whose stored
    Category is no longer in it is excluded (compared case-insensitively —
    storage lowercases categories, the vocabulary is title-cased). Passing
    `None` skips only that one check, which keeps the function usable as a pure
    `classify_ground_truth(item)` in tests.

    Note on `confirmed`: the app records an explicit confirmation through
    `TransactionsDB.mark_category_reviewed(..., "manual")` (the `reviewed: true`
    branch of `PATCH /transactions/{tx_id}`), which writes a manual audit
    source with *no* `previous_source` and no `previous_category` — a category
    that was reviewed and left alone. That is the signature matched here. It is
    not airtight: a manual edit applied to a row that never had an audit dict
    also lands without a `previous_source`, so the stratum can absorb a few
    genuine edits of un-audited legacy rows.
    """
    if item.get("DeletedAt"):
        return "excluded"
    if item.get("Ignored"):
        return "excluded"

    company = str(item.get("Company") or "").strip()
    if not company:
        return "excluded"
    if item.get("Amount") is None:
        return "excluded"

    category = str(item.get("Category") or "").strip()
    if not category:
        return "excluded"
    if categories is not None and category.casefold() not in {c.casefold() for c in categories}:
        return "excluded"

    audit = normalize_audit(item.get("CategoryAudit")) or {}
    source = audit.get("source")
    previous_source = audit.get("previous_source")

    if source in EXCLUDED_SOURCES:
        return "excluded"
    # A bare override with no previous_source was written by the categorizer at
    # ingestion. An override *with* one was applied retroactively over an
    # existing label (dev/cli/apply_category_overrides.py) — the model may well
    # have produced that label, so it is not unbiased.
    if source == "override" and not previous_source:
        return "override_at_ingest"
    if source in MANUAL_SOURCES:
        if previous_source == "ai":
            return "corrected"
        if not previous_source:
            return "confirmed"
        return "excluded"
    if source == "ai" and not previous_source:
        return "ai_unreviewed"
    return "excluded"


def build_replay_transaction(item: dict[str, Any]) -> dict[str, Any]:
    """Shape a stored row into the exact dict production hands the categorizer.

    `src/finance/email_pipeline.py` builds `{"amount": <float>, "company": <str>}`
    and nothing else. The prompt interpolates `str(transaction)`, so an extra
    key — or a `Decimal("12.34")` repr where production has `12.34` — would
    change the prompt and invalidate the comparison.
    """
    amount = item.get("Amount")
    if isinstance(amount, Decimal):
        amount = float(amount)
    return {"amount": float(amount or 0.0), "company": str(item.get("Company") or "")}


@dataclass(frozen=True)
class Sample:
    """One replayable row. `index`/`sample_id` are the only safe public handles."""

    index: int
    sample_id: str
    stratum: Stratum
    expected: str
    company: str
    amount: float
    date_file_name: str

    @property
    def replay(self) -> dict[str, Any]:
        return {"amount": self.amount, "company": self.company}


def make_sample_id(forwarded_to: str, date_file_name: str) -> str:
    """Opaque, stable, non-reversible handle for a row (no merchant, no amount)."""
    digest = hashlib.sha256(f"{forwarded_to}|{date_file_name}".encode()).hexdigest()
    return digest[:12]


def dedupe_by_company(samples: list[Sample]) -> list[Sample]:
    """Keep one row per normalized company per stratum — the most recent wins.

    Thirty Starbucks rows teach the harness nothing thirty times over; they just
    weight the score toward whichever merchant the user visits most. Recency
    wins because `DateFileName` sorts lexicographically by time.
    """
    best: dict[tuple[str, str], Sample] = {}
    for sample in samples:
        key = (sample.stratum, normalize_merchant(sample.company).casefold())
        current = best.get(key)
        if current is None or sample.date_file_name > current.date_file_name:
            best[key] = sample
    return sorted(best.values(), key=lambda s: (s.stratum, s.date_file_name), reverse=True)


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile; 0.0 for an empty series."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * pct
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


# --------------------------------------------------------------------------- #
# Recording client
# --------------------------------------------------------------------------- #


@dataclass
class CallRecord:
    """Everything measurable about a single chat() round-trip."""

    latency_s: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None
    cached_tokens: int | None = None
    error: str | None = None


def _as_int(value: Any) -> int | None:
    """Coerce a usage counter to int, tolerating None and junk."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    return int(value)


def extract_usage(completion: Any) -> dict[str, int | None]:
    """Pull token counters off a completion, tolerating every missing layer."""
    usage = getattr(completion, "usage", None)
    completion_details = getattr(usage, "completion_tokens_details", None)
    prompt_details = getattr(usage, "prompt_tokens_details", None)
    return {
        "prompt_tokens": _as_int(getattr(usage, "prompt_tokens", None)),
        "completion_tokens": _as_int(getattr(usage, "completion_tokens", None)),
        "reasoning_tokens": _as_int(getattr(completion_details, "reasoning_tokens", None)),
        "cached_tokens": _as_int(getattr(prompt_details, "cached_tokens", None)),
    }


class RecordingClient:
    """Chat-client wrapper that times and meters every call it proxies.

    Structurally an `AIProviderClient`, so `categorize_with_ai` accepts it
    unchanged. One instance per arm, called sequentially: `last_error` is
    instance state on the inner client, so concurrent calls through one client
    would race the categorizer's error classification.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.model: str | None = getattr(inner, "model", None)
        self.records: list[CallRecord] = []
        # Mirrors the inner client's last_error, refreshed on every chat() so
        # `categorize_with_ai` classifies the real provider failure. A plain
        # attribute rather than a property: `AIProviderClient` declares
        # `last_error` as a mutable attribute, and a read-only property would
        # not satisfy the protocol.
        self.last_error: Exception | None = getattr(inner, "last_error", None)

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> Any:
        start = time.perf_counter()
        completion: Any = None
        raised: BaseException | None = None
        try:
            completion = self._inner.chat(messages, tools=tools, tool_choice=tool_choice)
        except BaseException as exc:
            # Recorded first, re-raised unchanged below — the categorizer owns
            # the decision about what a raised call means.
            raised = exc
        latency = time.perf_counter() - start

        inner_error = getattr(self._inner, "last_error", None)
        self.last_error = inner_error if isinstance(inner_error, Exception) else None

        error_name: str | None = None
        if raised is not None:
            error_name = type(raised).__name__
        elif isinstance(inner_error, BaseException):
            error_name = type(inner_error).__name__

        self.records.append(CallRecord(latency_s=latency, error=error_name, **extract_usage(completion)))
        if raised is not None:
            raise raised
        return completion


# --------------------------------------------------------------------------- #
# Running an arm
# --------------------------------------------------------------------------- #


@dataclass
class Observation:
    """One arm's answer for one sample, plus how it was produced."""

    index: int
    sample_id: str
    stratum: Stratum
    expected: str
    predicted: str
    correct: bool
    audit_source: str | None
    fallback_reason: str | None
    latency_s: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None
    cached_tokens: int | None = None
    error: str | None = None


def run_arm(samples: list[Sample], client: RecordingClient, categories: list[str]) -> list[Observation]:
    """Replay every sample through one arm, sequentially. Takes no DB handle."""
    observations: list[Observation] = []
    for sample in samples:
        transaction = sample.replay
        before = len(client.records)
        predicted = categorize_with_ai(client, transaction, categories)
        record = client.records[before] if len(client.records) > before else CallRecord(latency_s=0.0)
        audit = transaction.get("_category_audit") or {}
        observations.append(
            Observation(
                index=sample.index,
                sample_id=sample.sample_id,
                stratum=sample.stratum,
                expected=sample.expected,
                predicted=predicted.strip().casefold(),
                correct=predicted.strip().casefold() == sample.expected.strip().casefold(),
                audit_source=audit.get("source"),
                fallback_reason=audit.get("fallback_reason"),
                latency_s=record.latency_s,
                prompt_tokens=record.prompt_tokens,
                completion_tokens=record.completion_tokens,
                reasoning_tokens=record.reasoning_tokens,
                cached_tokens=record.cached_tokens,
                error=record.error,
            )
        )
    return observations


# --------------------------------------------------------------------------- #
# Summarizing
# --------------------------------------------------------------------------- #


@dataclass
class ArmSummary:
    """Scored result for one arm, across all repeats."""

    name: str
    model: str
    effort: str
    is_luna: bool
    n: int
    stratum_totals: dict[str, int] = field(default_factory=dict)
    stratum_correct: dict[str, int] = field(default_factory=dict)
    human_verified_correct: int = 0
    human_verified_total: int = 0
    fallback_rate: float = 0.0
    fallback_reasons: dict[str, int] = field(default_factory=dict)
    p50_latency_s: float = 0.0
    p95_latency_s: float = 0.0
    mean_prompt_tokens: float = 0.0
    mean_completion_tokens: float = 0.0
    mean_reasoning_tokens: float = 0.0
    mean_cached_tokens: float = 0.0
    flip_rate: float | None = None
    errors: dict[str, int] = field(default_factory=dict)

    def agreement(self, stratum: str) -> float | None:
        total = self.stratum_totals.get(stratum, 0)
        if not total:
            return None
        return self.stratum_correct.get(stratum, 0) / total


def summarize_arm(arm: Arm, runs: list[list[Observation]]) -> ArmSummary:
    """Fold an arm's repeats into one scorecard.

    Accuracy is scored on the first repeat (one vote per sample, so the
    stratum counts stay interpretable as row counts); latency, tokens and the
    fallback rate pool every repeat; the flip rate compares repeats against
    each other and is `None` for a single run.
    """
    first = runs[0] if runs else []
    flat = [obs for run in runs for obs in run]

    summary = ArmSummary(
        name=arm.name,
        model=arm.model,
        effort=arm.effort_label,
        is_luna=arm.is_luna,
        n=len(first),
    )

    for obs in first:
        summary.stratum_totals[obs.stratum] = summary.stratum_totals.get(obs.stratum, 0) + 1
        if obs.correct:
            summary.stratum_correct[obs.stratum] = summary.stratum_correct.get(obs.stratum, 0) + 1
    summary.human_verified_total = sum(summary.stratum_totals.get(s, 0) for s in HUMAN_VERIFIED_STRATA)
    summary.human_verified_correct = sum(summary.stratum_correct.get(s, 0) for s in HUMAN_VERIFIED_STRATA)

    fallbacks = [obs for obs in flat if obs.audit_source == "ai_fallback"]
    summary.fallback_rate = len(fallbacks) / len(flat) if flat else 0.0
    for obs in fallbacks:
        reason = obs.fallback_reason or "unknown"
        summary.fallback_reasons[reason] = summary.fallback_reasons.get(reason, 0) + 1
    for obs in flat:
        if obs.error:
            summary.errors[obs.error] = summary.errors.get(obs.error, 0) + 1

    latencies = [obs.latency_s for obs in flat]
    summary.p50_latency_s = _percentile(latencies, 0.50)
    summary.p95_latency_s = _percentile(latencies, 0.95)
    summary.mean_prompt_tokens = _mean([float(o.prompt_tokens) for o in flat if o.prompt_tokens is not None])
    summary.mean_completion_tokens = _mean(
        [float(o.completion_tokens) for o in flat if o.completion_tokens is not None]
    )
    summary.mean_reasoning_tokens = _mean([float(o.reasoning_tokens) for o in flat if o.reasoning_tokens is not None])
    summary.mean_cached_tokens = _mean([float(o.cached_tokens) for o in flat if o.cached_tokens is not None])

    if len(runs) > 1:
        by_index: dict[int, set[str]] = {}
        for run in runs:
            for obs in run:
                by_index.setdefault(obs.index, set()).add(obs.predicted)
        flipped = sum(1 for answers in by_index.values() if len(answers) > 1)
        summary.flip_rate = flipped / len(by_index) if by_index else 0.0

    return summary


# --------------------------------------------------------------------------- #
# Winner rule
# --------------------------------------------------------------------------- #


@dataclass
class WinnerDecision:
    """The chosen arm (or none) plus a per-arm explanation of why."""

    winner: str | None
    reasons: dict[str, list[str]] = field(default_factory=dict)


def pick_winner(summaries: list[ArmSummary]) -> WinnerDecision:
    """Cheapest luna effort that is not measurably worse than the best luna arm.

    1. Disqualify any arm whose fallback rate exceeds 1% — an API-rejected
       effort/tool_choice combination surfaces as a silent "Miscellaneous", not
       an exception, so a high fallback rate means the arm is broken, not bad.
    2. Among the survivors, take the lowest effort (none < low < medium) whose
       human-verified correct count is within `max(2 rows, 2%)` of the best
       luna arm.
    3. Its `ai_unreviewed` agreement must be within 3 points of the best luna arm.
    4. Its p95 latency must be <= 8.0 s.
    5. Ties break toward the lower effort.

    Only luna arms compete. Nano is the incumbent labeler — every
    `ai_unreviewed` row agrees with it by construction — and `default` is
    reported but never eligible, since it is not a setting we can pin.
    """
    reasons: dict[str, list[str]] = {s.name: [] for s in summaries}

    for summary in summaries:
        if not summary.is_luna:
            reasons[summary.name].append("not eligible: nano is the incumbent labeler, reported for context only")

    luna = [s for s in summaries if s.is_luna]
    if not luna:
        return WinnerDecision(winner=None, reasons=reasons)

    healthy: list[ArmSummary] = []
    for summary in luna:
        if summary.fallback_rate > MAX_FALLBACK_RATE:
            reasons[summary.name].append(
                f"disqualified: fallback rate {summary.fallback_rate:.1%} > {MAX_FALLBACK_RATE:.0%}"
            )
        else:
            healthy.append(summary)

    if not healthy:
        return WinnerDecision(winner=None, reasons=reasons)

    best_hv = max(s.human_verified_correct for s in healthy)
    agreements = [s.agreement("ai_unreviewed") for s in healthy]
    best_agreement = max([a for a in agreements if a is not None], default=None)
    tolerance = max(float(MIN_HUMAN_VERIFIED_MARGIN_ROWS), HUMAN_VERIFIED_MARGIN_FRACTION * best_hv)

    candidates: list[ArmSummary] = []
    for summary in healthy:
        arm_reasons = reasons[summary.name]
        if summary.effort not in EFFORT_ORDER:
            arm_reasons.append("not eligible: `default` effort is reported but never wins")
            continue

        gap = best_hv - summary.human_verified_correct
        if gap > tolerance:
            arm_reasons.append(
                f"rejected: human-verified correct {summary.human_verified_correct}/{summary.human_verified_total} "
                f"is {gap} behind the best luna arm ({best_hv}), tolerance {tolerance:.1f}"
            )
            continue
        arm_reasons.append(
            f"human-verified correct {summary.human_verified_correct}/{summary.human_verified_total} "
            f"within {tolerance:.1f} of best luna ({best_hv})"
        )

        agreement = summary.agreement("ai_unreviewed")
        if best_agreement is not None and agreement is not None:
            agreement_gap = best_agreement - agreement
            if agreement_gap > AGREEMENT_MARGIN:
                arm_reasons.append(
                    f"rejected: ai_unreviewed agreement {agreement:.1%} is "
                    f"{agreement_gap * 100:.1f} points below the best luna arm ({best_agreement:.1%})"
                )
                continue
            arm_reasons.append(f"ai_unreviewed agreement {agreement:.1%} within 3 points of best luna")

        if summary.p95_latency_s > MAX_P95_LATENCY_S:
            arm_reasons.append(f"rejected: p95 latency {summary.p95_latency_s:.2f}s > {MAX_P95_LATENCY_S:.1f}s")
            continue
        arm_reasons.append(f"p95 latency {summary.p95_latency_s:.2f}s within budget")
        candidates.append(summary)

    if not candidates:
        return WinnerDecision(winner=None, reasons=reasons)

    winner = min(candidates, key=lambda s: (EFFORT_ORDER.index(s.effort), s.name))
    reasons[winner.name].append("WINNER: lowest qualifying effort")
    return WinnerDecision(winner=winner.name, reasons=reasons)


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def _arm_row(summary: ArmSummary) -> str:
    """One markdown row of the per-arm scorecard. Carries no merchant data."""
    return (
        f"| {summary.name} | {summary.model} | {summary.effort} | {summary.n} "
        f"| {_pct(summary.agreement('override_at_ingest'))} "
        f"| {_pct(summary.agreement('corrected'))} "
        f"| {_pct(summary.agreement('confirmed'))} "
        f"| {_pct(summary.agreement('ai_unreviewed'))} "
        f"| {summary.human_verified_correct}/{summary.human_verified_total} "
        f"| {_pct(summary.fallback_rate)} "
        f"| {summary.p50_latency_s:.2f} | {summary.p95_latency_s:.2f} "
        f"| {summary.mean_prompt_tokens:.0f} | {summary.mean_completion_tokens:.0f} "
        f"| {summary.mean_reasoning_tokens:.0f} | {_pct(summary.flip_rate)} |"
    )


def format_markdown(
    summaries: list[ArmSummary],
    decision: WinnerDecision,
    *,
    backend: str,
    stratum_counts: dict[str, int],
    selected_counts: dict[str, int],
    repeats: int = 1,
    samples: list[Sample] | None = None,
    show_rows: bool = False,
) -> str:
    """Render the whole report. Merchant names appear only when `show_rows`."""
    lines: list[str] = []
    lines.append(f"Backend: {backend}")
    lines.append("")
    lines.append("## Sample strata")
    lines.append("")
    lines.append("| stratum | found | replayed |")
    lines.append("| --- | ---: | ---: |")
    lines.extend(
        f"| {stratum} | {stratum_counts.get(stratum, 0)} | {selected_counts.get(stratum, 0)} |"
        for stratum in ALL_STRATA
    )
    lines.append("")

    lines.append(f"## Arms (repeats: {repeats})")
    lines.append("")
    header = (
        "| arm | model | effort | n | override_at_ingest | corrected | confirmed | ai_unreviewed | "
        "human-verified correct | fallback | p50 s | p95 s | prompt tok | completion tok | reasoning tok | flip |"
    )
    lines.append(header)
    lines.append(
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    )
    lines.extend(_arm_row(summary) for summary in summaries)
    lines.append("")

    fallback_lines = [f"- {s.name}: {s.fallback_reasons}" for s in summaries if s.fallback_reasons]
    if fallback_lines:
        lines.append("### Fallback reasons")
        lines.append("")
        lines.extend(fallback_lines)
        lines.append("")

    lines.append("## Verdict")
    lines.append("")
    lines.append(f"Winner: **{decision.winner or 'none — no arm cleared the gates'}**")
    lines.append("")
    for name, arm_reasons in decision.reasons.items():
        lines.append(f"- **{name}**")
        lines.extend(f"  - {reason}" for reason in arm_reasons or ["no notes"])
    lines.append("")

    if show_rows and samples:
        lines.append("## Rows (--show-rows)")
        lines.append("")
        lines.append("| # | id | stratum | company | amount | expected |")
        lines.append("| ---: | --- | --- | --- | ---: | --- |")
        lines.extend(
            f"| {sample.index} | {sample.sample_id} | {sample.stratum} | "
            f"{sample.company} | {sample.amount:.2f} | {sample.expected} |"
            for sample in samples
        )
        lines.append("")

    return "\n".join(lines)


def build_report(
    summaries: list[ArmSummary],
    runs_by_arm: dict[str, list[list[Observation]]],
    decision: WinnerDecision,
    *,
    backend: str,
    stratum_counts: dict[str, int],
    selected_counts: dict[str, int],
    months: int,
    repeats: int,
    samples: list[Sample],
    show_rows: bool = False,
) -> dict[str, Any]:
    """Assemble the JSON report. Rows are identified by index/hash unless `show_rows`."""
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "backend": backend,
        "months": months,
        "repeats": repeats,
        "stratum_counts_found": stratum_counts,
        "stratum_counts_replayed": selected_counts,
        "winner": decision.winner,
        "reasons": decision.reasons,
        "arms": [
            {
                "name": s.name,
                "model": s.model,
                "effort": s.effort,
                "n": s.n,
                "agreement": {stratum: s.agreement(stratum) for stratum in SCORED_STRATA},
                "stratum_totals": s.stratum_totals,
                "stratum_correct": s.stratum_correct,
                "human_verified_correct": s.human_verified_correct,
                "human_verified_total": s.human_verified_total,
                "fallback_rate": s.fallback_rate,
                "fallback_reasons": s.fallback_reasons,
                "errors": s.errors,
                "p50_latency_s": s.p50_latency_s,
                "p95_latency_s": s.p95_latency_s,
                "mean_prompt_tokens": s.mean_prompt_tokens,
                "mean_completion_tokens": s.mean_completion_tokens,
                "mean_reasoning_tokens": s.mean_reasoning_tokens,
                "mean_cached_tokens": s.mean_cached_tokens,
                "flip_rate": s.flip_rate,
            }
            for s in summaries
        ],
        "observations": {
            name: [
                [
                    {
                        "index": obs.index,
                        "sample_id": obs.sample_id,
                        "stratum": obs.stratum,
                        "expected": obs.expected,
                        "predicted": obs.predicted,
                        "correct": obs.correct,
                        "audit_source": obs.audit_source,
                        "fallback_reason": obs.fallback_reason,
                        "latency_s": obs.latency_s,
                        "prompt_tokens": obs.prompt_tokens,
                        "completion_tokens": obs.completion_tokens,
                        "reasoning_tokens": obs.reasoning_tokens,
                        "cached_tokens": obs.cached_tokens,
                        "error": obs.error,
                    }
                    for obs in run
                ]
                for run in runs
            ]
            for name, runs in runs_by_arm.items()
        },
    }
    if show_rows:
        report["rows"] = [
            {
                "index": s.index,
                "sample_id": s.sample_id,
                "stratum": s.stratum,
                "company": s.company,
                "amount": s.amount,
                "expected": s.expected,
            }
            for s in samples
        ]
    return report


# --------------------------------------------------------------------------- #
# Data collection (read-only)
# --------------------------------------------------------------------------- #


def describe_backend() -> str:
    """Human-readable name of the storage backend the harness will read."""
    config = get_config()
    if config.get("demo_mode"):
        return "demo (data/demo.db)"
    if config.get("storage") == "dynamodb":
        return "dynamodb (Transactions table)"
    return "sqlite (data/finance.db)"


def read_recent_items(months: int) -> list[dict[str, Any]]:
    """Read the trailing `months` months of rows, newest month first.

    Uses `SpendingSummary.query_month()` — the only public, factory-provided,
    read-only method that returns whole rows (`TransactionsDB.query_month_partition`
    projects away `CategoryAudit`, which is exactly the field the strata are
    built from). No write method is reachable from this object graph.
    """
    service = create_spending_summary()
    today = now_local()
    items: list[dict[str, Any]] = []
    for offset in range(months):
        year_month = (today - relativedelta(months=offset)).strftime("%Y-%m")
        items.extend(dict(item) for item in service.query_month(year_month))
    return items


def collect_samples(
    items: list[dict[str, Any]], categories: list[str], limit: int
) -> tuple[list[Sample], dict[str, int], dict[str, int]]:
    """Stratify, dedupe and cap. Returns (samples, found counts, replayed counts).

    Every human-verified row survives the cap; only `ai_unreviewed` — the
    stratum that is merely an agreement signal — is trimmed to `limit`,
    newest-first.
    """
    found: dict[str, int] = dict.fromkeys(ALL_STRATA, 0)
    staged: list[Sample] = []
    for item in items:
        stratum = classify_ground_truth(item, categories)
        found[stratum] = found.get(stratum, 0) + 1
        if stratum == "excluded":
            continue
        staged.append(
            Sample(
                index=-1,
                sample_id=make_sample_id(str(item.get("ForwardedTo") or ""), str(item.get("DateFileName") or "")),
                stratum=stratum,
                expected=str(item.get("Category") or "").strip().casefold(),
                company=str(item.get("Company") or "").strip(),
                amount=build_replay_transaction(item)["amount"],
                date_file_name=str(item.get("DateFileName") or ""),
            )
        )

    deduped = dedupe_by_company(staged)

    selected: list[Sample] = []
    ai_unreviewed_kept = 0
    for sample in deduped:
        if sample.stratum == "ai_unreviewed":
            if ai_unreviewed_kept >= limit:
                continue
            ai_unreviewed_kept += 1
        selected.append(sample)

    selected = [replace(sample, index=i) for i, sample in enumerate(selected)]
    replayed: dict[str, int] = dict.fromkeys(ALL_STRATA, 0)
    for sample in selected:
        replayed[sample.stratum] = replayed.get(sample.stratum, 0) + 1
    return selected, found, replayed


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def parse_arm_names(raw: list[str] | None) -> list[str]:
    """Resolve `--arms` (space- or comma-separated) to known arm names, in canonical order."""
    if not raw:
        return list(ARMS)
    requested: list[str] = []
    for chunk in raw:
        requested.extend(part.strip() for part in chunk.split(",") if part.strip())
    unknown = [name for name in requested if name not in ARMS]
    if unknown:
        raise SystemExit(f"Unknown arm(s): {', '.join(unknown)}. Known: {', '.join(ARMS)}")
    return [name for name in ARMS if name in set(requested)]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eval_categorization.py",
        description="Replay real transactions through several (model, reasoning-effort) arms.",
    )
    parser.add_argument("--months", type=int, default=6, help="Trailing months of transactions to read (default: 6)")
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Cap on the ai_unreviewed stratum (default: 100). Human-verified rows are never capped.",
    )
    parser.add_argument("--repeats", type=int, default=1, help="Times to replay each arm (default: 1)")
    parser.add_argument(
        "--arms",
        nargs="+",
        metavar="NAME",
        help=f"Subset of arms to run (space- or comma-separated). Known: {', '.join(ARMS)}",
    )
    parser.add_argument(
        "--json-out",
        metavar="PATH",
        help=f"Where to write the JSON report (default: {DEFAULT_JSON_DIR}/<UTC timestamp>.json)",
    )
    parser.add_argument(
        "--show-rows",
        action="store_true",
        help="Include merchant names and amounts in the report (off by default — these are real transactions)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the backend and per-stratum sample counts, then stop. Makes zero API calls.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    args = build_arg_parser().parse_args(argv)

    if get_config().get("demo_mode"):
        print("Refusing to run: demo mode is active — the seeded demo rows are not real ground truth.")
        return 2

    arm_names = parse_arm_names(args.arms)
    backend = describe_backend()
    print(f"Backend: {backend}")

    categories = get_category_list()
    items = read_recent_items(args.months)
    samples, found, replayed = collect_samples(items, categories, args.limit)

    print(f"Rows read: {len(items)} over {args.months} month(s); vocabulary: {len(categories)} categories")
    for stratum in ALL_STRATA:
        print(f"  {stratum:<20} found={found.get(stratum, 0):<6} replayed={replayed.get(stratum, 0)}")

    if args.dry_run:
        print("\n--dry-run: no client constructed, no API calls made.")
        return 0

    if not samples:
        print("No replayable samples — nothing to measure.")
        return 1

    api_key = get_openai_api_key()
    runs_by_arm: dict[str, list[list[Observation]]] = {}

    def _run(arm: Arm) -> list[list[Observation]]:
        client = RecordingClient(OpenAIClient(model=arm.model, api_key=api_key, reasoning_effort=arm.reasoning_effort))
        return [run_arm(samples, client, categories) for _ in range(max(1, args.repeats))]

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(arm_names)) as pool:
        futures = {pool.submit(_run, ARMS[name]): name for name in arm_names}
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            runs_by_arm[name] = future.result()

    summaries = [summarize_arm(ARMS[name], runs_by_arm[name]) for name in arm_names]
    decision = pick_winner(summaries)

    print()
    print(
        format_markdown(
            summaries,
            decision,
            backend=backend,
            stratum_counts=found,
            selected_counts=replayed,
            repeats=max(1, args.repeats),
            samples=samples,
            show_rows=args.show_rows,
        )
    )

    report = build_report(
        summaries,
        runs_by_arm,
        decision,
        backend=backend,
        stratum_counts=found,
        selected_counts=replayed,
        months=args.months,
        repeats=max(1, args.repeats),
        samples=samples,
        show_rows=args.show_rows,
    )
    out_path = (
        Path(args.json_out)
        if args.json_out
        else DEFAULT_JSON_DIR / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"JSON report: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
