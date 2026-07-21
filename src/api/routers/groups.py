"""Category group CRUD endpoints (independent of budget targets)."""

from fastapi import APIRouter, Depends, Query, Request

from src.api.activity import stage_before
from src.api.dependencies import get_budget_service, run_sync
from src.api.models import BudgetGroupConfig, GroupsResponse, GroupsUpdateRequest
from src.api.utils import run_with_conflict_handling
from src.finance.budget_service import DEFAULT_GROUPS
from src.finance.demo_clock import app_today
from src.finance.protocols import IBudgetService

router = APIRouter(tags=["groups"])


@router.get(
    "/groups",
    response_model=GroupsResponse,
    operation_id="getGroups",
    summary="Get budget category groups for a year",
)
async def get_groups(
    year: int | None = Query(None, ge=2020, le=2099),
    svc: IBudgetService = Depends(get_budget_service),
):
    if year is None:
        year = app_today().year

    item = await run_sync(svc.get_groups, year)
    if item is None:
        return GroupsResponse(
            year=year,
            groups=[BudgetGroupConfig(name=g["name"], categories=g["categories"]) for g in DEFAULT_GROUPS],
            version=0,
        )

    groups_data = item.get("Data", {}).get("groups", DEFAULT_GROUPS)
    version = int(item.get("Version", 0))

    return GroupsResponse(
        year=year,
        groups=[BudgetGroupConfig(name=g["name"], categories=g["categories"]) for g in groups_data],
        version=version,
    )


@router.put(
    "/groups",
    response_model=GroupsResponse,
    operation_id="putGroups",
    summary="Replace budget category groups for a year",
)
async def put_groups(
    body: GroupsUpdateRequest,
    request: Request,
    year: int | None = Query(None, ge=2020, le=2099),
    svc: IBudgetService = Depends(get_budget_service),
):
    if year is None:
        year = app_today().year

    # Pre-mutation before-image (L5): the current groups document for this year,
    # read before the replace so revert can re-put it.
    before_item = await run_sync(svc.get_groups, year)

    groups_data = {"groups": [{"name": g.name, "categories": g.categories} for g in body.groups]}

    await run_with_conflict_handling(
        run_sync,
        svc.put_groups,
        year,
        groups_data,
        body.version,
        detail="Version conflict — groups were modified concurrently",
    )

    # "year" rides in both images: it is the storage key (a query param, absent
    # from the path), and revert needs it to address the row.
    stage_before(
        request,
        resource="groups",
        before={"groups": before_item.get("Data"), "year": year} if before_item else {"year": year},
        after={"groups": groups_data, "year": year},
        summary=f"updated category groups for {year}",
    )

    svc.invalidate_cache()

    # Re-read to return consistent data
    item = await run_sync(svc.get_groups, year)
    groups_out = item.get("Data", {}).get("groups", DEFAULT_GROUPS) if item else DEFAULT_GROUPS
    new_version = int(item.get("Version", 0)) if item else 0

    return GroupsResponse(
        year=year,
        groups=[BudgetGroupConfig(name=g["name"], categories=g["categories"]) for g in groups_out],
        version=new_version,
    )
