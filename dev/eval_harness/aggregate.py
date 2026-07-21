"""Borda count aggregation over the rankings log.

Two event formats are supported:

- **Legacy** (``ordered_variants``): a list of variant names, top = best.
- **Per-sample** (``ordered_samples`` + ``available_variants``): each entry is
  ``{"variant": str, "sample_idx": int}``. Variants are deduped by first
  occurrence (the user picks one representative sample per variant). Variants
  that were available but never placed get ``EXCLUSION_PENALTY`` points.

For ``N`` placed variants, position ``i`` (1-indexed) earns ``N - i`` points.
Excluded variants get a fixed ``EXCLUSION_PENALTY`` (negative) so a deliberate
snub counts against the variant.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

RANKINGS_DIR = Path("data/eval-harness/rankings")
EXCLUSION_PENALTY = -1


class RankingEvent(TypedDict, total=False):
    ts: str
    day: str
    ordered_variants: list[str]
    ordered_samples: list[dict[str, Any]]
    available_variants: list[str]


def _placed_variants(event: RankingEvent) -> list[str]:
    """Ordered list of variants represented in the event, deduped by first
    occurrence. Works for both legacy and per-sample formats."""
    if "ordered_samples" in event:
        seen: set[str] = set()
        out: list[str] = []
        for entry in event["ordered_samples"]:
            v = entry.get("variant")
            if not v or v in seen:
                continue
            seen.add(v)
            out.append(v)
        return out
    return list(event.get("ordered_variants", []))


def _excluded_variants(event: RankingEvent, placed: list[str]) -> list[str]:
    """Variants the user could have placed but didn't. Empty for legacy events."""
    available = event.get("available_variants")
    if not available:
        return []
    placed_set = set(placed)
    return [v for v in available if v not in placed_set]


def iter_rankings(rankings_dir: Path | None = None) -> Iterator[RankingEvent]:
    """Yield every ranking event across every ``rankings/*.jsonl`` file, in
    filesystem-name order (which is ISO timestamp order)."""
    d = rankings_dir or RANKINGS_DIR
    if not d.exists():
        return
    for path in sorted(d.glob("*.jsonl")):
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and ("ordered_variants" in event or "ordered_samples" in event):
                    yield event  # type: ignore[misc]


def borda_score(events: Iterable[RankingEvent]) -> dict[str, int]:
    """Sum Borda points across all events. Variant at position i (1-indexed)
    of an N-placed event gets (N - i) points; excluded variants get EXCLUSION_PENALTY."""
    totals: dict[str, int] = defaultdict(int)
    for event in events:
        placed = _placed_variants(event)
        n = len(placed)
        for i, name in enumerate(placed, start=1):
            totals[name] += n - i
        for excluded in _excluded_variants(event, placed):
            totals[excluded] += EXCLUSION_PENALTY
    return dict(totals)


def borda_per_day(events: Iterable[RankingEvent]) -> dict[str, dict[str, int]]:
    """Borda points broken out per day."""
    by_day: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for event in events:
        placed = _placed_variants(event)
        n = len(placed)
        for i, name in enumerate(placed, start=1):
            by_day[event["day"]][name] += n - i
        for excluded in _excluded_variants(event, placed):
            by_day[event["day"]][excluded] += EXCLUSION_PENALTY
    return {d: dict(v) for d, v in by_day.items()}


def filter_events_excluding(
    events: Iterable[RankingEvent],
    exclude_variants: set[str],
) -> list[RankingEvent]:
    """Return a copy of ``events`` with variants in ``exclude_variants`` dropped
    from each event. Removes them from both placed lists and ``available_variants``
    so they don't generate exclusion penalties either. Events that retain fewer
    than two placed variants are dropped entirely.
    """
    if not exclude_variants:
        return list(events)
    out: list[RankingEvent] = []
    for ev in events:
        if "ordered_samples" in ev:
            kept_samples = [s for s in ev["ordered_samples"] if s.get("variant") not in exclude_variants]
            kept_avail = [v for v in ev.get("available_variants", []) if v not in exclude_variants]
            placed = _placed_variants({"ordered_samples": kept_samples})  # type: ignore[typeddict-item]
            if len(placed) >= 2:
                out.append({**ev, "ordered_samples": kept_samples, "available_variants": kept_avail})
        else:
            kept = [v for v in ev.get("ordered_variants", []) if v not in exclude_variants]
            if len(kept) >= 2:
                out.append({**ev, "ordered_variants": kept})
    return out


def borda_trajectory(events: Iterable[RankingEvent]) -> list[dict[str, Any]]:
    """Cumulative Borda totals after each chronological event."""
    events_list = list(events)
    if not events_list:
        return []

    all_variants: set[str] = set()
    for ev in events_list:
        all_variants.update(_placed_variants(ev))
        all_variants.update(ev.get("available_variants", []))

    running: dict[str, int] = dict.fromkeys(all_variants, 0)
    rows: list[dict[str, Any]] = []
    for idx, ev in enumerate(events_list):
        placed = _placed_variants(ev)
        n = len(placed)
        for i, name in enumerate(placed, start=1):
            running[name] += n - i
        for excluded in _excluded_variants(ev, placed):
            running[excluded] += EXCLUSION_PENALTY
        rows.append(
            {
                "event_idx": idx,
                "ts": ev["ts"],
                "day": ev["day"],
                **running,
            }
        )
    return rows


def append_event(event: dict[str, Any], rankings_dir: Path | None = None) -> Path:
    """Append a single ranking event as one JSONL line. Each session gets its
    own file (named by ISO timestamp); on subsequent saves we keep appending
    to the same file."""
    d = rankings_dir or RANKINGS_DIR
    d.mkdir(parents=True, exist_ok=True)
    # One file per session day — keeps the log human-greppable while avoiding
    # one-file-per-event clutter.
    fname = event["ts"][:10] + ".jsonl"
    path = d / fname
    with path.open("a") as f:
        f.write(json.dumps(event) + "\n")
    return path
