"""Router-altitude computation for the budget status endpoint.

Extracted from ``budget.py``'s ``get_status`` route so the pace/forecast math is
directly unit-testable without a ``TestClient``. This is deliberately router
altitude (imports API-layer Pydantic models), **not** ``src/finance`` — the
models are API contracts and the computation orchestrates injected services.

``run_sync`` is **injected**, never imported here: the ``get_status`` route owns
the ``src.api.routers.budget.run_sync`` symbol that tests patch, and the
``mock_run_sync`` drift guard requires helper modules not to expose their own.
"""

import asyncio
import calendar
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from src.api.models import (
    BudgetCategoryConfig,
    BudgetConfigResponse,
    BudgetGroupConfig,
    BudgetStatusResponse,
    CategoryPaceDetail,
    GroupPace,
    PaceStatus,
    UnbudgetedCategory,
)
from src.api.models.budget import PaceStatusValue
from src.api.utils import generate_month_keys
from src.finance import forecast_service
from src.finance.budget_service import DEFAULT_GROUPS
from src.finance.forecast_service import ForecastService
from src.finance.protocols import ISpendingSummary

logger = logging.getLogger(__name__)

# Injected ``run_sync`` — an awaitable-returning callable. Typed loosely because
# the route passes its own module-level ``run_sync`` (which tests patch).
RunSync = Callable[..., Awaitable[Any]]

# L14: a category whose expected recurring charges cover at least this share of
# its trailing mean monthly spend is "recurring-dominated" — its forecast
# switches from a smeared curve to a committed projection (known charge pending).
COMMITTED_CATEGORY_SHARE = 0.70  # locked


def compute_status_value(variance: float, expected: float) -> PaceStatusValue:
    if expected == 0:
        return "on_track"
    if variance > 0:
        return "under"
    if abs(variance) / expected <= 0.05:
        return "on_track"
    return "over"


def build_config_response(
    targets_item: dict[str, Any], groups_item: dict[str, Any] | None, year: int
) -> BudgetConfigResponse:
    """Build a BudgetConfigResponse from raw DynamoDB items."""
    data = targets_item.get("Data", {})
    raw_categories = data.get("categories", {})

    categories = {}
    allocated_total = 0.0
    for cat_name, cat_conf in raw_categories.items():
        target = float(cat_conf.get("target", 0))
        allocated_total += target
        categories[cat_name] = BudgetCategoryConfig(
            target=target,
            input_mode=cat_conf.get("input_mode", "monthly"),
            monthly_amount=float(cat_conf.get("monthly_amount", 0)),
            category_type=cat_conf.get("category_type", "variable"),
        )

    spending_ceiling = float(data.get("spending_ceiling", 0))

    groups_data = groups_item.get("Data", {}).get("groups", DEFAULT_GROUPS) if groups_item else DEFAULT_GROUPS
    groups = [BudgetGroupConfig(name=g["name"], categories=g["categories"]) for g in groups_data]

    return BudgetConfigResponse(
        year=year,
        spending_ceiling=spending_ceiling,
        categories=categories,
        groups=groups,
        targets_version=int(targets_item.get("Version", 1)),
        groups_version=int(groups_item.get("Version", 1)) if groups_item else 0,
        allocated_total=round(allocated_total, 2),
        unallocated=round(spending_ceiling - allocated_total, 2),
    )


def elapsed_fractions(today: date, year: int) -> tuple[float, float]:
    """Return (elapsed_year_fraction, elapsed_month_fraction).

    ``elapsed_year_fraction`` is leap-year aware and rounded to 3 places;
    ``elapsed_month_fraction`` is intentionally left unrounded.
    """
    day_of_year = today.timetuple().tm_yday
    days_in_year = 366 if calendar.isleap(year) else 365
    elapsed_year_fraction = round(day_of_year / days_in_year, 3)

    day_of_month = today.day
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    elapsed_month_fraction = day_of_month / days_in_month
    return elapsed_year_fraction, elapsed_month_fraction


@dataclass(frozen=True)
class AggregatedSpending:
    """Per-category spending rolled up from the fetched month summaries."""

    ytd_by_cat: dict[str, float]
    current_month_by_cat: dict[str, float]
    current_month_counts: dict[str, int]
    monthly_by_cat: dict[str, list[float]]
    total_ytd: float
    prior_year_by_cat: dict[str, float]


def aggregate_summaries(
    month_summaries: list[dict[str, Any]],
    compare_summaries: list[dict[str, Any]],
    current_month_key: str,
    compare_year: int | None,
) -> AggregatedSpending:
    """Aggregate per-category spending: YTD, current month, monthly breakdown, prior year."""
    ytd_by_cat: dict[str, float] = {}
    current_month_by_cat: dict[str, float] = {}
    current_month_counts: dict[str, int] = {}
    monthly_by_cat: dict[str, list[float]] = {}
    total_ytd = 0.0

    for raw in month_summaries:
        ym = raw.get("year_month", "")
        # Extract month index (0-based) from "YYYY-MM"
        month_idx = int(ym.split("-")[1]) - 1 if "-" in ym else 0
        for cat, info in raw.get("by_category", {}).items():
            amount = float(info["amount"])
            ytd_by_cat[cat] = ytd_by_cat.get(cat, 0.0) + amount
            total_ytd += amount
            if ym == current_month_key:
                current_month_by_cat[cat] = current_month_by_cat.get(cat, 0.0) + amount
                current_month_counts[cat] = current_month_counts.get(cat, 0) + int(info.get("count", 0))
            # Store per-month spending
            if cat not in monthly_by_cat:
                monthly_by_cat[cat] = [0.0] * 12
            monthly_by_cat[cat][month_idx] += amount

    # Aggregate compare year spending per category
    prior_year_by_cat: dict[str, float] = {}
    if compare_year:
        for raw in compare_summaries:
            for cat, info in raw.get("by_category", {}).items():
                prior_year_by_cat[cat] = prior_year_by_cat.get(cat, 0.0) + float(info["amount"])

    return AggregatedSpending(
        ytd_by_cat=ytd_by_cat,
        current_month_by_cat=current_month_by_cat,
        current_month_counts=current_month_counts,
        monthly_by_cat=monthly_by_cat,
        total_ytd=total_ytd,
        prior_year_by_cat=prior_year_by_cat,
    )


def build_category_details(
    config: BudgetConfigResponse,
    aggregated: AggregatedSpending,
    elapsed_year_fraction: float,
    elapsed_month_fraction: float,
    compare_year: int | None,
) -> tuple[dict[str, CategoryPaceDetail], PaceStatus]:
    """Build per-category pace details plus the overall ``PaceStatus`` headline."""
    ytd_by_cat = aggregated.ytd_by_cat
    current_month_by_cat = aggregated.current_month_by_cat
    monthly_by_cat = aggregated.monthly_by_cat
    prior_year_by_cat = aggregated.prior_year_by_cat

    # Overall pace
    overall_expected = config.spending_ceiling * elapsed_year_fraction
    overall_variance = round(overall_expected - aggregated.total_ytd, 2)
    overall_status = compute_status_value(overall_variance, overall_expected)

    if overall_variance >= 0:
        headline = f"${overall_variance:,.0f} ahead of pace"
    else:
        headline = f"${abs(overall_variance):,.0f} over budget"

    overall = PaceStatus(
        spending_ceiling=config.spending_ceiling,
        ytd_spent=round(aggregated.total_ytd, 2),
        expected_pace=round(overall_expected, 2),
        variance=overall_variance,
        status=overall_status,
        headline=headline,
    )

    # Per-category pace
    category_details: dict[str, CategoryPaceDetail] = {}

    for cat_name, cat_config in config.categories.items():
        ytd_spent = round(ytd_by_cat.get(cat_name, 0.0), 2)
        current_spent = round(current_month_by_cat.get(cat_name, 0.0), 2)

        if cat_config.category_type == "variable":
            expected = cat_config.monthly_amount * elapsed_month_fraction
            actual = current_spent
            ytd_expected = cat_config.target * elapsed_year_fraction
        elif cat_config.category_type == "lumpy":
            expected = cat_config.target * elapsed_year_fraction
            actual = ytd_spent
            ytd_expected = expected
        else:  # fixed
            expected = cat_config.monthly_amount
            actual = current_spent
            ytd_expected = cat_config.target * elapsed_year_fraction

        variance = round(expected - actual, 2)
        pace_pct = round((actual / expected) * 100, 1) if expected > 0 else 0.0
        status = compute_status_value(variance, expected)

        if cat_config.category_type == "fixed" and cat_config.monthly_amount > 0:
            diff_ratio = abs(current_spent - cat_config.monthly_amount) / cat_config.monthly_amount
            if current_spent > 0 and diff_ratio > 0.05:
                status = "over"

        category_details[cat_name] = CategoryPaceDetail(
            category=cat_name,
            target=cat_config.target,
            input_mode=cat_config.input_mode,
            monthly_amount=cat_config.monthly_amount,
            category_type=cat_config.category_type,
            current_month_spent=current_spent,
            current_month_expected=round(
                expected if cat_config.category_type != "lumpy" else cat_config.monthly_amount * elapsed_month_fraction,
                2,
            ),
            ytd_spent=ytd_spent,
            ytd_expected=round(ytd_expected, 2),
            variance=variance,
            pace_percent=pace_pct,
            status=status,
            monthly_spent=monthly_by_cat.get(cat_name, [0.0] * 12),
            prior_year_total=round(prior_year_by_cat.get(cat_name, 0.0), 2) if compare_year else None,
        )

    return category_details, overall


def build_groups_and_unbudgeted(
    config: BudgetConfigResponse,
    category_details: dict[str, CategoryPaceDetail],
    aggregated: AggregatedSpending,
    hist_cats: dict[str, Any],
    elapsed_year_fraction: float,
    compare_year: int | None,
) -> tuple[list[GroupPace], list[UnbudgetedCategory], list[float], float | None]:
    """Build group rollups, the unbudgeted list, monthly totals, and the prior-year total."""
    budgeted_cats = set(config.categories.keys())

    # Build groups
    groups = []
    overall_monthly = [0.0] * 12
    for g in config.groups:
        group_cats = [category_details[c] for c in g.categories if c in category_details]
        group_budgeted = sum(cd.target for cd in group_cats)
        group_ytd = sum(cd.ytd_spent for cd in group_cats)
        group_expected = group_budgeted * elapsed_year_fraction
        group_variance = round(group_expected - group_ytd, 2)
        group_status = compute_status_value(group_variance, group_expected)

        # Sum monthly totals across categories in this group
        group_monthly = [0.0] * 12
        for cd in group_cats:
            for i in range(12):
                group_monthly[i] += cd.monthly_spent[i]
        for i in range(12):
            overall_monthly[i] += group_monthly[i]

        group_prior = round(sum(c.prior_year_total or 0 for c in group_cats), 2) if compare_year else None

        groups.append(
            GroupPace(
                name=g.name,
                budgeted_total=round(group_budgeted, 2),
                ytd_spent=round(group_ytd, 2),
                expected_pace=round(group_expected, 2),
                variance=group_variance,
                status=group_status,
                categories=group_cats,
                monthly_totals=[round(v, 2) for v in group_monthly],
                prior_year_total=group_prior,
            )
        )

    # Unbudgeted categories
    unbudgeted = []
    for cat, ytd in sorted(aggregated.ytd_by_cat.items(), key=lambda x: x[1], reverse=True):
        if cat not in budgeted_cats:
            hist = hist_cats.get(cat, {})
            unbudgeted.append(
                UnbudgetedCategory(
                    category=cat,
                    ytd_spent=round(ytd, 2),
                    monthly_avg_historical=hist.get("monthly_avg", 0.0),
                    current_month_spent=round(aggregated.current_month_by_cat.get(cat, 0.0), 2),
                )
            )

    total_prior = round(sum(g.prior_year_total or 0 for g in groups), 2) if compare_year else None
    monthly_totals = [round(v, 2) for v in overall_monthly]

    return groups, unbudgeted, monthly_totals, total_prior


async def _upcoming_charges_by_category(today: date, run_sync: RunSync) -> dict[str, list[Any]]:
    """Group the current month's expected charges by their profile category.

    Resolves to ``{}`` on any error — the L14 committed treatment is a pure
    enhancement over the curve forecast and must never change the response
    shape when the upcoming derivation is unavailable.
    """
    try:
        from src.api.dependencies import get_upcoming_service

        month = today.strftime("%Y-%m")
        upcoming = await run_sync(get_upcoming_service().get_upcoming, month)
    except Exception:
        logger.exception("Upcoming-charge derivation failed — skipping committed budget forecasts")
        return {}
    by_cat: dict[str, list[Any]] = {}
    for charge in upcoming.charges:
        if charge.category:
            by_cat.setdefault(charge.category, []).append(charge)
    return by_cat


def _apply_committed_forecast(
    detail: CategoryPaceDetail,
    history: Any,
    base_forecast: float,
    cat_charges: list[Any],
) -> float | None:
    """L14: recurring-dominated category → committed forecast. Returns the new
    projection (and mutates ``detail``), or ``None`` when the category isn't
    recurring-dominated and the curve forecast should stand.

    ``committed forecast = spent + Σ(still-expected committed) + everyday
    remainder``, where the everyday remainder is whatever the base curve
    projects beyond spent + committed (floored at 0). Bounds are ``None`` — the
    committed terms are point estimates, not a variance band.
    """
    if history is None or history.mean_month_total <= 0:
        return None
    basket = sum(c.amount_estimate for c in cat_charges)  # the recurring commitment size
    if basket < COMMITTED_CATEGORY_SHARE * history.mean_month_total:
        return None

    # Only charges that haven't posted yet add to the projection — arrived
    # charges are already inside ``current_month_spent``; ``unrecorded`` may
    # never arrive (mirrors L5's committed terms).
    still_coming = sum(c.amount_estimate for c in cat_charges if c.status in ("upcoming", "assumed"))
    committed_forecast = max(base_forecast, detail.current_month_spent + still_coming)

    detail.forecast_month_total = round(committed_forecast, 2)
    detail.forecast_lower = None
    detail.forecast_upper = None
    detail.forecast_quality = "committed"
    if detail.monthly_amount > 0:
        detail.forecast_pct = round(committed_forecast / detail.monthly_amount * 100, 1)
    return committed_forecast


async def apply_forecast(
    details: dict[str, CategoryPaceDetail],
    current_month_counts: dict[str, int],
    today: date,
    svc: ForecastService,
    summary: ISpendingSummary,
    run_sync: RunSync,
) -> tuple[float, PaceStatusValue] | None:
    """Set forecast fields on category details; return the overall projection.

    Covers budgeted non-lumpy categories on both sides of the comparison:
    variable categories contribute their projection (or actual spend when no
    projection is possible), fixed categories their posted amount or
    historical mean. Recurring-dominated categories (L14) switch to a committed
    forecast. Returns None when nothing is budgeted monthly.
    """
    keys = forecast_service.month_keys(today)
    window = forecast_service.window_key(keys)

    def _build_tables() -> forecast_service.ForecastTables:
        items = {ym: summary.query_month(ym, forecast_service.FORECAST_PROJECTION) for ym in keys}
        return forecast_service.build_tables(items)

    # Single-flight: get_or_build runs on a worker thread (via run_sync), so its
    # threading.Lock never blocks the event loop, and concurrent cold-cache
    # requests build the window at most once. The builder queries months
    # synchronously inside that one worker call.
    tables = await run_sync(svc.get_or_build, window, _build_tables)

    # Expected recurring charges grouped by category (L14). Fail-open to ``{}``
    # so a missing/erroring upcoming service leaves every curve forecast intact.
    upcoming_by_cat = await _upcoming_charges_by_category(today, run_sync)

    projected_total = 0.0
    budgeted_total = 0.0
    covered = 0

    for cat_name, detail in details.items():
        if detail.category_type == "lumpy":
            continue
        history = tables.categories.get(cat_name)

        if detail.category_type == "variable":
            fc = forecast_service.project_category(
                history,
                detail.current_month_spent,
                current_month_counts.get(cat_name, 0),
                today,
            )
            if fc is not None:
                detail.forecast_month_total = fc.month_total
                detail.forecast_lower = fc.lower
                detail.forecast_upper = fc.upper
                detail.forecast_quality = fc.quality
                if detail.monthly_amount > 0:
                    detail.forecast_pct = round(fc.month_total / detail.monthly_amount * 100, 1)
            contribution = fc.month_total if fc is not None else detail.current_month_spent
        else:  # fixed: actual if posted, else historical mean, else the budgeted amount
            if detail.current_month_spent > 0:
                contribution = detail.current_month_spent
            elif history is not None and history.months_active > 0:
                contribution = history.mean_month_total
            else:
                contribution = detail.monthly_amount
            detail.forecast_month_total = round(contribution, 2)

        cat_charges = upcoming_by_cat.get(cat_name)
        if cat_charges:
            committed = _apply_committed_forecast(detail, history, contribution, cat_charges)
            if committed is not None:
                contribution = committed

        projected_total += contribution
        budgeted_total += detail.monthly_amount
        covered += 1

    if covered == 0 or budgeted_total <= 0:
        return None

    status = compute_status_value(round(budgeted_total - projected_total, 2), budgeted_total)
    return round(projected_total, 2), status


async def build_budget_status(
    targets_item: dict[str, Any],
    groups_item: dict[str, Any] | None,
    year: int,
    compare_year: int | None,
    today: date,
    summary: ISpendingSummary,
    forecast_svc: ForecastService,
    svc: Any,
    run_sync: RunSync,
) -> BudgetStatusResponse:
    """Orchestrate the full budget status response.

    Takes the already-fetched ``targets_item``/``groups_item`` plus injected
    services and the (patchable) ``run_sync`` seam. Performs the parallel
    summary fetch and the fail-open forecast wiring exactly as the route did.
    """
    config = build_config_response(targets_item, groups_item, year)

    elapsed_year_fraction, elapsed_month_fraction = elapsed_fractions(today, year)

    # Fetch all YTD months in parallel (plus compare year if requested)
    current_month_num = today.month if today.year == year else 12
    # Single-year YTD (and full compare year) ranges — always valid and never
    # long enough to trip the range cap, so no max_months is passed.
    month_keys = generate_month_keys(f"{year}-01", f"{year}-{str(current_month_num).zfill(2)}")
    compare_keys = generate_month_keys(f"{compare_year}-01", f"{compare_year}-12") if compare_year else []
    all_summaries = await asyncio.gather(
        *[run_sync(summary.get_summary, ym) for ym in month_keys],
        *[run_sync(summary.get_summary, ym) for ym in compare_keys],
    )
    month_summaries = all_summaries[: len(month_keys)]
    compare_summaries = all_summaries[len(month_keys) :]

    current_month_key = today.strftime("%Y-%m") if today.year == year else f"{year}-12"
    aggregated = aggregate_summaries(month_summaries, compare_summaries, current_month_key, compare_year)

    category_details, overall = build_category_details(
        config, aggregated, elapsed_year_fraction, elapsed_month_fraction, compare_year
    )

    # Historical averages for unbudgeted section
    historical = await run_sync(svc.get_historical_averages, summary)
    hist_cats = historical.get("categories", {})

    # Month-end forecast — fail-open: on any error the response is identical
    # to the pre-forecast shape (all forecast fields stay None).
    if today.year == year:
        try:
            projection = await apply_forecast(
                category_details, aggregated.current_month_counts, today, forecast_svc, summary, run_sync
            )
            if projection is not None:
                overall.projected_month_total, overall.projected_month_status = projection
        except Exception:
            logger.exception("Forecast computation failed — returning pace without projections")

    groups, unbudgeted, monthly_totals, total_prior = build_groups_and_unbudgeted(
        config, category_details, aggregated, hist_cats, elapsed_year_fraction, compare_year
    )

    return BudgetStatusResponse(
        year=year,
        as_of=today.isoformat(),
        elapsed_year_fraction=elapsed_year_fraction,
        overall=overall,
        groups=groups,
        unbudgeted=unbudgeted,
        monthly_totals=monthly_totals,
        prior_year_total=total_prior,
        compare_year=compare_year,
    )
