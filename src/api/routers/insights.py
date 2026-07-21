"""Insights endpoint: background task generation + polling."""

import asyncio
import contextlib
import json
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import get_budget_service, get_spending_summary, run_sync
from src.api.models.insights import (
    BriefingFigure,
    BriefingValidation,
    BriefingValidationSummary,
    InsightsContextResponse,
    InsightsGenerateResponse,
    InsightsStatusResponse,
    SavedInsightDetail,
    SavedInsightItem,
    SavedInsightListResponse,
)
from src.api.utils import MONTH_PATTERN
from src.finance.ai_cli import run_cli_provider
from src.finance.app_config import get_config
from src.finance.app_timezone import now_local
from src.finance.briefing_validator import validate_briefing
from src.finance.insights_context import gather_context as gather_insights_context
from src.finance.insights_context import gather_context_to_file
from src.finance.protocols import IBudgetService, ISpendingSummary

_PROVIDER_LABELS = {
    "openai": "OpenAI",
    "claude_cli": "Claude Code",
    "codex": "OpenAI Codex",
    "gemini_cli": "Google Gemini",
}

MIN_INSIGHT_LENGTH = 200

logger = logging.getLogger(__name__)

router = APIRouter(tags=["insights"])

BRIEFING_PROMPT = """\
Here is structured spending data for {month}:

<spending_data>
{context_data}
</spending_data>

The data may include a `commented_transactions` array holding notes the reader wrote on \
specific transactions. These comments are ground truth about intent (e.g. "split with \
roommate", "one-time emergency repair", "gift for mom"). Use them to explain what a number \
means, not to raise it as a concern: a category that jumped because of a comment like \
"one-time moving expense" is explained, not something to look into.

<data_notes>
Read these before interpreting any field:
- A company entry labelled "Unknown" is transactions without a recognized merchant name — \
not a single vendor and not something that "fails to reconcile". Do not describe it as an \
error to review.
- A company's `category` label reflects only one of possibly several categories its \
transactions fell under — treat it as indicative, not definitive.
- `pace` is the authoritative budget math. Every budget projection, variance, and \
year-to-date figure comes from there. `pace.ceiling.projected_adjusted` is the year-end \
estimate to cite; `projected_naive` is the distorted straight-line figure, shown only for \
contrast. In `pace.categories`, `assessment` of "ahead" means spending faster than the \
prorated target and "behind" means slower; the signed `variance_amount` is authoritative. \
Lumpy (annual) categories are assessed against the full-year target, not a monthly pace.
- `anomalies[].annotated_amount`, when present, is the portion of a change the reader already \
explained via a comment — mention the remainder, not the whole.
- `suspected_ignored`, when non-empty, lists transactions resembling ones usually marked \
ignored. Note it once, plainly, and only when non-empty; omit it otherwise.
- `same_month_last_year` is this month one year ago — a seasonal comparison, not a monthly \
one. Its `comments` are LAST YEAR's annotations; cite them as historical context ("property \
tax arrived, as it did last May"), never as facts about the current month.
- `recurring_annual` lists categories that historically bill around this time of year. An \
arrival in one of these is expected seasonal timing, not a change worth singling out.
- `fixed_charges` are stable recurring items (mortgage, strata, childcare and the like). \
Mention them collectively in at most one line — do not re-explain each one — unless one \
actually changed from its usual amount.
- `previous_briefing`, when present, is last month's briefing. Follow up on what it raised: \
say whether each item resolved, persists, or grew. Continuity sentences ("groceries returned \
to target after last month's overage") are among the most valuable output. Never carry a \
dollar figure from the excerpt into this month's numbers — use it only for continuity.
- `user_memo`, when present, is free-text standing context the reader wrote about their own \
situation. Treat it as ground truth and let it shape interpretation.

Every dollar amount and percentage in the briefing must appear verbatim in the data above. \
Do not derive, extrapolate, annualize, or compute any new figure. All pace and projection \
numbers come from `pace`; the year-end figure is always `pace.ceiling.projected_adjusted`, \
never `projected_naive`. If a number you want is not in the data, do not state it.
</data_notes>

Write a spending briefing addressed to the reader — the person whose money this is. The \
sections and rules below are fixed; follow them exactly so every month reads as the work of \
the same steady hand.

VOICE
- Second person, present tense: "you spent", "your groceries", "this month" — always writing \
to the reader, never about them in the third person, and never as "I" or "we".
- Observe, do not judge. State the number and what it shows. No praise, no scolding, no \
"good" or "bad", no "should".
- Phrase anything actionable as an option the reader has, not an instruction: "an auto-ignore \
rule would keep these transfers out of your totals", not "you should review these"; "the \
Mapletrade line reads like an investment move rather than spending — a category override would \
keep it out of the total", not "this needs to be reviewed".
- No exclamation marks, and none of the alarm words a nervous bank reaches for — no "alert", \
no "warning", no "urgent". A large or unusual number is stated plainly and left to speak for \
itself.
- Section headers are sentence case, exactly as written below, at the `##` level.

ACTIONS AVAILABLE IN TIDINGS
When a finding maps to one of these, you may name it in passing — never as a command, and no \
more than two or three across the whole briefing:
- Annotate a transaction with a comment, on the Journal page, to record intent.
- Set a category override or an auto-ignore rule, on the Categorize page, to fix where a \
transaction lands or keep transfers and payments out of totals.
- Adjust a budget target, on the Budgets page.
- Update the standing briefing memo, in Settings → Intelligence.

SECTIONS

## The month in brief
One or two sentences: the month's total, its direction against last month, and the single \
thing that most explains it. No bullets.

## What changed
Three to five bullets on the month's most notable movements — against last month, the \
six-month trend, budget pace, and historical averages. When `previous_briefing` is present, \
the first bullet follows up on what it raised: resolved, still here, or larger. Connect \
categories rather than restating the table below.

## Where the month went
A short lead sentence, then exactly one table covering the top three to five categories by \
spending. Use these columns and no others:

| Category | This month | Last month | Pace | Notable merchants |

Fill "Pace" with the plain read from `pace` — "on target", "ahead of pace", "$210 over \
target", or "—" where no target exists. Do not add columns, a totals row, or a second table \
anywhere in the briefing.

## Worth attention
Two to four bullets on the month's outliers: a category well past its pace, a spend far above \
its six-month norm, a category that fell to zero, or a single merchant carrying most of a \
category. State each as a fact with its number, and leave out anything a comment already \
explains. Mention `suspected_ignored` here in a single line only when it is non-empty. Omit \
this whole section when nothing qualifies.

## Your notes
Include only when `commented_transactions` is non-empty. Two to four bullets on what you \
annotated and how it shapes the month, grouping related comments. Omit this whole section \
when there are no comments.

## Looking ahead
Two to four sentences. If the month is still partial, give the projected month-end total from \
the data. Otherwise look to year-end with `pace.ceiling.projected_adjusted` against the \
ceiling, and name the categories most in play. Frame next steps as options the reader has, \
not tasks.

FORMATTING
- Plain markdown. Do not use bold anywhere — not for amounts, not for labels. The single \
table above is the only table; everything else is prose and bullets.
- Keep the prose outside the table to roughly 350-500 words.
- Every figure appears verbatim from the data; the year-end number is always \
`pace.ceiling.projected_adjusted`.
- Print figures the way a bank statement would, without changing their value: thousands \
separators and two decimals or none — $14,407.60 or $14,408, never a raw $14407.6, $1348.0, \
or $0.0. Percentages keep at most one decimal: 19.2%, not 19.22%."""

# --- Background generation state (single-user, single slot) ---

_generation_state: dict[str, Any] = {"status": "idle"}
_generation_task: asyncio.Task[None] | None = None


@router.post(
    "/insights/generate",
    status_code=202,
    response_model=InsightsGenerateResponse,
    operation_id="generateInsights",
    summary="Kick off background AI generation of a monthly spending briefing",
)
async def generate_insights(
    month: str = Query(..., pattern=MONTH_PATTERN),
    spending_summary: ISpendingSummary = Depends(get_spending_summary),
    budget_service: IBudgetService = Depends(get_budget_service),
):
    global _generation_task, _generation_state

    if _generation_state["status"] == "running":
        raise HTTPException(409, "Generation already in progress")

    _generation_state = {
        "status": "running",
        "month": month,
        "started_at": now_local().isoformat(),
    }
    _generation_task = asyncio.create_task(_run_generation(month, spending_summary, budget_service))
    return InsightsGenerateResponse(status="running", month=month)


@router.get(
    "/insights/status",
    response_model=InsightsStatusResponse,
    operation_id="getInsightsGenerationStatus",
    summary="Background generation status (idle/running/error)",
)
async def get_insights_status() -> dict[str, Any]:
    return _generation_state


@router.get(
    "/insights/context",
    response_model=InsightsContextResponse,
    operation_id="getInsightsContext",
    summary="Raw context dict the AI briefing uses (for inspection / external automation)",
)
async def get_insights_context(
    month: str = Query(..., pattern=MONTH_PATTERN, description="Month in YYYY-MM format."),
    spending_summary: ISpendingSummary = Depends(get_spending_summary),
    budget_service: IBudgetService = Depends(get_budget_service),
):
    """Return the raw context the AI briefing uses.

    Same dict that ``gather_context_to_file`` persists for the generation
    worker — exposed over HTTP so external consumers (Claude agents, the
    frontend transparency panel, future automation) can inspect the inputs
    without re-running the aggregation.
    """
    return await gather_insights_context(
        month,
        spending_summary=spending_summary,
        budget_service=budget_service,
    )


async def _run_openai_briefing(prompt: str, model: str | None, reasoning_effort: str | None) -> str:
    """Run the insights briefing through the OpenAI chat API.

    Requires an OpenAI key; raises ``RuntimeError`` (surfaced as an "Analysis
    failed" state by the caller) when the key is missing or the call fails, so
    the openai path mirrors the CLI paths' error handling.
    """
    from src.finance.ai_cli import DEFAULT_OPENAI_CHAT_MODEL
    from src.finance.openai_client import OpenAIClient
    from src.finance.secrets import get_openai_api_key

    try:
        api_key = get_openai_api_key()
    except RuntimeError as e:
        raise RuntimeError("OpenAI is selected for insights but no API key is configured.") from e

    client = OpenAIClient(model=model or DEFAULT_OPENAI_CHAT_MODEL, api_key=api_key)
    response = await asyncio.to_thread(
        client.chat, [{"role": "user", "content": prompt}], reasoning_effort=reasoning_effort
    )
    if response is None:
        raise RuntimeError(f"The OpenAI request failed: {client.last_error}")
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("The OpenAI reply was empty.")
    return content


async def run_briefing_provider(
    provider_name: str,
    prompt: str,
    *,
    model: str | None,
    reasoning_effort: str | None,
    timeout: int = 180,
) -> str:
    """Dispatch a briefing prompt to the configured provider and return the text.

    Single source of truth for the OpenAI-API-vs-CLI split: the OpenAI path goes
    through :func:`_run_openai_briefing`, every CLI provider through
    ``run_cli_provider``. The names are resolved from this module's globals at
    call time, so tests that patch ``src.api.routers.insights._run_openai_briefing``
    / ``run_cli_provider`` still intercept the calls. The ``dev/cli/regen_insights.py``
    eval harness imports this so it exercises the exact same code path the router
    does. Raises ``RuntimeError`` on provider failure.
    """
    if provider_name == "openai":
        return await _run_openai_briefing(prompt, model, reasoning_effort)
    return await run_cli_provider(
        provider_name, prompt, timeout=timeout, model=model, reasoning_effort=reasoning_effort
    )


def validate_and_persist_briefing(
    markdown: str,
    context_json: str,
    insights_dir: Path,
    ts: str,
) -> bool | None:
    """Validate a saved briefing's figures and write the sidecar next to the ``.md``.

    Reuses the context that fed the prompt (``context_json`` — the same JSON
    written to the tmp file), so no re-gather. Persists the full per-figure
    result to ``<ts>.validation.json`` and logs a warning listing any figures
    that do not trace back to the context. Returns the ``ok`` verdict, or
    ``None`` when the context JSON is unavailable/unparseable (validation
    skipped, the briefing is still saved).
    """
    try:
        context = json.loads(context_json)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Briefing figure validation skipped: context JSON unavailable")
        return None

    result = validate_briefing(markdown, context)
    sidecar = insights_dir / f"{ts}.validation.json"
    sidecar.write_text(json.dumps(result.to_sidecar_dict(), indent=2) + "\n")

    if not result.ok:
        logger.warning(
            "Briefing has %d figure(s) not found in the context: %s",
            result.unmatched_count,
            [v.figure.raw for v in result.unmatched],
        )
    return result.ok


async def _run_generation(
    month: str,
    spending_summary: ISpendingSummary,
    budget_service: IBudgetService,
) -> None:
    global _generation_state
    tmp_path = None
    try:
        # Phase 1: Gather data
        logger.info("Insights generation starting for month=%s", month)
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="insights_")
        os.close(tmp_fd)

        await run_sync(
            gather_context_to_file,
            month,
            output_path=tmp_path,
            spending_summary=spending_summary,
            budget_service=budget_service,
        )
        logger.info("Context gathered, wrote %s", tmp_path)

        # Phase 2: Run the configured insights provider (OpenAI API or a CLI).
        config = get_config()
        provider_name = config.get("insights_provider", "disabled")
        model = config.get("insights_model")
        reasoning_effort = config.get("insights_reasoning_effort")
        if provider_name == "disabled":
            msg = "No insights provider is configured. Choose one in Settings → Intelligence."
            logger.error(msg)
            _generation_state = {"status": "error", "month": month, "error": msg}
            return

        label = _PROVIDER_LABELS.get(provider_name, provider_name)
        context_data = Path(tmp_path).read_text()
        prompt = BRIEFING_PROMPT.format(context_data=context_data, month=month)

        try:
            full_text = await run_briefing_provider(
                provider_name, prompt, model=model, reasoning_effort=reasoning_effort, timeout=180
            )
        except RuntimeError as e:
            logger.exception("%s failed", label)
            _generation_state = {
                "status": "error",
                "month": month,
                "error": f"Analysis failed: {str(e)[:200]}",
            }
            return

        _diag = {"provider": provider_name, "stdout_len": len(full_text)}

        if full_text.startswith("Error:"):
            logger.error("%s returned error in stdout: %s", label, full_text[:300])
            _generation_state = {
                "status": "error",
                "month": month,
                "error": f"Analysis failed: {full_text.strip()[:200]}",
                "_diag": _diag,
            }
            return

        # Save insight to disk (only if substantive)
        if full_text and len(full_text) >= MIN_INSIGHT_LENGTH:
            insights_dir = Path("data/insights") / month
            insights_dir.mkdir(parents=True, exist_ok=True)
            ts = now_local().strftime("%Y-%m-%d_%H-%M-%S")
            filepath = insights_dir / f"{ts}.md"
            filepath.write_text(full_text)
            logger.info("Saved insight to %s via %s", filepath, label)

            # A flagged briefing is still saved; the figure check rides alongside
            # as a sidecar, reusing the context that fed the prompt (no re-gather).
            figures_ok = validate_and_persist_briefing(full_text, context_data, insights_dir, ts)
            if figures_ok is not None:
                _diag["figures_ok"] = figures_ok
        elif full_text:
            logger.warning("Insight too short to save (%d chars), skipping", len(full_text))

        _generation_state = {"status": "idle", "_diag": _diag}
        logger.info("Insights generation complete via %s: %d chars", label, len(full_text))

    except Exception as e:
        logger.exception("Insights generation error")
        _generation_state = {
            "status": "error",
            "month": month,
            "error": str(e),
        }
    finally:
        if tmp_path:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


# --- Saved insights endpoints ---

_INSIGHT_ID_RE = re.compile(r"^\d{8}T\d{6}$|^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$")


def _parse_dt(stem: str) -> datetime:
    """Parse insight filename stem into datetime for sorting."""
    if "T" in stem:
        return datetime.strptime(stem, "%Y%m%dT%H%M%S")  # noqa: DTZ007 — filename-stem round-trip, naive by construction, sort/format only
    return datetime.strptime(stem, "%Y-%m-%d_%H-%M-%S")  # noqa: DTZ007 — filename-stem round-trip, naive by construction, sort/format only


def _parse_ts(stem: str) -> str:
    """Parse insight filename stem into ISO timestamp."""
    dt = _parse_dt(stem)
    if "T" in stem:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _sidecar_path(md_path: Path) -> Path:
    """The ``<stem>.validation.json`` sidecar path for a saved ``.md``."""
    return md_path.with_name(f"{md_path.stem}.validation.json")


def _read_sidecar(md_path: Path) -> dict[str, Any] | None:
    """Load a briefing's validation sidecar, or None when absent/unreadable."""
    sidecar = _sidecar_path(md_path)
    if not sidecar.is_file():
        return None
    try:
        data = json.loads(sidecar.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _figures_ok(md_path: Path) -> bool | None:
    """Lightweight ``ok`` verdict from a briefing's sidecar, or None when absent."""
    data = _read_sidecar(md_path)
    if data is None:
        return None
    ok = data.get("ok")
    return ok if isinstance(ok, bool) else None


def _load_validation(md_path: Path) -> BriefingValidation | None:
    """Project a briefing's sidecar onto the API model (summary + unmatched only)."""
    data = _read_sidecar(md_path)
    if data is None:
        return None
    summary = data.get("summary") or {}
    unmatched = [
        BriefingFigure(
            raw=fig["raw"],
            kind=fig["kind"],
            value=fig["value"],
            snippet=fig.get("snippet", ""),
        )
        for fig in data.get("figures", [])
        if not fig.get("matched", True)
    ]
    return BriefingValidation(
        ok=bool(data.get("ok", True)),
        summary=BriefingValidationSummary(
            total=int(summary.get("total", 0)),
            matched=int(summary.get("matched", 0)),
            unmatched=int(summary.get("unmatched", 0)),
        ),
        unmatched=unmatched,
    )


@router.get(
    "/insights/saved",
    response_model=SavedInsightListResponse,
    operation_id="listSavedInsights",
    summary="List saved insight briefings for a month",
)
async def list_saved_insights(month: str = Query(..., pattern=MONTH_PATTERN)) -> SavedInsightListResponse:
    insights_dir = Path("data/insights") / month
    if not insights_dir.is_dir():
        return SavedInsightListResponse(items=[], count=0)
    files = [f for f in insights_dir.glob("*.md") if _INSIGHT_ID_RE.match(f.stem)]
    files.sort(key=lambda f: _parse_dt(f.stem), reverse=True)
    items = [
        SavedInsightItem(
            id=f.stem,
            month=month,
            generated_at=_parse_ts(f.stem),
            figures_ok=_figures_ok(f),
        )
        for f in files
    ]
    return SavedInsightListResponse(items=items, count=len(items))


@router.get(
    "/insights/saved/{insight_id}",
    response_model=SavedInsightDetail,
    operation_id="getSavedInsight",
    summary="Get the markdown content of a saved insight briefing",
)
async def get_saved_insight(
    insight_id: str,
    month: str = Query(..., pattern=MONTH_PATTERN),
):
    if not _INSIGHT_ID_RE.match(insight_id):
        # Malformed opaque id → treat as not found (matches parse_tx_id).
        raise HTTPException(404, "Invalid insight ID")
    filepath = Path("data/insights") / month / f"{insight_id}.md"
    if not filepath.is_file():
        raise HTTPException(404, "Insight not found")
    return SavedInsightDetail(
        id=insight_id,
        month=month,
        generated_at=_parse_ts(insight_id),
        content=filepath.read_text(),
        validation=_load_validation(filepath),
    )
