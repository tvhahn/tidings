"""Month-end spending projections from cumulative day-of-month spending curves.

Methodology (docs/specs/_archive/2026-02-27-spending-forecast/README.md): for each
category, build a per-month cumulative-fraction curve — what share of the
month's total had been spent by each day — from the last 6 complete months,
then project the current month as ``current_spend / fraction_at(today)``.
Early in the month the ratio is unstable, so it is blended with the
historical mean weighted by the fraction itself; algebraically the blend
reduces to ``current + (1 - f_today) * mean_month_total``.

Statement-created and statement-enriched transactions are INCLUDED (L2,
2026-07-17): excluding them made mid-month projections silently understate
spending for statement-lag users (verified live: ~27% of a month's rows were
invisible to the curves). The synthetic ``00:00`` time on statement-created
rows is irrelevant here — the curves use day-of-month precision, and the
calendar date is reliable. Deleted/ignored/non-spending rows stay excluded.

Fail-open by design: callers wrap forecast computation in try/except and
leave all forecast fields None on any error.
"""

import calendar
import statistics
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any, Literal

from dateutil.relativedelta import relativedelta

from src.finance.demo_clock import app_today
from src.finance.merchant_normalizer import normalize_merchant
from src.finance.spending_aggregator import SPENDING_TYPES

if TYPE_CHECKING:
    from src.finance.upcoming_service import UpcomingResult

# Attributes needed to build fraction tables. ``Company`` is needed by the
# commitment-aware projection (L3/L5) to attribute rows to recurring merchants.
# None are DynamoDB reserved words, so no ExpressionAttributeNames are required.
# SQLite ignores this.
FORECAST_PROJECTION = "DateFileName, Amount, TransactionType, Category, Company, DeletedAt, Ignored, StatementSource"

HISTORY_MONTHS = 6
_CACHE_TTL_SECONDS = 3600
# Below this day (or transaction count) the ratio projection is unreliable —
# show the historical mean instead, labeled quality="historical".
_EARLY_MONTH_DAY = 5
_MIN_CURRENT_TXNS = 3
# Fewer historical months than this → linear extrapolation, quality="limited".
_MIN_HISTORY_MONTHS = 2
_IQR_Z = 0.675  # +/-0.675 stdev approximates the P25-P75 interquartile range
_LIMITED_BAND_FACTOR = 1.5
_WIDEN_BAND_BELOW_MONTHS = 4

ForecastQualityValue = Literal["forecast", "historical", "limited"]


@dataclass
class CategoryHistory:
    """Per-category spending history across the analyzed months.

    ``curves[i]`` is month i's cumulative curve: sorted (position, fraction)
    pairs on a 0.0-1.0 day-position scale (month-length normalized), ending
    at fraction 1.0. ``monthly_totals[i]`` is that month's total spend.
    Only months where the category had spending are included.
    """

    curves: list[list[tuple[float, float]]]
    monthly_totals: list[float]

    @property
    def months_active(self) -> int:
        return len(self.monthly_totals)

    @property
    def mean_month_total(self) -> float:
        return statistics.fmean(self.monthly_totals) if self.monthly_totals else 0.0


@dataclass
class ForecastTables:
    """Fraction tables for one 6-month window, keyed by category.

    ``overall`` is the whole-window spending history built from every included
    item regardless of category, with one entry per window month — including
    zero-spend months (empty curve, ``0.0`` total). ``overall.curves[i]`` and
    ``overall.monthly_totals[i]`` therefore align 1:1 with ``months[i]``, so
    ``overall.curves[-1]`` is always the most recent complete month. It is built
    directly (never by summing per-category curves, which skip months and so
    don't align with the window).
    """

    categories: dict[str, CategoryHistory]
    months: list[str]
    overall: CategoryHistory = field(default_factory=lambda: CategoryHistory(curves=[], monthly_totals=[]))


@dataclass
class CategoryForecast:
    month_total: float
    lower: float | None
    upper: float | None
    quality: ForecastQualityValue


def forecast_today() -> date:
    """Today in the configured app timezone — the forecast's notion of 'now'.

    Honors the ``DEMO_TODAY`` fixture-generation override via :func:`app_today`.
    """
    return app_today()


def month_keys(today: date, months: int = HISTORY_MONTHS) -> list[str]:
    """The last ``months`` complete months before today's month, oldest first."""
    first = date(today.year, today.month, 1)
    return [(first - relativedelta(months=i)).strftime("%Y-%m") for i in range(months, 0, -1)]


def window_key(keys: list[str]) -> str:
    return f"{keys[0]}..{keys[-1]}"


def _include(item: Mapping[str, Any]) -> bool:
    # L2: statement-created and statement-enriched rows COUNT — only
    # deleted / ignored / non-spending / amount-less rows are excluded.
    if item.get("DeletedAt") or item.get("Ignored"):
        return False
    if item.get("TransactionType") not in SPENDING_TYPES:
        return False
    return item.get("Amount") is not None


def _day_of_month(item: Mapping[str, Any]) -> int | None:
    """Parse the day from a DateFileName sort key (``YYYY.MM.DD_HH.MM_...``)."""
    raw = item.get("DateFileName") or ""
    try:
        return int(raw[8:10])
    except (ValueError, IndexError):
        return None


def _cumulative_curve(day_amounts: dict[int, float], total: float, days_in_month: int) -> list[tuple[float, float]]:
    """Cumulative (position, fraction) curve for one month's day→amount map."""
    curve: list[tuple[float, float]] = []
    cumulative = 0.0
    for day in sorted(day_amounts):
        cumulative += day_amounts[day]
        curve.append((day / days_in_month, cumulative / total))
    return curve


def build_tables(items_by_month: Mapping[str, Sequence[Mapping[str, Any]]]) -> ForecastTables:
    """Build cumulative-fraction curves per category from raw month transactions."""
    categories: dict[str, CategoryHistory] = {}
    # Whole-window overall history: one entry per window month, in the same
    # sorted order as ``months`` — zero-spend months append ``([], 0.0)`` so the
    # lists stay index-aligned with the window (L1).
    overall = CategoryHistory(curves=[], monthly_totals=[])

    for ym in sorted(items_by_month):
        year, month = int(ym[:4]), int(ym[5:7])
        days_in_month = calendar.monthrange(year, month)[1]

        by_cat_day: dict[str, dict[int, float]] = {}
        overall_by_day: dict[int, float] = {}
        for item in items_by_month[ym]:
            if not _include(item):
                continue
            day = _day_of_month(item)
            if day is None:
                continue
            day = min(max(day, 1), days_in_month)
            amount = float(item["Amount"])
            cat = item.get("Category") or "miscellaneous"
            by_cat_day.setdefault(cat, {})[day] = by_cat_day.get(cat, {}).get(day, 0.0) + amount
            overall_by_day[day] = overall_by_day.get(day, 0.0) + amount

        for cat, day_amounts in by_cat_day.items():
            total = sum(day_amounts.values())
            if total <= 0:
                continue
            history = categories.setdefault(cat, CategoryHistory(curves=[], monthly_totals=[]))
            history.curves.append(_cumulative_curve(day_amounts, total, days_in_month))
            history.monthly_totals.append(total)

        overall_total = sum(overall_by_day.values())
        overall.curves.append(
            _cumulative_curve(overall_by_day, overall_total, days_in_month) if overall_total > 0 else []
        )
        overall.monthly_totals.append(overall_total)

    return ForecastTables(categories=categories, months=sorted(items_by_month), overall=overall)


def _fraction_at(curve: list[tuple[float, float]], position: float) -> float:
    """Cumulative fraction at a day position, linearly interpolated.

    Anchored at (0, 0); flat at 1.0 after the month's last transaction.
    """
    prev_pos, prev_frac = 0.0, 0.0
    for pos, frac in curve:
        if position <= pos:
            span = pos - prev_pos
            if span <= 0:
                return frac
            return prev_frac + (frac - prev_frac) * (position - prev_pos) / span
        prev_pos, prev_frac = pos, frac
    return 1.0


def _band(
    history: CategoryHistory, current_spent: float, position: float, projected: float
) -> tuple[float | None, float | None]:
    """P25-P75 band from cross-month variance at the current day position.

    Each month implies a month-end total of ``current + (1 - fraction_m) *
    total_m`` ("the rest of this month behaves like month m's remainder");
    the spread of those implied totals is the dollar-space variance at this
    position. Early in the month it converges to the variance of monthly
    totals, late in the month to zero.
    """
    if history.months_active < _MIN_HISTORY_MONTHS:
        return None, None
    implied = [
        current_spent + (1.0 - _fraction_at(curve, position)) * total
        for curve, total in zip(history.curves, history.monthly_totals, strict=True)
    ]
    spread = _IQR_Z * statistics.stdev(implied)
    if history.months_active < _WIDEN_BAND_BELOW_MONTHS:
        spread *= _LIMITED_BAND_FACTOR
    lower = max(projected - spread, current_spent, 0.0)
    upper = max(projected + spread, lower)
    return round(lower, 2), round(upper, 2)


def project_category(
    history: CategoryHistory | None,
    current_spent: float,
    current_txn_count: int,
    today: date,
) -> CategoryForecast | None:
    """Project a variable category's month-end total. None when unprojectable."""
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    elapsed = today.day / days_in_month

    if history is None or history.months_active < _MIN_HISTORY_MONTHS:
        # New category (or a single historical month): linear extrapolation.
        # No variance data, so no confidence band — honest over invented.
        if current_spent <= 0 or elapsed <= 0:
            return None
        return CategoryForecast(
            month_total=round(current_spent / elapsed, 2),
            lower=None,
            upper=None,
            quality="limited",
        )

    mean_total = history.mean_month_total
    position = elapsed

    if today.day < _EARLY_MONTH_DAY or current_txn_count < _MIN_CURRENT_TXNS:
        projected = max(mean_total, current_spent)
        lower, upper = _band(history, current_spent, position, projected)
        return CategoryForecast(month_total=round(projected, 2), lower=lower, upper=upper, quality="historical")

    fractions = [_fraction_at(curve, position) for curve in history.curves]
    f_today = statistics.fmean(fractions)
    if f_today <= 0:
        projected = max(mean_total, current_spent)
        lower, upper = _band(history, current_spent, position, projected)
        return CategoryForecast(month_total=round(projected, 2), lower=lower, upper=upper, quality="historical")

    # Blend = f * (current / f) + (1 - f) * mean, which reduces to:
    projected = max(current_spent + (1.0 - f_today) * mean_total, current_spent)
    lower, upper = _band(history, current_spent, position, projected)
    return CategoryForecast(month_total=round(projected, 2), lower=lower, upper=upper, quality="forecast")


def compute_month_pace(
    tables: ForecastTables,
    current_total: float,
    current_count: int,
    today: date,
) -> dict[str, Any] | None:
    """L3 verbatim: the ``MonthPaceInfo`` field dict for the current month.

    Returns ``None`` when the window is empty (all overall totals zero). All
    fraction lookups use the ``day_of_month / days_in_month`` position (the same
    convention as :func:`project_category`). ``previous_to_date`` reads the most
    recent complete month (``overall.curves[-1]`` — ``0.0`` if that month is
    empty). ``typical_to_date`` is the median across every window month (zero
    months contribute ``0.0``), or ``None`` when fewer than two months had
    spending. Projection fields come from :func:`project_category` on the overall
    history; when it returns ``None`` all four are ``None``.
    """
    overall = tables.overall
    if not overall.monthly_totals or all(total <= 0 for total in overall.monthly_totals):
        return None

    days_in_month = calendar.monthrange(today.year, today.month)[1]
    day_of_month = today.day
    position = day_of_month / days_in_month

    previous_to_date = _fraction_at(overall.curves[-1], position) * overall.monthly_totals[-1]

    active_months = sum(1 for total in overall.monthly_totals if total > 0)
    if active_months >= _MIN_HISTORY_MONTHS:
        typical_to_date: float | None = statistics.median(
            _fraction_at(curve, position) * total
            for curve, total in zip(overall.curves, overall.monthly_totals, strict=True)
        )
    else:
        typical_to_date = None

    forecast = project_category(overall, current_total, current_count, today)
    if forecast is not None:
        projected_month_total: float | None = forecast.month_total
        projected_lower = forecast.lower
        projected_upper = forecast.upper
        forecast_quality: str | None = forecast.quality
    else:
        projected_month_total = projected_lower = projected_upper = None
        forecast_quality = None

    return {
        "day_of_month": day_of_month,
        "days_in_month": days_in_month,
        "previous_to_date": round(previous_to_date, 2),
        "typical_to_date": round(typical_to_date, 2) if typical_to_date is not None else None,
        "projected_month_total": projected_month_total,
        "projected_lower": projected_lower,
        "projected_upper": projected_upper,
        "forecast_quality": forecast_quality,
    }


def compute_commitment_pace(
    tables: ForecastTables,
    discretionary_tables: ForecastTables,
    upcoming: "UpcomingResult",
    current_total: float,
    current_count: int,
    current_items: list[Mapping[str, Any]],
    today: date,
) -> dict[str, Any] | None:
    """L5: commitment-aware ``MonthPaceInfo`` field dict, including ``breakdown``.

    Composes (never replaces) :func:`compute_month_pace`:

    - ``observed_mtd`` = ``current_total`` (every observed row, including any
      arrived recurring charges and imported statement rows).
    - ``assumed_committed`` / ``upcoming_committed`` = Σ estimate over expected
      charges with status ``assumed`` / ``upcoming``. ``unrecorded`` charges
      count in NEITHER term — they may never arrive.
    - ``discretionary_mtd`` = ``observed_mtd`` minus the actual amounts of
      ``arrived`` charges minus current-month ``_stmt_`` rows attributed to
      recurring merchants (each recurring merchant subtracted once — a merchant
      that arrived is not also subtracted via its statement row).
    - ``everyday_remainder`` = the discretionary-only curve projection minus
      ``discretionary_mtd``, floored at 0.
    - ``projected_month_total`` = observed + assumed + upcoming + everyday.

    ``previous_to_date`` / ``typical_to_date`` keep using the (L2-corrected)
    overall history. Returns ``None`` when the window is empty (same rule as
    :func:`compute_month_pace`); returns the plain ``compute_month_pace`` dict
    (plus ``breakdown=None``) when there are no expected charges to fold in.
    """
    base = compute_month_pace(tables, current_total, current_count, today)
    if base is None:
        return None
    if not upcoming.charges:
        return {**base, "breakdown": None}

    days_in_month = calendar.monthrange(today.year, today.month)[1]
    days_remaining = days_in_month - today.day
    observed_mtd = current_total

    assumed_committed = sum(c.amount_estimate for c in upcoming.charges if c.status == "assumed")
    upcoming_committed = sum(c.amount_estimate for c in upcoming.charges if c.status == "upcoming")

    # Recurring spend already observed this month, removed from the discretionary
    # slice so the everyday curve is not fed (and does not re-project) the
    # recurring basket. Each recurring merchant is subtracted once: via its
    # arrived actual if it matched a row, else via its current-month statement row.
    # Only current-month arrivals are subtracted: a boundary-fuzz arrival matches a
    # row in the PREVIOUS month (e.g. a day-1 charge that posted Feb 28), whose
    # amount is not part of ``observed_mtd`` — subtracting it would understate the
    # discretionary slice by a recurring-charge-sized error mid-month.
    current_prefix = today.strftime("%Y-%m")
    arrived_actual = sum(
        c.actual_amount or 0.0
        for c in upcoming.charges
        if c.status == "arrived" and c.actual_date is not None and c.actual_date.startswith(current_prefix)
    )
    # The stmt-row guard still spans ALL arrived merchants: a merchant that arrived
    # via a previous-month row must not be re-subtracted through a statement row.
    arrived_merchants = {c.merchant for c in upcoming.charges if c.status == "arrived"}
    recurring = upcoming.recurring_merchants
    stmt_recurring = 0.0
    for item in current_items:
        if "_stmt_" not in (item.get("DateFileName") or ""):
            continue
        if item.get("DeletedAt") or item.get("Ignored"):
            continue
        if item.get("TransactionType") not in SPENDING_TYPES:
            continue
        amount = item.get("Amount")
        if amount is None:
            continue
        merchant = normalize_merchant(str(item.get("Company") or ""))
        if merchant in recurring and merchant not in arrived_merchants:
            stmt_recurring += float(amount)

    discretionary_mtd = max(observed_mtd - arrived_actual - stmt_recurring, 0.0)

    disc_forecast = project_category(discretionary_tables.overall, discretionary_mtd, current_count, today)
    if disc_forecast is not None:
        everyday_remainder = max(disc_forecast.month_total - discretionary_mtd, 0.0)
    else:
        everyday_remainder = 0.0

    projected_month_total = observed_mtd + assumed_committed + upcoming_committed + everyday_remainder

    # Committed terms are point estimates; the projection's band is the
    # discretionary forecast's band, re-centered on the projection.
    if disc_forecast is not None and disc_forecast.lower is not None and disc_forecast.upper is not None:
        lower_width = disc_forecast.month_total - disc_forecast.lower
        upper_width = disc_forecast.upper - disc_forecast.month_total
        projected_lower: float | None = round(projected_month_total - lower_width, 2)
        projected_upper: float | None = round(projected_month_total + upper_width, 2)
    else:
        projected_lower = projected_upper = None

    breakdown = {
        "observed_mtd": round(observed_mtd, 2),
        "assumed_committed": round(assumed_committed, 2),
        "upcoming_committed": round(upcoming_committed, 2),
        "everyday_remainder": round(everyday_remainder, 2),
        "everyday_daily_rate": round(everyday_remainder / days_remaining, 2) if days_remaining > 0 else None,
        "days_remaining": days_remaining,
        "charges": [
            {
                "merchant": c.merchant,
                "display_name": c.display_name,
                "amount_estimate": round(c.amount_estimate, 2),
                "expected_day": c.expected_day,
                "status": c.status,
                "channel": c.channel,
                "cadence": c.cadence,
                "category": c.category,
                "actual_amount": round(c.actual_amount, 2) if c.actual_amount is not None else None,
                "actual_date": c.actual_date,
                "previous_amount": round(c.previous_amount, 2) if c.previous_amount is not None else None,
            }
            for c in upcoming.charges
        ],
    }

    return {
        **base,
        "projected_month_total": round(projected_month_total, 2),
        "projected_lower": projected_lower,
        "projected_upper": projected_upper,
        "forecast_quality": disc_forecast.quality if disc_forecast is not None else base.get("forecast_quality"),
        "breakdown": breakdown,
    }


class ForecastService:
    """Thin 1-hour cache around the fraction tables for one history window.

    Historical months are immutable, so the only staleness risk is edits to
    past transactions — the TTL matches BudgetServiceBase._historical_cache.
    The projection math itself is stateless (module-level functions).
    """

    def __init__(self) -> None:
        self._cache: dict[str, ForecastTables] = {}
        self._cache_time: dict[str, float] = {}
        # Parallel single-window cache for the discretionary tables (overall
        # history minus the recurring basket, L5). Additive: the commitment-aware
        # summary pace builds these from the SAME window rows as ``_cache`` so a
        # cache hit avoids re-querying the 6-month window. The recurring set is
        # stable within its own 1-hour cache, so keying on ``window`` alone is
        # safe for the aligned TTLs.
        self._disc_cache: dict[str, ForecastTables] = {}
        self._disc_cache_time: dict[str, float] = {}
        # Serializes the miss path so a single builder runs across the request
        # threadpool. Held across builder() in get_or_build — see its docstring.
        self._lock = threading.Lock()

    def get_or_build(self, window: str, builder: Callable[[], ForecastTables]) -> ForecastTables:
        """Return cached tables for ``window``, building at most once across threads.

        This is the concurrent-safe entry point; prefer it over the raw
        get_cached/store pair. Double-checked under ``self._lock``: concurrent
        cold-cache callers serialize, so only the first runs ``builder`` and the
        rest wait and reuse its result — no thundering-herd recompute.

        ``builder`` must be synchronous and must not re-enter this service or
        touch the event loop (the lock is held across it). The forecast builder
        satisfies this: it queries the spending summary and calls the
        module-level ``build_tables`` — never back into ``ForecastService``.
        """
        with self._lock:
            cached = self.get_cached(window)
            if cached is not None:
                return cached
            tables = builder()
            # Inline the single-window replacement rather than calling the public
            # store() — we already hold the lock and a plain Lock isn't reentrant.
            self._cache = {window: tables}
            self._cache_time = {window: time.time()}
            return tables

    def get_cached(self, window: str) -> ForecastTables | None:
        """Return live cached tables for ``window`` or None. Concurrent callers
        should use :meth:`get_or_build` — a lone get_cached/store pair races."""
        cached = self._cache.get(window)
        if cached and (time.time() - self._cache_time.get(window, 0)) < _CACHE_TTL_SECONDS:
            return cached
        return None

    def store(self, window: str, tables: ForecastTables) -> None:
        """Replace the single-window cache. Prefer :meth:`get_or_build` as the
        concurrent-safe entry point; this takes the lock so a store can't
        interleave with invalidate_cache."""
        with self._lock:
            # Single-window cache: a new window means the month rolled over.
            self._cache = {window: tables}
            self._cache_time = {window: time.time()}

    def get_cached_discretionary(self, window: str) -> ForecastTables | None:
        cached = self._disc_cache.get(window)
        if cached and (time.time() - self._disc_cache_time.get(window, 0)) < _CACHE_TTL_SECONDS:
            return cached
        return None

    def store_discretionary(self, window: str, tables: ForecastTables) -> None:
        # A duplicate concurrent build is benign here (last write wins on the
        # same window), but take the lock so a store can't interleave with
        # invalidate_cache — mirrors store().
        with self._lock:
            # Single-window cache: a new window replaces the prior one (month rollover).
            self._disc_cache = {window: tables}
            self._disc_cache_time = {window: time.time()}

    def invalidate_cache(self) -> None:
        with self._lock:
            self._cache = {}
            self._cache_time = {}
            self._disc_cache = {}
            self._disc_cache_time = {}
