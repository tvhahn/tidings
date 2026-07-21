"""Multi-provider AI summary generation: OpenAI API, Claude Code, OpenAI Codex."""

import asyncio
import json
import logging
import re
import shutil
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from src.finance.ai_cli import DEFAULT_OPENAI_CHAT_MODEL, _codex_signed_in, _gemini_signed_in, run_cli_provider

logger = logging.getLogger(__name__)

DAY_PROMPT_TEMPLATE = """\
You are a personal finance assistant. Write ONE short sentence (≤25 words, plain text, \
no markdown) summarizing today's spending. Lead with the single most interesting thing: \
a category running unusually hot or cold this month, a budget-pace observation, a \
recurring renewal, a new merchant, or — if nothing stands out — the largest item. \
Be specific: name the merchant or category and include one number. Write merchant \
names in title case ("Costco Wholesale", never "COSTCO WHOLESALE"), dropping \
processor prefixes and store numbers. Skip filler \
("today you spent…"). Stay neutral and observational, never alarmist.

Day: {day_of_week}, {date}
Today: {transaction_count} txn(s), ${day_total:.2f} — {top_items}
Month-to-date: ${mtd_total:.2f}, day {day_number}/{days_in_month} (expected pace: \
{expected_pace_pct:.0f}% of month elapsed; spend pace: {actual_pace_line})
Budget: {budget_line}
Top MTD categories: {top_categories}
6-month avg monthly spend: {trend_avg_line}
Notable categories this month vs last: {category_deltas_line}
Quiet anomalies flagged this month: {anomalies_line}"""

BATCH_PROMPT_TEMPLATE = """\
Here is daily spending data for {month}:

<daily_data>
{context_json}
</daily_data>

For each day, write ONE short sentence (≤25 words, plain text, no markdown) summarizing \
that day. Lead with the single most interesting thing — a hot/cold category, a \
budget-pace observation, a recurring renewal, a new merchant, or the largest item. \
Be specific: name the merchant or category and include one number. Write merchant \
names in title case ("Costco Wholesale", never "COSTCO WHOLESALE"), dropping \
processor prefixes and store numbers. Skip filler. Stay \
neutral and observational, never alarmist.

Output format — one section per day, headed by the date:

## 2026-04-15
Summary text here.

## 2026-04-14
Summary text here.
"""


class DaySummaryResult(BaseModel):
    """Structured output for a single day summary via instructor."""

    summary: str = Field(description="single sentence, ≤25 words, plain text")


def prepare_template_fields(ctx: dict[str, Any]) -> dict[str, Any]:
    """Derive the format-ready fields used by DAY_PROMPT_TEMPLATE.

    Tolerates missing monthly-context fields (anomalies, trend, deltas) so the
    prompt structure stays stable when the enrichment pipeline can't run.

    Exposed publicly so tools (e.g., the prompt eval harness) can reuse the
    derivations while swapping in a different template.
    """
    txns = ctx.get("transactions", [])
    top_items = (
        ", ".join(
            f"${t['amount']:.2f} {t['company']}" for t in sorted(txns, key=lambda t: t["amount"], reverse=True)[:3]
        )
        or "none"
    )

    mtd_cats = ctx.get("mtd_by_category", {})
    top_categories = (
        ", ".join(f"{cat} ${amt:.2f}" for cat, amt in sorted(mtd_cats.items(), key=lambda x: x[1], reverse=True)[:3])
        or "none"
    )

    ceiling = ctx.get("budget_ceiling_monthly")
    actual_pace_pct = ctx.get("actual_pace_pct")
    if ceiling and actual_pace_pct is not None:
        budget_line = f"{actual_pace_pct:.0f}% of ${ceiling:.0f}/month used"
        actual_pace_line = f"{actual_pace_pct:.0f}% of monthly ceiling"
    else:
        budget_line = "not configured"
        actual_pace_line = "n/a (no budget set)"

    trend_avg = ctx.get("trend_avg_6mo")
    trend_avg_line = f"${trend_avg:,.0f}" if trend_avg else "n/a"

    deltas = ctx.get("category_deltas_top") or []
    if deltas:
        category_deltas_line = ", ".join(
            f"{d['category']} ${d['current']:.0f} vs ${d['previous']:.0f}"
            + (f" ({d['delta_pct']:+.0f}%)" if d.get("delta_pct") is not None else "")
            for d in deltas
        )
    else:
        category_deltas_line = "no major shifts"

    anomalies = ctx.get("top_anomalies") or []
    if anomalies:
        anomalies_line = "; ".join(f"{a['category']}: {a['reason']}" for a in anomalies)
    else:
        anomalies_line = "none flagged"

    return {
        "day_of_week": ctx["day_of_week"],
        "date": ctx["date"],
        "transaction_count": ctx["transaction_count"],
        "day_total": ctx["day_total"],
        "top_items": top_items,
        "mtd_total": ctx["mtd_total"],
        "day_number": ctx["month_day_number"],
        "days_in_month": ctx["month_total_days"],
        "expected_pace_pct": ctx.get("expected_pace_pct", 0.0),
        "actual_pace_line": actual_pace_line,
        "budget_line": budget_line,
        "top_categories": top_categories,
        "trend_avg_line": trend_avg_line,
        "category_deltas_line": category_deltas_line,
        "anomalies_line": anomalies_line,
    }


def build_day_prompt(ctx: dict[str, Any]) -> str:
    """Render DAY_PROMPT_TEMPLATE from a context dict."""
    return DAY_PROMPT_TEMPLATE.format(**prepare_template_fields(ctx))


class SummaryProvider(ABC):
    """Abstract base for AI summary providers."""

    @abstractmethod
    async def generate_summaries(
        self,
        day_contexts: list[dict[str, Any]],
        on_complete: Callable[[str, str], None] | None = None,
    ) -> dict[str, str]:
        """Generate summaries for multiple days.

        Returns {date_str: summary_text}.
        on_complete is called with (date, summary) as each day finishes.
        """


class OpenAISummaryProvider(SummaryProvider):
    """Uses instructor + OpenAI API for structured per-day output."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_OPENAI_CHAT_MODEL,
        reasoning_effort: str | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.reasoning_effort = reasoning_effort

    async def generate_summaries(
        self,
        day_contexts: list[dict[str, Any]],
        on_complete: Callable[[str, str], None] | None = None,
    ) -> dict[str, str]:
        import instructor
        from openai import OpenAI

        client = instructor.from_openai(OpenAI(api_key=self.api_key))
        results: dict[str, str] = {}
        # reasoning_effort is a passthrough OpenAI param — only send it when set
        # so a None keeps the model's default.
        extra: dict[str, Any] = {"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}

        for ctx in day_contexts:
            date = ctx["date"]
            prompt = self._build_prompt(ctx)
            try:
                result = await asyncio.to_thread(
                    client.chat.completions.create,
                    model=self.model,
                    response_model=DaySummaryResult,
                    messages=[{"role": "user", "content": prompt}],
                    **extra,
                )
                results[date] = result.summary
                if on_complete:
                    on_complete(date, result.summary)
            except Exception:
                logger.exception("OpenAI summary generation failed for %s", date)

        return results

    def _build_prompt(self, ctx: dict[str, Any]) -> str:
        return build_day_prompt(ctx)


def _parse_sections(text: str) -> dict[str, str]:
    """Parse ``## YYYY-MM-DD`` headed sections into a ``{date: summary}`` dict."""
    pattern = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    results: dict[str, str] = {}
    for i, match in enumerate(matches):
        date = match.group(1)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        summary = text[start:end].strip()
        if summary:
            results[date] = summary
    return results


class _CLISummaryProvider(SummaryProvider):
    """Shared model/effort init for the CLI-backed summary providers.

    Each concrete provider sets ``provider_name`` and keeps its own
    ``generate_summaries`` (they differ only in the log label); the optional
    ``model`` / ``reasoning_effort`` thread straight through to
    ``run_cli_provider`` (``None`` = provider default).
    """

    provider_name: str

    def __init__(self, model: str | None = None, reasoning_effort: str | None = None) -> None:
        self.model = model
        self.reasoning_effort = reasoning_effort


class ClaudeCLISummaryProvider(_CLISummaryProvider):
    """Spawns Claude Code subprocess, batches all days in one prompt."""

    provider_name = "claude_cli"

    async def generate_summaries(
        self,
        day_contexts: list[dict[str, Any]],
        on_complete: Callable[[str, str], None] | None = None,
    ) -> dict[str, str]:
        month = day_contexts[0]["date"][:7] if day_contexts else "unknown"
        context_json = json.dumps(day_contexts, indent=2)
        prompt = BATCH_PROMPT_TEMPLATE.format(month=month, context_json=context_json)

        logger.info("Generating %d day summaries via Claude Code", len(day_contexts))
        full_text = await run_cli_provider(
            self.provider_name, prompt, model=self.model, reasoning_effort=self.reasoning_effort
        )

        results = _parse_sections(full_text)
        if on_complete:
            for date, summary in results.items():
                on_complete(date, summary)
        return results


class CodexCLISummaryProvider(_CLISummaryProvider):
    """Spawns OpenAI Codex subprocess, batches all days in one prompt."""

    provider_name = "codex"

    async def generate_summaries(
        self,
        day_contexts: list[dict[str, Any]],
        on_complete: Callable[[str, str], None] | None = None,
    ) -> dict[str, str]:
        month = day_contexts[0]["date"][:7] if day_contexts else "unknown"
        context_json = json.dumps(day_contexts, indent=2)
        prompt = BATCH_PROMPT_TEMPLATE.format(month=month, context_json=context_json)

        logger.info("Generating %d day summaries via OpenAI Codex", len(day_contexts))
        full_text = await run_cli_provider(
            self.provider_name, prompt, model=self.model, reasoning_effort=self.reasoning_effort
        )

        results = _parse_sections(full_text)
        if on_complete:
            for date, summary in results.items():
                on_complete(date, summary)
        return results


class GeminiCLISummaryProvider(_CLISummaryProvider):
    """Spawns Google Gemini CLI subprocess, batches all days in one prompt."""

    provider_name = "gemini_cli"

    async def generate_summaries(
        self,
        day_contexts: list[dict[str, Any]],
        on_complete: Callable[[str, str], None] | None = None,
    ) -> dict[str, str]:
        month = day_contexts[0]["date"][:7] if day_contexts else "unknown"
        context_json = json.dumps(day_contexts, indent=2)
        prompt = BATCH_PROMPT_TEMPLATE.format(month=month, context_json=context_json)

        logger.info("Generating %d day summaries via Google Gemini", len(day_contexts))
        # Gemini ignores model / reasoning_effort; run_cli_provider drops them.
        full_text = await run_cli_provider(
            self.provider_name, prompt, model=self.model, reasoning_effort=self.reasoning_effort
        )

        results = _parse_sections(full_text)
        if on_complete:
            for date, summary in results.items():
                on_complete(date, summary)
        return results


def create_summary_provider(
    provider_name: str,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> SummaryProvider | None:
    """Factory for summary providers. Returns None if unavailable.

    ``model`` / ``reasoning_effort`` (``None`` = provider default) thread through
    to the chosen provider: the OpenAI API model falls back to
    ``DEFAULT_OPENAI_CHAT_MODEL``, and the CLI providers forward both to
    ``run_cli_provider``.
    """
    if provider_name == "openai":
        try:
            from src.finance.secrets import get_openai_api_key

            api_key = get_openai_api_key()
            return OpenAISummaryProvider(
                api_key=api_key,
                model=model or DEFAULT_OPENAI_CHAT_MODEL,
                reasoning_effort=reasoning_effort,
            )
        except RuntimeError:
            logger.warning("OpenAI API key not available")
            return None
    elif provider_name == "claude_cli":
        if shutil.which("claude"):
            return ClaudeCLISummaryProvider(model=model, reasoning_effort=reasoning_effort)
        logger.warning("Claude Code not found in PATH")
        return None
    elif provider_name == "codex":
        if _codex_signed_in():
            return CodexCLISummaryProvider(model=model, reasoning_effort=reasoning_effort)
        logger.warning("OpenAI Codex not available (binary missing or not signed in)")
        return None
    elif provider_name == "gemini_cli":
        if _gemini_signed_in():
            return GeminiCLISummaryProvider(model=model, reasoning_effort=reasoning_effort)
        logger.warning("Google Gemini not available (binary missing or not signed in)")
        return None
    return None
