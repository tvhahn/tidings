"""Streamlit prompt evaluation harness — UI for ranking variants per day.

Run locally:
    uv sync --extra eval
    streamlit run dev/eval_harness/app.py

Layout follows spec §7. State persists across process restarts via
``data/eval-harness/session.json`` and ``rankings/*.jsonl``. Cache cells are
written by ``runner.run_variant`` and read here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

# Streamlit runs this file directly (not via `python -m`), so the workspace
# root isn't on sys.path and `dev.eval_harness.*` imports below would fail.
_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

import streamlit as st  # noqa: E402  (sys.path injection above must run first)

try:
    from streamlit_sortables import sort_items
except ImportError:  # pragma: no cover — exercised when optional dep missing
    sort_items = None  # type: ignore[assignment]

from dev.eval_harness import aggregate, runner, voice_gate  # noqa: E402
from dev.eval_harness.picker import pick_diverse_days  # noqa: E402
from dev.eval_harness.variants import ALL_VARIANTS, Variant, get_variant  # noqa: E402
from dev.eval_harness.windowed_context import gather_as_of  # noqa: E402
from src.finance.app_config import get_config  # noqa: E402
from src.finance.budget_service_local import BudgetServiceLocal  # noqa: E402
from src.finance.spending_summary_local import SpendingSummaryLocal  # noqa: E402
from src.finance.storage import create_budget_service, create_spending_summary  # noqa: E402

logger = logging.getLogger(__name__)

SESSION_PATH = Path("data/eval-harness/session.json")
DEMO_DB_PATH = Path("data/demo.db")

DEFAULT_MONTH = "2026-04"
DEFAULT_VARIANTS = [v.name for v in ALL_VARIANTS]
DEFAULT_N_SAMPLES = 3


# ---------------------------------------------------------------------------
# Storage selection — read once at top, keep simple
# ---------------------------------------------------------------------------


def _make_storage(use_demo: bool) -> tuple[Any, Any]:
    if use_demo:
        return (
            SpendingSummaryLocal(db_path=DEMO_DB_PATH),
            BudgetServiceLocal(db_path=DEMO_DB_PATH, user_id="default"),
        )
    return (create_spending_summary(), create_budget_service())


def _backend_label(use_demo: bool) -> str:
    if use_demo:
        return "demo.db"
    storage = get_config().get("storage", "sqlite")
    return "DynamoDB" if storage == "dynamodb" else "finance.db"


# ---------------------------------------------------------------------------
# Session persistence
# ---------------------------------------------------------------------------


def load_session() -> dict[str, Any]:
    if SESSION_PATH.exists():
        try:
            return cast("dict[str, Any]", json.loads(SESSION_PATH.read_text()))
        except json.JSONDecodeError:
            logger.warning("Corrupt session.json; resetting to defaults.")
    return {}


def save_session(state: dict[str, Any]) -> None:
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_PATH.write_text(json.dumps(state, indent=2))


def init_session_state() -> None:
    if "harness_initialized" in st.session_state:
        return
    persisted = load_session()
    st.session_state.month = persisted.get("month", DEFAULT_MONTH)
    st.session_state.selected_dates = persisted.get("selected_dates", [])
    st.session_state.active_variants = persisted.get("active_variants", DEFAULT_VARIANTS)
    st.session_state.n_samples = persisted.get("n_samples", DEFAULT_N_SAMPLES)
    st.session_state.use_demo_db = persisted.get("use_demo_db", True)
    st.session_state.hide_voice_violations = persisted.get("hide_voice_violations", False)
    st.session_state.use_radio_ranking = persisted.get("use_radio_ranking", False)
    st.session_state.harness_initialized = True


def persist_session_state() -> None:
    save_session(
        {
            "month": st.session_state.month,
            "selected_dates": st.session_state.selected_dates,
            "active_variants": st.session_state.active_variants,
            "n_samples": st.session_state.n_samples,
            "use_demo_db": st.session_state.use_demo_db,
            "hide_voice_violations": st.session_state.hide_voice_violations,
            "use_radio_ranking": st.session_state.use_radio_ranking,
        }
    )


# ---------------------------------------------------------------------------
# Cache cell readers / generators
# ---------------------------------------------------------------------------


def cell_state(variant: Variant, day: str, sample_idx: int) -> tuple[str, dict[str, Any] | None]:
    """Return one of: ('missing', None), ('stale', cell), ('fresh', cell)."""
    cell = runner.read_cell(variant.name, day, sample_idx)
    if cell is None:
        return ("missing", None)
    if not runner.cell_is_fresh(cell, variant):
        return ("stale", cell)
    return ("fresh", cell)


async def _ensure_ctx_async(month: str, day: str, ss: Any, bs: Any) -> dict[str, Any] | None:
    day_n = int(day.rsplit("-", maxsplit=1)[-1])
    try:
        return await gather_as_of(month, day_n, spending_summary=ss, budget_service=bs)
    except LookupError:
        return None


def get_or_build_ctx(month: str, day: str, ss: Any, bs: Any) -> dict[str, Any] | None:
    """Cache by day in session_state to avoid re-querying every rerun."""
    key = f"_ctx_{day}"
    if key in st.session_state:
        return cast("dict[str, Any] | None", st.session_state[key])
    ctx = asyncio.run(_ensure_ctx_async(month, day, ss, bs))
    st.session_state[key] = ctx
    return ctx


async def _generate_one(variant: Variant, ctx: dict[str, Any], sample_idx: int) -> Path:
    return await runner.run_variant(variant, ctx, sample_idx)


def generate_missing_cells(
    month: str, days: list[str], variants: list[Variant], n_samples: int, ss: Any, bs: Any
) -> int:
    """For every (variant, day, sample 1..N) cell that's missing or stale,
    generate a fresh one. Returns how many cells were written."""
    written = 0
    progress = st.progress(0.0, text="Generating missing cells…")
    total_cells = len(variants) * len(days) * n_samples
    if total_cells == 0:
        progress.empty()
        return 0

    seen = 0
    for day in days:
        ctx = get_or_build_ctx(month, day, ss, bs)
        if ctx is None:
            seen += len(variants) * n_samples
            progress.progress(seen / total_cells, text=f"Skipped {day} (no transactions)")
            continue
        for variant in variants:
            for s in range(1, n_samples + 1):
                state, _ = cell_state(variant, day, s)
                if state == "fresh":
                    seen += 1
                    progress.progress(seen / total_cells, text=f"{variant.name} {day} #{s} cached")
                    continue
                try:
                    asyncio.run(_generate_one(variant, ctx, s))
                    written += 1
                except Exception as exc:
                    st.warning(f"{variant.name} {day} #{s} failed: {exc}")
                seen += 1
                progress.progress(seen / total_cells, text=f"{variant.name} {day} #{s} generated")

    progress.empty()
    return written


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------


def render_sidebar(ss: Any, bs: Any) -> None:
    with st.sidebar:
        st.header("Settings")

        st.text_input("Month (YYYY-MM)", key="month", on_change=persist_session_state)

        st.checkbox(
            "Use data/demo.db (demo seed)",
            key="use_demo_db",
            on_change=persist_session_state,
            help="When off, reads your real data via the storage factory (DynamoDB or data/finance.db, per data/config.json).",
        )

        st.number_input(
            "Samples per cell (N)",
            min_value=1,
            max_value=10,
            step=1,
            key="n_samples",
            on_change=persist_session_state,
        )

        st.multiselect(
            "Active variants",
            options=DEFAULT_VARIANTS,
            key="active_variants",
            on_change=persist_session_state,
        )

        st.checkbox(
            "Hide voice-violating outputs from ranking",
            key="hide_voice_violations",
            on_change=persist_session_state,
        )

        st.checkbox(
            "Use radio buttons to rank (fallback)",
            key="use_radio_ranking",
            on_change=persist_session_state,
            help="Use this if the drag-and-drop component fails to load.",
        )

        st.divider()
        if st.button("Re-pick diverse days from picker"):
            picks = pick_diverse_days(st.session_state.month, spending_summary=ss, budget_service=bs)
            st.session_state.selected_dates = [d.isoformat() for d in picks]
            persist_session_state()
            # Clear cached contexts so they rebuild for the new days.
            for k in [k for k in st.session_state if k.startswith("_ctx_")]:
                del st.session_state[k]
            st.rerun()

        st.divider()
        with st.expander("Raw rankings log", expanded=False):
            events = list(aggregate.iter_rankings())
            st.write(f"{len(events)} event(s)")
            if events:
                st.json(events[-20:])


def render_day_inputs(month: str, day: str, ss: Any, bs: Any) -> dict[str, Any] | None:
    ctx = get_or_build_ctx(month, day, ss, bs)
    if ctx is None:
        st.warning(f"No transactions for {day} in the selected database.")
        return None
    with st.expander(f"Raw input for {day} ({ctx['transaction_count']} txns, ${ctx['day_total']:.2f})"):
        st.subheader("Transactions")
        st.json(ctx.get("transactions", []))
        st.subheader("Computed context")
        st.json({k: v for k, v in ctx.items() if k != "transactions"})
        st.subheader("Rendered prompt (V0)")
        try:
            from dev.eval_harness.variants import V0_baseline

            st.code(runner.render_prompt(V0_baseline, ctx), language="text")
        except Exception as exc:  # pragma: no cover
            st.error(f"V0 render failed: {exc}")
    return ctx


@st.dialog("Prompt + input", width="large")
def _show_prompt_dialog(variant: Variant, day: str, ctx: dict[str, Any]) -> None:
    st.markdown(f"### {variant.name} — {day}")
    st.caption(f"Model: `{variant.model}` · Prior days: {variant.prior_day_summaries}")
    try:
        rendered = runner.render_prompt(variant, ctx)
        st.markdown("**Rendered prompt**")
        st.code(rendered, language="text")
    except Exception as exc:
        st.error(f"Prompt render failed: {exc}")
    st.markdown("**Variant context** (filtered to `context_field_set`)")
    st.json({k: ctx.get(k) for k in variant.context_field_set if k in ctx})
    st.markdown(f"**Transactions** ({ctx.get('transaction_count', 0)})")
    st.json(ctx.get("transactions", []))


SAMPLE_LABEL_SEP = "  ·  "
RANKING_HEADER = "Ranking (top = best)"


def _build_sample_label(variant_name: str, sample_idx: int, output: str, has_violation: bool) -> str:
    prefix = f"{variant_name} #{sample_idx}"
    if has_violation:
        prefix = f"⚠ {prefix}"
    snippet = output.strip().replace("\n", " ")
    return f"{prefix}{SAMPLE_LABEL_SEP}{snippet}"


def _parse_sample_label(label: str) -> tuple[str, int] | None:
    """Reverse :func:`_build_sample_label`; tolerates the optional leading ⚠."""
    prefix, _, _ = label.partition(SAMPLE_LABEL_SEP)
    prefix = prefix.lstrip("⚠").strip()
    head, sep, tail = prefix.rpartition(" #")
    if not sep:
        return None
    try:
        return head.strip(), int(tail.strip())
    except ValueError:
        return None


def render_variant_ranker(month: str, day: str, ctx: dict[str, Any], active_variants: list[Variant]) -> None:
    """One sortable replaces the variant grid and the ranking box. Each variant
    is a column; the trailing column is the Ranking. The user drags one
    representative sample per variant into Ranking; top = best.
    """
    hide_violations = st.session_state.hide_voice_violations
    n_samples = st.session_state.n_samples
    use_radio = st.session_state.get("use_radio_ranking", False) or sort_items is None

    variant_to_samples: dict[str, list[tuple[int, dict[str, Any], bool]]] = {}
    for variant in active_variants:
        rows: list[tuple[int, dict[str, Any], bool]] = []
        for s in range(1, n_samples + 1):
            state, cell = cell_state(variant, day, s)
            if state != "fresh" or cell is None:
                continue
            output = cell.get("output_parsed") or cell.get("output_raw") or ""
            has_violation = bool(voice_gate.detect_voice_violations(output))
            if has_violation and hide_violations:
                continue
            rows.append((s, cell, has_violation))
        if rows:
            variant_to_samples[variant.name] = rows

    available_variants = [v.name for v in active_variants if v.name in variant_to_samples]

    cols = st.columns(len(active_variants) + 1)
    for col, variant in zip(cols[:-1], active_variants, strict=True):
        with col:
            st.markdown(f"**{variant.name}**")
            st.caption(variant.hypothesis)
            cc = st.columns(2)
            with cc[0]:
                if st.button("📋", key=f"prompt_{variant.name}_{day}", help="View prompt + input"):
                    _show_prompt_dialog(variant, day, ctx)
            with cc[1]:
                if st.button("↻", key=f"add_{variant.name}_{day}", help="Generate another sample"):
                    next_idx = runner.next_sample_idx(variant.name, day)
                    with st.spinner(f"Generating {variant.name} sample #{next_idx}…"):
                        try:
                            asyncio.run(runner.run_variant(variant, ctx, next_idx))
                        except Exception as exc:
                            st.error(f"Failed: {exc}")
                    st.rerun()
            if variant.name not in variant_to_samples:
                st.caption("_no fresh samples_")
    with cols[-1]:
        st.markdown(f"**{RANKING_HEADER}**")
        st.caption(f"One per variant. Excluded variants score {aggregate.EXCLUSION_PENALTY} each.")

    if len(available_variants) < 2:
        st.info(f"Need ≥2 variants with fresh samples to rank; have {len(available_variants)}.")
        return

    if use_radio:
        st.warning("Radio fallback active — ranking variants only (not samples).")
        ordered: list[str] = []
        for pos in range(1, len(available_variants) + 1):
            remaining = [v for v in available_variants if v not in ordered]
            choice = st.radio(
                f"Rank {pos}",
                options=remaining,
                key=f"rank_{day}_{pos}",
                horizontal=True,
            )
            ordered.append(choice)

        if st.button(f"Save ranking for {day}", key=f"save_{day}"):
            event = {
                "ts": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "day": day,
                "ordered_variants": ordered,
                "available_variants": available_variants,
                "n_samples": n_samples,
                "hide_voice_violations": hide_violations,
            }
            path = aggregate.append_event(event)
            st.success(f"Saved → {path}")
        return

    containers: list[dict[str, Any]] = []
    for variant in active_variants:
        rows = variant_to_samples.get(variant.name, [])
        labels = [
            _build_sample_label(variant.name, s, cell.get("output_parsed") or cell.get("output_raw") or "", has_v)
            for s, cell, has_v in rows
        ]
        containers.append({"header": variant.name, "items": labels})
    containers.append({"header": RANKING_HEADER, "items": []})

    result = sort_items(
        containers,
        multi_containers=True,
        direction="horizontal",
        key=f"ranker_{day}",
    )

    ranking_items: list[str] = []
    for c in result or containers:
        if c.get("header") == RANKING_HEADER:
            ranking_items = list(c.get("items", []))
            break

    parsed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for lbl in ranking_items:
        parsed_lbl = _parse_sample_label(lbl)
        if parsed_lbl is None:
            continue
        v, s = parsed_lbl
        if v in seen:
            continue
        seen.add(v)
        parsed.append({"variant": v, "sample_idx": s})

    excluded = [v for v in available_variants if v not in seen]

    info_cols = st.columns([2, 1])
    with info_cols[0]:
        if parsed:
            st.markdown("**Current ranking**")
            for i, entry in enumerate(parsed, start=1):
                st.text(f"{i}. {entry['variant']} #{entry['sample_idx']}")
        else:
            st.caption("Nothing placed yet.")
    with info_cols[1]:
        if excluded:
            st.markdown(f"**Excluded** ({aggregate.EXCLUSION_PENALTY} each)")
            for v in excluded:
                st.text(f"· {v}")
        else:
            st.caption("All variants placed.")

    can_save = len(parsed) >= 2
    if st.button(
        f"Save ranking for {day}",
        key=f"save_{day}",
        disabled=not can_save,
        help=None if can_save else "Place at least 2 samples to save.",
    ):
        event = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "day": day,
            "ordered_samples": parsed,
            "available_variants": available_variants,
            "n_samples": n_samples,
            "hide_voice_violations": hide_violations,
        }
        path = aggregate.append_event(event)
        st.success(f"Saved → {path}")


def _currently_violating_variants(active_variants: list[Variant], days: list[str], n_samples: int) -> set[str]:
    """Variants where ANY cached cell across the selected days/samples has a
    voice violation under the current rules. Used by the aggregate panel to
    honor the sidebar's "Hide voice-violating outputs from ranking" toggle —
    spec §11 requires this filter to apply to Borda totals as well as the
    drag list."""
    flagged: set[str] = set()
    for variant in active_variants:
        for day in days:
            for s in range(1, n_samples + 1):
                cell = runner.read_cell(variant.name, day, s)
                if cell is None:
                    continue
                output = cell.get("output_parsed") or cell.get("output_raw") or ""
                if voice_gate.detect_voice_violations(output):
                    flagged.add(variant.name)
                    break
            if variant.name in flagged:
                break
    return flagged


def render_aggregate_panel(active_variants: list[Variant]) -> None:
    events = list(aggregate.iter_rankings())
    if not events:
        st.info("No rankings yet — Borda totals will appear after the first save.")
        return

    if st.session_state.hide_voice_violations:
        excluded = _currently_violating_variants(
            active_variants,
            st.session_state.selected_dates,
            st.session_state.n_samples,
        )
        if excluded:
            events = aggregate.filter_events_excluding(events, excluded)
            st.caption(f"Hiding voice-violating variants from Borda: {', '.join(sorted(excluded))}")
            if not events:
                st.info("All saved rankings only contain currently-violating variants.")
                return

    totals = aggregate.borda_score(events)
    st.subheader(f"Borda totals — {len(events)} event(s)")
    rows = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    for name, pts in rows:
        st.text(f"{name}: {pts}")

    # Rank trajectory over time — answers "is the lead stable or session-
    # dependent?" per spec §10. Each variant becomes one line on the chart;
    # x-axis is event index in chronological order.
    if len(events) >= 2:
        trajectory = aggregate.borda_trajectory(events)
        variant_names = sorted(set(totals))
        chart_data = {
            "event_idx": [row["event_idx"] for row in trajectory],
            **{name: [row.get(name, 0) for row in trajectory] for name in variant_names},
        }
        st.line_chart(chart_data, x="event_idx", y=variant_names)

    with st.expander("Per-day breakdown"):
        per_day = aggregate.borda_per_day(events)
        for d in sorted(per_day):
            st.markdown(f"**{d}**")
            for name, pts in sorted(per_day[d].items(), key=lambda kv: -kv[1]):
                st.text(f"  {name}: {pts}")


def main() -> None:
    st.set_page_config(page_title="Tidings prompt eval", layout="wide")
    init_session_state()

    ss, bs = _make_storage(st.session_state.use_demo_db)

    st.title("Tidings prompt eval")
    st.caption(
        f"Month: {st.session_state.month} · "
        f"DB: {_backend_label(st.session_state.use_demo_db)} · "
        f"N={st.session_state.n_samples}"
    )

    render_sidebar(ss, bs)

    # Auto-pick diverse days on first run if none persisted.
    if not st.session_state.selected_dates:
        picks = pick_diverse_days(st.session_state.month, spending_summary=ss, budget_service=bs)
        st.session_state.selected_dates = [d.isoformat() for d in picks]
        persist_session_state()

    if not st.session_state.selected_dates:
        st.warning(
            f"No diverse days found in {st.session_state.month}. Confirm the database has transactions for this month."
        )
        return

    active_variants: list[Variant] = []
    for name in st.session_state.active_variants:
        try:
            active_variants.append(get_variant(name))
        except KeyError:
            continue

    if not active_variants:
        st.warning("Select at least one variant in the sidebar.")
        return

    col_left, col_right = st.columns([3, 1])
    with col_right:
        if st.button("⚡ Generate missing cells"):
            written = generate_missing_cells(
                st.session_state.month,
                st.session_state.selected_dates,
                active_variants,
                st.session_state.n_samples,
                ss,
                bs,
            )
            st.success(f"Wrote {written} cell(s).")
            st.rerun()
    with col_left:
        day = st.radio(
            "Day",
            options=st.session_state.selected_dates,
            horizontal=True,
            key="active_day",
        )

    ctx = render_day_inputs(st.session_state.month, day, ss, bs)
    if ctx is None:
        return

    render_variant_ranker(st.session_state.month, day, ctx, active_variants)
    st.divider()
    render_aggregate_panel(active_variants)


if __name__ == "__main__":
    main()
