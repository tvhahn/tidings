"""Regenerate monthly AI briefings for one or more months — the prompt eval harness.

Usage:
    uv run dev/cli/regen_insights.py 2026-03 2026-04 2026-05 [--dry-run]

For each month this gathers fresh context (via the same
``gather_context_to_file`` the API worker uses), assembles the CURRENT
``BRIEFING_PROMPT``, runs the configured insights provider through the router's
``run_briefing_provider`` (the exact dispatch the live generation path uses),
validates every figure against the context with
``src.finance.briefing_validator``, and saves ``<ts>.md`` + ``<ts>.validation.json``
under ``data/insights/<month>/`` — so the newest briefing simply appears in the
UI. It prints a per-month report (provider, duration, word count, sections,
figures matched/unmatched with snippets, and previous-vs-new file pointers for
eyeballing a diff).

``--dry-run`` gathers context and prints the assembled prompt size, then stops
before any provider call — safe to run without credentials.

Maintainer-only, not shipped UX. Live provider runs are left to the operator;
this module's pure parts (prompt assembly, section scan, report formatting) are
unit-tested with the provider mocked (``tests/unit/test_regen_insights_cli.py``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from src.api.routers.insights import (
    BRIEFING_PROMPT,
    run_briefing_provider,
)
from src.finance.app_config import get_config
from src.finance.app_timezone import now_local
from src.finance.briefing_validator import ValidationResult, validate_briefing
from src.finance.insights_context import gather_context_to_file

# Saved-briefing filename stems, mirrored from the router's _INSIGHT_ID_RE.
_STEM_RE = re.compile(r"^\d{8}T\d{6}$|^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested)
# --------------------------------------------------------------------------- #


def assemble_prompt(month: str, context_json: str) -> str:
    """Build the current briefing prompt for ``month`` from its context JSON.

    Identical to what the API worker formats — the single ``BRIEFING_PROMPT`` is
    imported from the router so the eval harness never drifts from production.
    """
    return BRIEFING_PROMPT.format(context_data=context_json, month=month)


def find_sections(markdown: str) -> list[str]:
    """The ``##``-level section headers present in a briefing, in order."""
    return [m.group(1).strip() for m in re.finditer(r"^##\s+(.+?)\s*$", markdown, re.MULTILINE)]


def word_count(markdown: str) -> int:
    """Whitespace-delimited word count of the briefing markdown."""
    return len(markdown.split())


@dataclass
class MonthReport:
    """Everything the per-month console report renders from."""

    month: str
    dry_run: bool
    context_path: str
    prompt_chars: int
    provider: str = ""
    duration_s: float = 0.0
    words: int = 0
    sections: list[str] = field(default_factory=list)
    matched: int = 0
    unmatched_figures: list[tuple[str, str]] = field(default_factory=list)  # (raw, snippet)
    total_figures: int = 0
    previous_path: str | None = None
    new_path: str | None = None


def format_report(report: MonthReport) -> str:
    """Render a :class:`MonthReport` to the multi-line console block."""
    lines = [f"── {report.month} " + "─" * max(0, 40 - len(report.month))]
    lines.append(f"  context      {report.context_path}")
    lines.append(f"  prompt       {report.prompt_chars:,} chars")

    if report.dry_run:
        lines.append("  dry-run      provider call skipped")
        return "\n".join(lines)

    lines.append(f"  provider     {report.provider}")
    lines.append(f"  duration     {report.duration_s:.1f}s")
    lines.append(f"  words        {report.words}")
    sections = ", ".join(report.sections) if report.sections else "(none found)"
    lines.append(f"  sections     {sections}")

    ok = not report.unmatched_figures
    verdict = "all trace to context" if ok else f"{len(report.unmatched_figures)} not in context"
    lines.append(f"  figures      {report.matched}/{report.total_figures} matched — {verdict}")
    for raw, snippet in report.unmatched_figures:
        lines.append(f"    ✗ {raw}  …{snippet}…")

    lines.append(f"  previous     {report.previous_path or '(none)'}")
    lines.append(f"  new          {report.new_path}")
    return "\n".join(lines)


def build_generation_report(
    *,
    month: str,
    context_path: str,
    prompt: str,
    provider: str,
    duration_s: float,
    markdown: str,
    result: ValidationResult,
    previous_path: str | None,
    new_path: str,
) -> MonthReport:
    """Assemble the post-generation report from the briefing + validation result."""
    return MonthReport(
        month=month,
        dry_run=False,
        context_path=context_path,
        prompt_chars=len(prompt),
        provider=provider,
        duration_s=duration_s,
        words=word_count(markdown),
        sections=find_sections(markdown),
        matched=result.matched_count,
        total_figures=result.total,
        unmatched_figures=[(v.figure.raw, v.figure.snippet) for v in result.unmatched],
        previous_path=previous_path,
        new_path=new_path,
    )


# --------------------------------------------------------------------------- #
# I/O (not unit-tested — driven live by the operator)
# --------------------------------------------------------------------------- #


def _newest_briefing_path(insights_dir: Path) -> str | None:
    """Path of the current newest saved ``.md`` in ``insights_dir``, or None."""
    if not insights_dir.is_dir():
        return None
    files = [f for f in insights_dir.glob("*.md") if _STEM_RE.match(f.stem)]
    if not files:
        return None
    files.sort(key=lambda f: f.stem, reverse=True)
    return str(files[0])


def regen_month(month: str, *, dry_run: bool) -> MonthReport:
    """Gather → (assemble → provider → validate → save) for a single month."""
    tmp = Path(tempfile.mkstemp(suffix=f"_context_{month}.json", prefix="regen_")[1])
    gather_context_to_file(month, output_path=str(tmp))
    context_json = tmp.read_text()
    prompt = assemble_prompt(month, context_json)

    if dry_run:
        return MonthReport(month=month, dry_run=True, context_path=str(tmp), prompt_chars=len(prompt))

    config = get_config()
    provider = config.get("insights_provider", "disabled")
    if provider == "disabled":
        raise SystemExit("No insights provider is configured (Settings → Intelligence).")
    model = config.get("insights_model")
    reasoning_effort = config.get("insights_reasoning_effort")

    insights_dir = Path("data/insights") / month
    previous_path = _newest_briefing_path(insights_dir)

    started = time.monotonic()
    markdown = asyncio.run(run_briefing_provider(provider, prompt, model=model, reasoning_effort=reasoning_effort))
    duration_s = time.monotonic() - started

    result = validate_briefing(markdown, json.loads(context_json))

    insights_dir.mkdir(parents=True, exist_ok=True)
    ts = now_local().strftime("%Y-%m-%d_%H-%M-%S")
    md_path = insights_dir / f"{ts}.md"
    md_path.write_text(markdown)
    (insights_dir / f"{ts}.validation.json").write_text(json.dumps(result.to_sidecar_dict(), indent=2) + "\n")

    return build_generation_report(
        month=month,
        context_path=str(tmp),
        prompt=prompt,
        provider=provider,
        duration_s=duration_s,
        markdown=markdown,
        result=result,
        previous_path=previous_path,
        new_path=str(md_path),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate monthly AI briefings (prompt eval harness)")
    parser.add_argument("months", nargs="+", help="One or more months in YYYY-MM format")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Gather context and print prompt size only — no provider call, nothing saved.",
    )
    args = parser.parse_args()

    for month in args.months:
        if not re.fullmatch(r"\d{4}-\d{2}", month):
            raise SystemExit(f"Invalid month: {month!r} (expected YYYY-MM)")
        report = regen_month(month, dry_run=args.dry_run)
        print(format_report(report))
        print()


if __name__ == "__main__":
    main()
