"""Gather spending context for AI insights analysis.

``gather_context`` is the pure, I/O-free core used by the API endpoint
(``GET /api/v1/insights/context``), which returns the dict directly.
``gather_context_to_file`` adds disk persistence for thread-pool callers —
the insights generation worker and the dev CLI wrapper
(``dev/cli/gather_insights_data.py``, maintainer-only, not shipped).
"""

from __future__ import annotations

import asyncio
import calendar
import json
import math
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from dateutil.relativedelta import relativedelta

from src.finance.app_config import get_config
from src.finance.app_timezone import now_local

# Re-exported under the historical private name for callers/tests that import it here.
from src.finance.decimal_utils import decimals_to_floats as _strip_decimals
from src.finance.demo_clock import app_today

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from src.finance.protocols import IBudgetService, ISpendingSummary

# Transaction types that count as spending (mirrors spending_aggregator.SPENDING_TYPES).
_SPENDING_TYPES = {"purchase", "withdrawal", "preauth", "e-transfer"}

# --- Memory-signal detection thresholds (documented in the prompt's <data_notes>) ---
# recurring_annual: a category qualifies only when its mean active-month amount clears
# this floor — keeps grocery-sized monthly noise out of the "annual event" hint list.
_RECURRING_ANNUAL_MIN_MEAN = 200.0
# ...and only when it is active in at most this many distinct months per 12 (sparse).
# Once/twice-a-year events sit far below 4; a monthly category sits at 12 and is excluded.
_RECURRING_ANNUAL_MAX_ACTIVE_PER_12 = 4
# Months of history scanned for annual patterns (only months with data are counted).
_RECURRING_ANNUAL_LOOKBACK = 24
_RECURRING_ANNUAL_CAP = 10
# fixed_charges: a merchant/category is "flat recurring" when active in at least this many
# of the 6 baseline months and its month-to-month amount barely moves (coefficient of
# variation below the cap) — mortgage/strata/childcare, not variable spend.
_FIXED_CHARGE_MIN_ACTIVE = 5
_FIXED_CHARGE_CV_MAX = 0.05
# previous_briefing: excerpt is truncated to this many chars at a paragraph boundary.
_BRIEFING_EXCERPT_CHARS = 3000

# Saved-briefing filename stems: 20260201T120000 or 2026-02-01_12-00-00.
# (Kept in sync with the router's _INSIGHT_ID_RE; gather_context lives in src.finance
# and must not import from src.api, so the stem logic is duplicated here deliberately.)
_INSIGHT_STEM_RE = re.compile(r"^\d{8}T\d{6}$|^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$")


def _parse_insight_stem_dt(stem: str) -> datetime:
    """Parse a saved-briefing filename stem into a naive datetime for sorting."""
    if "T" in stem:
        return datetime.strptime(stem, "%Y%m%dT%H%M%S")  # noqa: DTZ007 — filename-stem round-trip, sort only
    return datetime.strptime(stem, "%Y-%m-%d_%H-%M-%S")  # noqa: DTZ007 — filename-stem round-trip, sort only


def _parse_insight_stem_ts(stem: str) -> str:
    """Parse a saved-briefing filename stem into an ISO timestamp string."""
    dt = _parse_insight_stem_dt(stem)
    if "T" in stem:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _truncate_at_paragraph(text: str, limit: int) -> str:
    """Truncate ``text`` to at most ``limit`` chars, backing up to a paragraph boundary.

    Prefers the last blank-line boundary within the limit; falls back to the last
    line break, then to a hard cut. Whole text returned unchanged when short enough.
    """
    if len(text) <= limit:
        return text
    head = text[:limit]
    for sep in ("\n\n", "\n"):
        idx = head.rfind(sep)
        if idx > 0:
            return head[:idx].rstrip()
    return head.rstrip()


def latest_briefing_for_month(month: str) -> dict[str, Any] | None:
    """Most recent saved briefing for ``month`` (``YYYY-MM``), or None.

    Reads ``data/insights/<month>/`` (the same layout the generation worker
    writes and the router's saved-insights endpoints list). Returns
    ``{month, generated_at, excerpt}`` with the markdown truncated to
    ``_BRIEFING_EXCERPT_CHARS`` at a paragraph boundary.
    """
    insights_dir = Path("data/insights") / month
    if not insights_dir.is_dir():
        return None
    files = [f for f in insights_dir.glob("*.md") if _INSIGHT_STEM_RE.match(f.stem)]
    if not files:
        return None
    files.sort(key=lambda f: _parse_insight_stem_dt(f.stem), reverse=True)
    latest = files[0]
    return {
        "month": month,
        "generated_at": _parse_insight_stem_ts(latest.stem),
        "excerpt": _truncate_at_paragraph(latest.read_text(), _BRIEFING_EXCERPT_CHARS),
    }


def _summary_has_data(summary: dict[str, Any] | None) -> bool:
    """True when a month summary carries any spending (non-empty by_category / total)."""
    if not summary:
        return False
    if float(summary.get("total_spending") or 0) > 0:
        return True
    return bool(summary.get("by_category"))


def _commented_spending_entries(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Live *spending* transactions carrying a user comment, in the commented-txn shape."""
    return [
        {
            "date": it.get("Date", ""),
            "company": it.get("Company", ""),
            "amount": it.get("Amount", 0),
            "category": it.get("Category", ""),
            "comment": it.get("Comment", ""),
        }
        for it in items
        if it.get("Comment") and _is_spend(it)
    ]


def _same_month_last_year(
    prev_year_ym: str,
    summaries_by_month: dict[str, dict[str, Any]],
    raw_by_month: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any] | None:
    """Seasonal anchor: the target month one year earlier, trimmed + last-year comments.

    Returns None when that month has no spending data. ``by_category`` matches the
    trimmed trend-entry shape; ``comments`` are last year's live-spending annotations.
    """
    summary = summaries_by_month.get(prev_year_ym)
    if summary is None or not _summary_has_data(summary):
        return None
    return {
        "year_month": prev_year_ym,
        "total_spending": summary.get("total_spending", 0),
        "spending_count": summary.get("spending_count", 0),
        "by_category": summary.get("by_category", {}),
        "comments": _commented_spending_entries(raw_by_month.get(prev_year_ym, [])),
    }


def _recurring_annual(
    target_ym: str,
    prev_year_ym: str,
    lookback_months: list[str],
    summaries_by_month: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Categories that look like once/twice-a-year events landing around this month.

    Deterministic hint list (not a forecaster): over the months with data in the
    lookback window, a category qualifies when it is active now (or was in the same
    month last year), is active in ≤ ``_RECURRING_ANNUAL_MAX_ACTIVE_PER_12`` distinct
    months per 12, and its mean active-month amount clears ``_RECURRING_ANNUAL_MIN_MEAN``.
    """
    data_months = [ym for ym in lookback_months if _summary_has_data(summaries_by_month.get(ym))]
    n_data = len(data_months)
    if n_data == 0:
        return []

    # category -> list of (year_month, amount) for months where it was active
    active: dict[str, list[tuple[str, float]]] = {}
    for ym in data_months:
        for cat, info in (summaries_by_month[ym].get("by_category") or {}).items():
            amt = float(info.get("amount") or 0)
            if amt > 0:
                active.setdefault(cat, []).append((ym, amt))

    def _active_now(ym: str, cat: str) -> bool:
        info = (summaries_by_month.get(ym) or {}).get("by_category", {}).get(cat)
        return bool(info) and float(info.get("amount") or 0) > 0

    out: list[dict[str, Any]] = []
    for cat, entries in active.items():
        if not (_active_now(target_ym, cat) or _active_now(prev_year_ym, cat)):
            continue
        if (len(entries) / n_data) * 12 > _RECURRING_ANNUAL_MAX_ACTIVE_PER_12:
            continue  # active too many months per year — not an annual event
        amounts = [a for _, a in entries]
        mean_amt = sum(amounts) / len(amounts)
        if mean_amt < _RECURRING_ANNUAL_MIN_MEAN:
            continue
        months_seen = sorted(ym for ym, _ in entries)
        out.append(
            {
                "category": cat,
                "typical_amount": round(mean_amt, 2),
                "months_seen": months_seen,
                "last_seen": months_seen[-1],
            }
        )
    out.sort(key=lambda d: d["typical_amount"], reverse=True)
    return out[:_RECURRING_ANNUAL_CAP]


def _fixed_charges(baseline_summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flat recurring merchant/category pairs across the 6-month baseline.

    ``baseline_summaries`` is the trend window in chronological (oldest→newest)
    order. A merchant qualifies when active in ≥ ``_FIXED_CHARGE_MIN_ACTIVE`` of the
    baseline months and its monthly amounts vary by less than ``_FIXED_CHARGE_CV_MAX``
    (coefficient of variation). ``monthly_amount`` is the latest active amount.
    """
    # company -> list of (amount, category) across baseline months where it was active
    by_company: dict[str, list[tuple[float, str]]] = {}
    for summary in baseline_summaries:
        for company, info in (summary.get("by_company") or {}).items():
            amt = float(info.get("amount") or 0)
            if amt > 0:
                by_company.setdefault(company, []).append((amt, info.get("category") or "miscellaneous"))

    out: list[dict[str, Any]] = []
    for company, entries in by_company.items():
        if len(entries) < _FIXED_CHARGE_MIN_ACTIVE:
            continue
        amounts = [a for a, _ in entries]
        mean_amt = sum(amounts) / len(amounts)
        if mean_amt <= 0:
            continue
        std = math.sqrt(sum((a - mean_amt) ** 2 for a in amounts) / len(amounts))
        if std / mean_amt >= _FIXED_CHARGE_CV_MAX:
            continue
        latest_amount, latest_category = entries[-1]
        out.append(
            {
                "company": company,
                "category": latest_category,
                "monthly_amount": round(latest_amount, 2),
                "months_active": len(entries),
            }
        )
    out.sort(key=lambda d: d["monthly_amount"], reverse=True)
    return out


def _compute_category_deltas(
    current_by_cat: dict[str, Any],
    previous_by_cat: dict[str, Any],
    top_n: int = 5,
) -> list[dict[str, Any]]:
    """Compute per-category month-over-month deltas, top N by absolute amount."""
    cats = set(current_by_cat) | set(previous_by_cat)
    deltas: list[dict[str, Any]] = []
    for cat in cats:
        cur = float(current_by_cat.get(cat, {}).get("amount", 0))
        prev = float(previous_by_cat.get(cat, {}).get("amount", 0))
        delta_amount = cur - prev
        if prev > 0:
            delta_pct: float | None = (cur - prev) / prev * 100
        else:
            delta_pct = None
        deltas.append(
            {
                "category": cat,
                "current": round(cur, 2),
                "previous": round(prev, 2),
                "delta_amount": round(delta_amount, 2),
                "delta_pct": round(delta_pct, 1) if delta_pct is not None else None,
            }
        )
    deltas.sort(key=lambda d: abs(d["delta_amount"]), reverse=True)
    return deltas[:top_n]


def _is_spend(item: Mapping[str, Any]) -> bool:
    """True for a live (non-ignored, non-deleted) spending transaction."""
    return item.get("TransactionType") in _SPENDING_TYPES and not item.get("DeletedAt") and not item.get("Ignored")


def _annotated_amounts_by_category(items: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Sum user-commented live spending per category for the target month.

    This is the ``annotated_amount`` fed into anomaly detection: the portion of
    a category's month that the user has already explained via a transaction
    comment.
    """
    out: dict[str, float] = {}
    for it in items:
        if not _is_spend(it) or not it.get("Comment"):
            continue
        cat = it.get("Category") or "miscellaneous"
        out[cat] = out.get(cat, 0.0) + float(it.get("Amount") or 0)
    return {k: round(v, 2) for k, v in out.items()}


def _largest_transactions(items: Sequence[Mapping[str, Any]], n: int = 10) -> list[dict[str, Any]]:
    """Top ``n`` live spending transactions this month, largest first."""
    spend = [it for it in items if _is_spend(it)]
    spend.sort(key=lambda it: float(it.get("Amount") or 0), reverse=True)
    out: list[dict[str, Any]] = []
    for it in spend[:n]:
        entry: dict[str, Any] = {
            "date": it.get("Date", ""),
            "company": it.get("Company") or "Unknown",
            "amount": round(float(it.get("Amount") or 0), 2),
            "category": it.get("Category") or "miscellaneous",
        }
        comment = it.get("Comment")
        if comment:
            entry["comment"] = comment
        out.append(entry)
    return out


def _suspected_ignored(
    target_items: Sequence[Mapping[str, Any]],
    prior_items: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Residual-risk signal: merchants active this month that the user usually ignores.

    A merchant qualifies when it has a live spending transaction in the target
    month *and*, across the prior 12 months, at least 2 of its transactions were
    marked Ignored and the ignored share is at least 50%.
    """
    active: dict[str, dict[str, float]] = {}
    for it in target_items:
        if not _is_spend(it):
            continue
        comp = it.get("Company") or "Unknown"
        d = active.setdefault(comp, {"amount": 0.0, "count": 0.0})
        d["amount"] += float(it.get("Amount") or 0)
        d["count"] += 1

    stats: dict[str, list[int]] = {}  # company -> [ignored_count, total_count]
    for it in prior_items:
        if it.get("DeletedAt"):
            continue
        comp = it.get("Company") or "Unknown"
        s = stats.setdefault(comp, [0, 0])
        s[1] += 1
        if it.get("Ignored"):
            s[0] += 1

    out: list[dict[str, Any]] = []
    for comp, info in active.items():
        ignored, total = stats.get(comp, [0, 0])
        if total == 0:
            continue
        share = ignored / total
        if ignored >= 2 and share >= 0.5:
            out.append(
                {
                    "company": comp,
                    "amount": round(info["amount"], 2),
                    "count": int(info["count"]),
                    "historical_ignored_share": round(share, 2),
                }
            )
    out.sort(key=lambda x: x["amount"], reverse=True)
    return out


def _pace_assessment(actual: float, expected: float) -> str:
    """Calm one-word pace read for a variable category (see data_notes in the prompt).

    ``ahead`` = spending faster than the prorated target, ``behind`` = slower.
    The signed ``variance_amount`` alongside it is authoritative.
    """
    if expected <= 0:
        return "on pace"
    ratio = actual / expected
    if ratio > 1.10:
        return "ahead"
    if ratio < 0.90:
        return "behind"
    return "on pace"


def _build_pace(
    *,
    year: int,
    month_num: int,
    targets_categories: dict[str, Any],
    spending_ceiling: float,
    ytd_summaries: list[dict[str, Any]],
    current_by_category: dict[str, Any],
    is_current_calendar_month: bool,
    today_day: int,
) -> dict[str, Any]:
    """Precompute all budget-pace math so the LLM never has to.

    All amounts are floats rounded to 2 decimals. ``ytd_summaries`` is the
    Jan..target-month ``get_summary`` list (also used for the budget block, so
    the months are fetched once). ``current_by_category`` is the target month's
    ``by_category`` map (Decimal amounts tolerated).
    """
    months_elapsed = month_num

    ytd_by_cat: dict[str, float] = {}
    ytd_total = 0.0
    for s in ytd_summaries:
        ytd_total += float(s.get("total_spending") or 0)
        for cat, info in s.get("by_category", {}).items():
            ytd_by_cat[cat] = ytd_by_cat.get(cat, 0.0) + float(info.get("amount") or 0)
    month_by_cat = {cat: float(info.get("amount") or 0) for cat, info in current_by_category.items()}

    budgeted = set(targets_categories)
    categories_out: list[dict[str, Any]] = []
    projected_adjusted = 0.0

    for cat, cfg in targets_categories.items():
        ctype = cfg.get("category_type") or "variable"
        annual = float(cfg.get("target") or 0)
        monthly = float(cfg.get("monthly_amount") if cfg.get("monthly_amount") is not None else (annual / 12))
        m_actual = round(month_by_cat.get(cat, 0.0), 2)
        y_actual = round(ytd_by_cat.get(cat, 0.0), 2)
        entry: dict[str, Any] = {
            "category": cat,
            "category_type": ctype,
            "annual_target": round(annual, 2),
            "monthly_target": round(monthly, 2),
            "month_actual": m_actual,
            "ytd_actual": y_actual,
        }
        if ctype == "lumpy":
            entry["pct_of_annual"] = round((y_actual / annual * 100) if annual else 0.0, 2)
            entry["remaining_expected"] = round(max(0.0, annual - y_actual), 2)
            entry["assessment"] = "annual — assess against full-year target"
            projected_adjusted += max(y_actual, annual)
        else:
            expected = round(monthly * months_elapsed, 2)
            variance = round(y_actual - expected, 2)
            entry["expected_to_date"] = expected
            entry["variance_amount"] = variance
            entry["variance_pct"] = round((variance / expected * 100) if expected else 0.0, 2)
            entry["assessment"] = _pace_assessment(y_actual, expected)
            projected_adjusted += (y_actual / months_elapsed * 12) if months_elapsed else 0.0
        categories_out.append(entry)

    unbudgeted: list[dict[str, Any]] = []
    for cat in sorted(set(ytd_by_cat) | set(month_by_cat)):
        if cat in budgeted:
            continue
        y_actual = round(ytd_by_cat.get(cat, 0.0), 2)
        m_actual = round(month_by_cat.get(cat, 0.0), 2)
        if y_actual == 0 and m_actual == 0:
            continue
        unbudgeted.append({"category": cat, "ytd_actual": y_actual, "month_actual": m_actual})
        projected_adjusted += (ytd_by_cat.get(cat, 0.0) / months_elapsed * 12) if months_elapsed else 0.0

    annual_ceiling = float(spending_ceiling or 0)
    prorated = round(annual_ceiling * months_elapsed / 12, 2)
    ytd_spent = round(ytd_total, 2)
    ceiling_variance = round(ytd_spent - prorated, 2)
    ceiling = {
        "annual": round(annual_ceiling, 2),
        "ytd_spent": ytd_spent,
        "prorated_to_date": prorated,
        "variance_amount": ceiling_variance,
        "variance_pct": round((ceiling_variance / prorated * 100) if prorated else 0.0, 2),
        "projected_naive": round((ytd_spent / months_elapsed * 12) if months_elapsed else 0.0, 2),
        "projected_adjusted": round(projected_adjusted, 2),
        "method_note": (
            "Projected year-end spend: variable and unbudgeted categories are annualized "
            "from year-to-date; lumpy/annual categories are counted at the greater of what "
            "is already paid or their full-year target, so paid-once items are not repeated."
        ),
    }

    month_progress: dict[str, Any] | None = None
    if is_current_calendar_month:
        days_in_month = calendar.monthrange(year, month_num)[1]
        days_elapsed = min(today_day, days_in_month)
        month_total = round(sum(month_by_cat.values()), 2)
        projected_month_end = round((month_total / days_elapsed * days_in_month) if days_elapsed else month_total, 2)
        month_progress = {
            "days_elapsed": days_elapsed,
            "days_in_month": days_in_month,
            "projected_month_end": projected_month_end,
        }

    return {
        "months_elapsed": months_elapsed,
        "ceiling": ceiling,
        "categories": categories_out,
        "unbudgeted": unbudgeted,
        "month_progress": month_progress,
    }


async def gather_context(
    year_month: str,
    *,
    spending_summary: ISpendingSummary | None = None,
    budget_service: IBudgetService | None = None,
) -> dict[str, Any]:
    """Assemble the full insights context for ``year_month`` (``YYYY-MM``).

    Returns a JSON-serializable dict. No disk writes — callers that want
    on-disk persistence should write the returned dict themselves.

    Runs the independent per-month queries concurrently via ``asyncio.to_thread``.
    The underlying ``SpendingSummary`` / ``BudgetService`` methods are sync
    (boto3 / sqlite3), so each is offloaded to a thread and gathered.
    """
    if spending_summary is None:
        from src.finance.storage import create_spending_summary

        spending_summary = create_spending_summary()
    if budget_service is None:
        from src.finance.storage import create_budget_service

        budget_service = create_budget_service()

    parts = year_month.split("-")
    year = int(parts[0])
    month_num = int(parts[1])
    current_date = date(year, month_num, 1)
    prev_month_ym = (current_date - relativedelta(months=1)).strftime("%Y-%m")
    prev_year_ym = (current_date - relativedelta(months=12)).strftime("%Y-%m")
    trend_months = [(current_date - relativedelta(months=i)).strftime("%Y-%m") for i in range(5, -1, -1)]
    # Prior 12 months (excluding the target month) for the suspected-ignored signal.
    # (i=12 lands on the same month last year, reused for its carried-forward comments.)
    prior_months = [(current_date - relativedelta(months=i)).strftime("%Y-%m") for i in range(1, 13)]
    # 24-month lookback (oldest→target) for recurring-annual detection. This is a
    # superset of the trend (last 6), YTD (Jan→target), and same-month-last-year
    # months, so every month summary is fetched exactly once and shared.
    lookback_months = [
        (current_date - relativedelta(months=i)).strftime("%Y-%m")
        for i in range(_RECURRING_ANNUAL_LOOKBACK - 1, -1, -1)
    ]

    # Phase 1: fan out everything that doesn't depend on budget targets or on
    # the target month's raw items (needed before anomaly detection). Kept to six
    # awaitables so asyncio.gather's typed overload holds (the previous-briefing
    # read is deferred to phase 2, where it is still independent).
    comparison, lookback_summaries, targets_item, historical, raw_items, prior_item_lists = await asyncio.gather(
        asyncio.to_thread(spending_summary.get_summary_with_comparison, year_month),
        asyncio.gather(*(asyncio.to_thread(spending_summary.get_summary, ym) for ym in lookback_months)),
        asyncio.to_thread(budget_service.get_targets, year),
        asyncio.to_thread(budget_service.get_historical_averages, spending_summary, 6),
        asyncio.to_thread(spending_summary.query_month, year_month),
        asyncio.gather(*(asyncio.to_thread(spending_summary.query_month, ym) for ym in prior_months)),
    )
    prior_items = [it for month_items in prior_item_lists for it in month_items]
    raw_by_month = dict(zip(prior_months, prior_item_lists, strict=True))

    # Single source of truth for month summaries — trend, YTD, and the memory
    # signals all read from here so no month is queried twice.
    summaries_by_month = dict(zip(lookback_months, lookback_summaries, strict=True))
    trend = [summaries_by_month[ym] for ym in trend_months]

    # Portion of each category already explained by a user comment this month —
    # drives proportional anomaly handling (replaces category-wide suppression).
    annotated_by_cat = _annotated_amounts_by_category(raw_items)

    # Phase 2: anomalies need the annotated amounts; the previous-month briefing
    # (disk read, independent) rides along. The YTD summaries are already in
    # summaries_by_month (Jan→target ⊂ the 24-month lookback), so no extra fetch.
    ytd_months = [f"{year}-{m:02d}" for m in range(1, month_num + 1)] if targets_item is not None else []
    ytd_summaries = [summaries_by_month[ym] for ym in ytd_months]
    anomalies, previous_briefing = await asyncio.gather(
        asyncio.to_thread(budget_service.get_category_anomalies, spending_summary, year_month, 6, annotated_by_cat),
        asyncio.to_thread(latest_briefing_for_month, prev_month_ym),
    )

    # Budget block + precomputed pace both consume the single YTD fetch above.
    budget: dict[str, Any] | None = None
    pace: dict[str, Any] | None = None
    if targets_item is not None:
        data = targets_item.get("Data", {})
        spending_ceiling = data.get("spending_ceiling", 0)
        targets_categories = data.get("categories", {})
        budget = {
            "spending_ceiling": spending_ceiling,
            "categories": targets_categories,
        }
        ytd_total = Decimal(0)
        for s in ytd_summaries:
            ytd_total += s["total_spending"]
        budget["ytd_spent_total"] = ytd_total
        budget["elapsed_year_fraction"] = round(month_num / 12, 3)

        today = app_today()
        is_current_calendar_month = today.year == year and today.month == month_num
        pace = _build_pace(
            year=year,
            month_num=month_num,
            targets_categories=targets_categories,
            spending_ceiling=float(spending_ceiling or 0),
            ytd_summaries=ytd_summaries,
            current_by_category=comparison["current"].get("by_category", {}),
            is_current_calendar_month=is_current_calendar_month,
            today_day=today.day,
        )

    commented_transactions = [
        {
            "date": item.get("Date", ""),
            "company": item.get("Company", ""),
            "amount": item.get("Amount", 0),
            "category": item.get("Category", ""),
            "comment": item.get("Comment", ""),
        }
        for item in raw_items
        if item.get("Comment") and not item.get("DeletedAt") and not item.get("Ignored")
    ]

    category_deltas = _compute_category_deltas(
        comparison["current"].get("by_category", {}),
        comparison["previous"].get("by_category", {}),
    )

    largest_transactions = _largest_transactions(raw_items)
    suspected_ignored = _suspected_ignored(raw_items, prior_items)

    # Memory signals — give the briefing continuity across months and years.
    same_month_last_year = _same_month_last_year(prev_year_ym, summaries_by_month, raw_by_month)
    recurring_annual = _recurring_annual(year_month, prev_year_ym, lookback_months, summaries_by_month)
    # fixed_charges reads per-company detail off the full trend summaries, which are
    # trimmed of by_company further down — compute it here, before that trim.
    fixed_charges = _fixed_charges(trend)
    user_memo = get_config().get("insights_user_memo") or None

    context = {
        "generated_at": now_local().isoformat(timespec="seconds"),
        "month": year_month,
        "current_month": comparison["current"],
        "previous_month": comparison["previous"],
        "delta": {
            "amount": comparison["delta_amount"],
            "percent": comparison["delta_percent"],
        },
        "trend": trend,
        "budget": budget,
        "pace": pace,
        "historical_averages": historical,
        "category_deltas": category_deltas,
        "anomalies": anomalies,
        "largest_transactions": largest_transactions,
        "suspected_ignored": suspected_ignored,
        "commented_transactions": commented_transactions,
        "same_month_last_year": same_month_last_year,
        "recurring_annual": recurring_annual,
        "fixed_charges": fixed_charges,
        "previous_briefing": previous_briefing,
        "user_memo": user_memo,
    }

    context = cast("dict[str, Any]", _strip_decimals(context))

    # Payload trim: trend and previous_month carry no per-company detail (it
    # roughly doubles the payload and adds nothing the LLM uses). current_month keeps
    # full detail. E-transfer deposits aren't spending, so drop them everywhere
    # so the LLM never nets them against the spend total.
    current = context["current_month"]
    current.pop("deposit_total", None)
    current.pop("deposit_count", None)

    previous = context["previous_month"]
    if previous:
        for key in ("by_company", "deposits_by_company", "deposit_total", "deposit_count"):
            previous.pop(key, None)

    for summary in context["trend"]:
        for key in (
            "by_company",
            "deposits_by_company",
            "top_categories",
            "deposit_total",
            "deposit_count",
        ):
            summary.pop(key, None)

    return context


def gather_context_to_file(
    year_month: str,
    output_path: str | None = None,
    *,
    spending_summary: ISpendingSummary | None = None,
    budget_service: IBudgetService | None = None,
) -> dict[str, Any]:
    """Gather the context dict and persist it to disk as JSON.

    Sync wrapper around :func:`gather_context` for thread-pool callers — the
    API's ``_run_generation`` worker (via ``run_sync``) and the dev CLI.
    Writes to ``output_path`` or ``data/insights/context_<YYYY-MM>.json``.
    The core strips ``Decimal`` values before returning, so the dict is
    plain-JSON-safe.
    """
    context = asyncio.run(
        gather_context(
            year_month,
            spending_summary=spending_summary,
            budget_service=budget_service,
        )
    )

    out = Path(output_path) if output_path else Path("data/insights") / f"context_{year_month}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(context, f, indent=2)
        f.write("\n")

    return context
