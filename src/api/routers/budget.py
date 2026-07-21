"""Budget endpoints: config CRUD, pace status, historical averages."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.api.activity import stage_before
from src.api.dependencies import get_budget_service, get_forecast_service, get_spending_summary, run_sync
from src.api.models import (
    BudgetConfigResponse,
    BudgetConfigUpdateRequest,
    BudgetStatusResponse,
    HistoricalAveragesResponse,
    HistoricalCategoryAverage,
)
from src.api.routers.budget_helpers import build_budget_status, build_config_response
from src.api.utils import run_with_conflict_handling
from src.finance.demo_clock import app_today
from src.finance.forecast_service import ForecastService
from src.finance.protocols import IBudgetService, ISpendingSummary

router = APIRouter(tags=["budget"])


@router.get(
    "/budget/config",
    response_model=BudgetConfigResponse,
    operation_id="getBudgetConfig",
    summary="Get budget targets and groups for a year",
)
async def get_config(
    year: int = Query(..., ge=2020, le=2099),
    svc: IBudgetService = Depends(get_budget_service),
):
    targets_item = await run_sync(svc.get_targets, year)
    if targets_item is None:
        raise HTTPException(status_code=404, detail="No budget configured for this year")

    groups_item = await run_sync(svc.get_groups, year)
    return build_config_response(targets_item, groups_item, year)


@router.put(
    "/budget/config",
    response_model=BudgetConfigResponse,
    operation_id="putBudgetConfig",
    summary="Replace budget targets and groups for a year",
)
async def put_config(
    body: BudgetConfigUpdateRequest,
    request: Request,
    year: int = Query(..., ge=2020, le=2099),
    svc: IBudgetService = Depends(get_budget_service),
):
    # Pre-mutation before-image (L5): the current targets + groups documents for
    # this year, read before the replace so revert can re-put them.
    before_targets_item = await run_sync(svc.get_targets, year)
    before_groups_item = await run_sync(svc.get_groups, year)

    targets_data = {
        "spending_ceiling": body.spending_ceiling,
        "categories": {
            name: {
                "target": cat.target,
                "input_mode": cat.input_mode,
                "category_type": cat.category_type,
            }
            for name, cat in body.categories.items()
        },
    }
    groups_data = {"groups": [{"name": g.name, "categories": g.categories} for g in body.groups]}

    await run_with_conflict_handling(
        run_sync,
        svc.put_targets,
        year,
        targets_data,
        body.targets_version,
        detail="Version conflict — budget was modified concurrently",
    )
    await run_with_conflict_handling(
        run_sync,
        svc.put_groups,
        year,
        groups_data,
        body.groups_version,
        detail="Version conflict — budget was modified concurrently",
    )

    before_doc: dict[str, object] = {}
    if before_targets_item is not None:
        before_doc["targets"] = before_targets_item.get("Data")
    if before_groups_item is not None:
        before_doc["groups"] = before_groups_item.get("Data")
    # "year" rides in both images: it is the storage key (a query param, absent
    # from the path), and revert needs it to address the row.
    stage_before(
        request,
        resource="budget_config",
        before={**before_doc, "year": year},
        after={"targets": targets_data, "groups": groups_data, "year": year},
        summary=f"updated budget config for {year}",
    )

    svc.invalidate_cache()

    # Re-read to return consistent data
    targets_item = await run_sync(svc.get_targets, year)
    # We just wrote targets above via put_targets/put_groups, so the row
    # is guaranteed to exist on re-read.
    assert targets_item is not None  # noqa: S101 — type-narrowing; None case handled above
    groups_item = await run_sync(svc.get_groups, year)
    return build_config_response(targets_item, groups_item, year)


@router.get(
    "/budget/status",
    response_model=BudgetStatusResponse,
    operation_id="getBudgetStatus",
    summary="YTD budget pace status with per-category and per-group breakdown",
)
async def get_status(
    year: int = Query(..., ge=2020, le=2099),
    compare_year: int | None = Query(None, ge=2020, le=2099),
    svc: IBudgetService = Depends(get_budget_service),
    summary: ISpendingSummary = Depends(get_spending_summary),
    forecast_svc: ForecastService = Depends(get_forecast_service),
):
    targets_item = await run_sync(svc.get_targets, year)
    if targets_item is None:
        raise HTTPException(status_code=404, detail="No budget configured for this year")

    groups_item = await run_sync(svc.get_groups, year)

    return await build_budget_status(
        targets_item=targets_item,
        groups_item=groups_item,
        year=year,
        compare_year=compare_year,
        today=app_today(),
        summary=summary,
        forecast_svc=forecast_svc,
        svc=svc,
        run_sync=run_sync,
    )


@router.get(
    "/budget/historical-averages",
    response_model=HistoricalAveragesResponse,
    operation_id="getBudgetHistoricalAverages",
    summary="Per-category historical monthly averages over the last N months",
)
async def get_historical_averages(
    months: int = Query(6, ge=2, le=12),
    svc: IBudgetService = Depends(get_budget_service),
    summary: ISpendingSummary = Depends(get_spending_summary),
):
    raw = await run_sync(svc.get_historical_averages, summary, months)

    categories = {
        cat: HistoricalCategoryAverage(
            monthly_avg=info["monthly_avg"],
            total=info["total"],
            months_active=info["months_active"],
            suggested_type=info["suggested_type"],
            suggested_monthly=info["suggested_monthly"],
            suggested_annual=info["suggested_annual"],
        )
        for cat, info in raw.get("categories", {}).items()
    }

    return HistoricalAveragesResponse(
        months_analyzed=raw["months_analyzed"],
        period=raw.get("period", {}),
        categories=categories,
    )
