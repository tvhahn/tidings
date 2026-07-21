"""Run a Variant against a single (date, sample_idx) and write a cache cell.

Cache cell schema (one JSON file per ``(variant, date, sample_idx)``):

    data/eval-harness/cache/<variant.name>__<YYYY-MM-DD>__<sample_idx>.json

Editing a Variant's prompt_template / context_field_set / model produces a new
``Variant.hash()`` → only that variant's cells are flagged stale on next read.
Other cells are untouched.

CLI smoke test (per spec §13):
    python -m dev.eval_harness.runner V0_baseline 2026-04-01 1 --demo
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dev.eval_harness.variants import get_variant
from dev.eval_harness.windowed_context import gather_as_of
from src.finance.summary_provider import prepare_template_fields, run_cli_provider

if TYPE_CHECKING:
    from collections.abc import Iterable

    from dev.eval_harness.variants import Variant

logger = logging.getLogger(__name__)

CACHE_DIR = Path("data/eval-harness/cache")
JOURNAL_DIR = Path("data/journal")


def cache_path(variant_name: str, day: str, sample_idx: int) -> Path:
    return CACHE_DIR / f"{variant_name}__{day}__{sample_idx}.json"


def _filter_ctx(ctx: dict[str, Any], keep_keys: Iterable[str]) -> dict[str, Any]:
    keep = set(keep_keys)
    return {k: v for k, v in ctx.items() if k in keep}


def _load_prior_summaries(month: str, target_date: str, n: int) -> list[tuple[str, str]]:
    """Return up to N (date, summary_text) pairs for days strictly before
    ``target_date``, newest-first. Missing files are silently skipped (April
    has gaps at 07, 13, 18 in this repo)."""
    target_day = int(target_date.rsplit("-", maxsplit=1)[-1])
    pairs: list[tuple[str, str]] = []
    for offset in range(1, target_day):
        day_n = target_day - offset
        path = JOURNAL_DIR / month / f"{day_n:02d}.txt"
        if not path.exists():
            continue
        text = path.read_text().strip()
        if not text:
            continue
        date_str = f"{month}-{day_n:02d}"
        pairs.append((date_str, text))
        if len(pairs) >= n:
            break
    return pairs


def render_prompt(variant: Variant, day_ctx: dict[str, Any]) -> str:
    """Apply variant's context filter, render the template, optionally prepend
    a Recent days block for V5_continuity-style variants."""
    filtered = _filter_ctx(day_ctx, variant.context_field_set)
    fields = prepare_template_fields(filtered)
    body = variant.prompt_template.format(**fields)

    if variant.prior_day_summaries > 0:
        month = day_ctx["date"][:7]
        prior = _load_prior_summaries(month, day_ctx["date"], variant.prior_day_summaries)
        if prior:
            block = "Recent days:\n" + "\n".join(f"- {d}: {t}" for d, t in prior)
            body = f"{block}\n\n{body}"
    return body


async def run_variant(variant: Variant, day_ctx: dict[str, Any], sample_idx: int) -> Path:
    """Render → invoke CLI → parse → write cache cell. Returns cache path."""
    rendered = render_prompt(variant, day_ctx)
    output_raw = await run_cli_provider("claude_cli", rendered, model=variant.model)

    parse_error: str | None = None
    output_parsed: str | None
    try:
        output_parsed = variant.parse(output_raw)
    except Exception as exc:
        output_parsed = None
        parse_error = f"{type(exc).__name__}: {exc}"

    cell = {
        "variant_name": variant.name,
        "prompt_hash": f"sha256:{variant.hash()}",
        "rendered_prompt": rendered,
        "context_snapshot": {k: day_ctx.get(k) for k in variant.context_field_set},
        "transaction_snapshot": day_ctx.get("transactions", []),
        "model": variant.model,
        "output_raw": output_raw,
        "output_parsed": output_parsed,
        "parse_error": parse_error,
        "sample_idx": sample_idx,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = cache_path(variant.name, day_ctx["date"], sample_idx)
    out.write_text(json.dumps(cell, indent=2, ensure_ascii=False))
    return out


def read_cell(variant_name: str, day: str, sample_idx: int) -> dict[str, Any] | None:
    path = cache_path(variant_name, day, sample_idx)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        logger.warning("Corrupt cache cell %s; treating as missing.", path)
        return None


def cell_is_fresh(cell: dict[str, Any], variant: Variant) -> bool:
    return cell.get("prompt_hash") == f"sha256:{variant.hash()}"


def list_existing_samples(variant_name: str, day: str) -> list[int]:
    """Return all sample indices already cached for a (variant, day)."""
    if not CACHE_DIR.exists():
        return []
    prefix = f"{variant_name}__{day}__"
    out: list[int] = []
    for p in CACHE_DIR.glob(f"{prefix}*.json"):
        try:
            idx = int(p.stem.rsplit("__", 1)[1])
        except (ValueError, IndexError):
            continue
        out.append(idx)
    out.sort()
    return out


def next_sample_idx(variant_name: str, day: str) -> int:
    """Sample indices are 1-based per spec §9 (``__1.json``, ``__2.json``, …).
    Returns 1 when no samples exist; otherwise ``max(existing) + 1``."""
    existing = list_existing_samples(variant_name, day)
    return (existing[-1] + 1) if existing else 1


async def _async_main(args: argparse.Namespace) -> int:
    variant = get_variant(args.variant)
    year_month, day_n = args.date[:7], int(args.date.split("-")[-1])

    spending_summary = None
    budget_service = None
    if args.demo:
        from src.finance.budget_service_local import BudgetServiceLocal
        from src.finance.spending_summary_local import SpendingSummaryLocal

        spending_summary = SpendingSummaryLocal(db_path=Path("data/demo.db"))
        budget_service = BudgetServiceLocal(db_path=Path("data/demo.db"), user_id="default")

    try:
        ctx = await gather_as_of(year_month, day_n, spending_summary=spending_summary, budget_service=budget_service)
    except LookupError as exc:
        print(f"skip: {exc}", file=sys.stderr)
        return 2
    path = await run_variant(variant, ctx, args.sample_idx)
    print(str(path))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dev.eval_harness.runner")
    parser.add_argument("variant", help="Variant name, e.g., V0_baseline")
    parser.add_argument("date", help="Day to evaluate, e.g., 2026-04-01")
    parser.add_argument("sample_idx", nargs="?", type=int, default=1, help="Sample index (1-based; default 1)")
    parser.add_argument("--demo", action="store_true", help="Use data/demo.db instead of configured storage")
    args = parser.parse_args(argv)
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
