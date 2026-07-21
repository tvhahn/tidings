"""Build per-day context dicts for AI daily summary generation."""

import calendar
from datetime import datetime, timedelta
from typing import Any


def _display_company(raw: str) -> str:
    """Normalize a merchant string for prompt use.

    Bank feeds ship ALL-CAPS names ("WESTLAND UTILITY CO") and the model copies
    casing verbatim into user-facing summaries, breaking the sentence-case
    voice rule. Title-case fully-uppercase words the same way the frontend's
    titleCase does; leave mixed-case tokens ("iTunes") untouched. Empty names
    become a lowercase description so the model treats them as unknown rather
    than quoting a blank.
    """
    if not raw:
        return "unknown merchant"

    def fix(word: str) -> str:
        if len(word) > 1 and word.isupper():
            return word[0].upper() + word[1:].lower()
        return word

    return " ".join(fix(w) for w in raw.split())


def gather_daily_contexts(
    journal_days: list[dict[str, Any]],
    budget_ceiling: float | None = None,
    budget_categories: dict[str, float] | None = None,
    prev_month_total: float = 0.0,
    monthly_context: dict[str, Any] | None = None,
    upcoming_by_date: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Build compact context dicts for each journal day.

    Args:
        journal_days: List of day dicts with keys: date, day_total, count,
            mtd_total, transactions (each with company, amount, category).
        budget_ceiling: Monthly budget ceiling (annual / 12), or None.
        budget_categories: Per-category monthly targets, or None.
        prev_month_total: Previous month's total spending for comparison.
        monthly_context: Optional output of insights_context.gather_context()
            for this month — provides 6-month trend, anomalies, and category
            deltas to anchor each day's summary against.
        upcoming_by_date: Optional map of ``YYYY-MM-DD`` → expected charges
            landing that day (L15). Each day dict gains ``upcoming_tomorrow``,
            the NEXT calendar day's expected charges — a calm day-before
            heads-up for the ntfy path. Empty list when nothing is expected.

    Returns:
        List of context dicts, one per day, ordered same as input.
    """
    if not journal_days:
        return []

    sample_date = journal_days[0]["date"]
    year, month_num = int(sample_date[:4]), int(sample_date[5:7])
    days_in_month = calendar.monthrange(year, month_num)[1]

    trend_avg_6mo: float | None = None
    top_anomalies: list[dict[str, Any]] = []
    category_deltas_top: list[dict[str, Any]] = []
    if monthly_context:
        trend = monthly_context.get("trend") or []
        prior = [t for t in trend if t.get("year_month") != f"{year}-{month_num:02d}"]
        prior_totals = [float(t.get("total_spending") or 0) for t in prior]
        if prior_totals:
            trend_avg_6mo = round(sum(prior_totals) / len(prior_totals), 2)

        top_anomalies.extend(
            {
                "category": a.get("category"),
                "current": float(a.get("current") or 0),
                "baseline": float(a.get("baseline") or 0),
                "reason": a.get("reason"),
            }
            for a in (monthly_context.get("anomalies") or [])[:2]
        )

        category_deltas_top.extend(
            {
                "category": d.get("category"),
                "current": float(d.get("current") or 0),
                "previous": float(d.get("previous") or 0),
                "delta_pct": d.get("delta_pct"),
            }
            for d in (monthly_context.get("category_deltas") or [])[:3]
        )

    contexts = []
    for day in journal_days:
        date_str = day["date"]
        dt = datetime.strptime(date_str, "%Y-%m-%d")  # noqa: DTZ007 — date-only string; only .day is used
        day_number = dt.day

        txns = [
            {
                "company": _display_company(t.get("company") or ""),
                "amount": float(t.get("amount", 0)),
                "category": t.get("category", "Miscellaneous"),
            }
            for t in day.get("transactions", [])
        ]

        mtd_by_cat: dict[str, float] = {}
        for t in txns:
            cat = t["category"]
            mtd_by_cat[cat] = mtd_by_cat.get(cat, 0) + t["amount"]

        mtd_total = float(day.get("mtd_total", 0))
        expected_pace_pct = round((day_number / days_in_month) * 100, 1)
        actual_pace_pct: float | None = None
        if budget_ceiling and budget_ceiling > 0:
            actual_pace_pct = round((mtd_total / budget_ceiling) * 100, 1)

        # Day-before heads-up: charges expected the NEXT calendar day (L15).
        tomorrow_key = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
        upcoming_tomorrow = list(upcoming_by_date.get(tomorrow_key, [])) if upcoming_by_date else []

        contexts.append(
            {
                "date": date_str,
                "day_of_week": dt.strftime("%A"),
                "day_total": float(day.get("day_total", 0)),
                "transaction_count": int(day.get("count", 0)),
                "transactions": txns,
                "mtd_total": mtd_total,
                "mtd_by_category": mtd_by_cat,
                "budget_ceiling_monthly": float(budget_ceiling) if budget_ceiling else None,
                "budget_categories": budget_categories,
                "month_day_number": day_number,
                "month_total_days": days_in_month,
                "previous_month_total": float(prev_month_total),
                "expected_pace_pct": expected_pace_pct,
                "actual_pace_pct": actual_pace_pct,
                "trend_avg_6mo": trend_avg_6mo,
                "top_anomalies": top_anomalies,
                "category_deltas_top": category_deltas_top,
                "upcoming_tomorrow": upcoming_tomorrow,
            }
        )

    return contexts
