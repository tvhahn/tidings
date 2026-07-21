"""Category management CRUD endpoints with cascade rename/delete."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import (
    get_budget_service,
    get_category_icon_service,
    get_category_service,
    get_override_service,
    get_transactions_db,
    run_sync,
)
from src.api.models import (
    CategoriesManagementResponse,
    CategoryAddRequest,
    CategoryDeleteResponse,
    CategoryGroupUpdateRequest,
    CategoryGroupUpdateResponse,
    CategoryIconsResponse,
    CategoryRenameRequest,
    CategoryRenameResponse,
    CategoryUsageResponse,
    CategoryWithGroup,
    SetCategoryIconRequest,
)
from src.api.utils import run_with_conflict_handling
from src.finance.budget_service import DEFAULT_GROUPS
from src.finance.category_cascade import (
    add_category_to_group,
    cascade_budget,
    cascade_overrides,
    remove_category_from_budget,
    remove_category_from_group,
    remove_category_from_overrides,
)
from src.finance.config_loader import invalidate_categories_cache
from src.finance.demo_clock import app_today
from src.finance.protocols import (
    IBudgetService,
    ICategoryIconService,
    ICategoryService,
    IOverrideService,
    ITransactionsDB,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["category-management"])


def _build_group_map(groups: list[dict[str, Any]]) -> dict[str, str]:
    """Build a lowercase-category → group-name map."""
    result: dict[str, str] = {}
    for g in groups:
        for cat in g.get("categories", []):
            result[cat.lower()] = g["name"]
    return result


def _get_groups_for_year(budget_svc: IBudgetService, year: int) -> list[dict[str, Any]]:
    """Get groups from DynamoDB or fall back to defaults."""
    item = budget_svc.get_groups(year)
    if item is not None:
        return item.get("Data", {}).get("groups", DEFAULT_GROUPS)
    return DEFAULT_GROUPS


@router.get(
    "/categories/managed",
    response_model=CategoriesManagementResponse,
    operation_id="listManagedCategories",
    summary="List categories with their group memberships and version",
)
async def list_managed_categories(
    cat_svc: ICategoryService = Depends(get_category_service),
    budget_svc: IBudgetService = Depends(get_budget_service),
):
    item = await run_sync(cat_svc.get_categories)
    if item is None:
        # Fall back to JSON
        categories = await run_sync(cat_svc.get_categories_list)
        version = 0
    else:
        categories = list(item.get("Data", []))
        version = int(item.get("Version", 0))

    year = app_today().year
    groups = await run_sync(_get_groups_for_year, budget_svc, year)
    group_map = _build_group_map(groups)
    group_names = sorted({g["name"] for g in groups})

    cat_with_groups = [CategoryWithGroup(name=c, group=group_map.get(c.lower())) for c in categories]

    return CategoriesManagementResponse(
        categories=cat_with_groups,
        count=len(categories),
        version=version,
        groups=group_names,
    )


# ---------------------------------------------------------------------------
# Category icon overrides
# (Defined early so /categories/icons wins route matching over
#  /categories/{old_name} and /categories/{name}. This ordering matters more
#  now that the rename/delete/usage routes use `:path` params — a `{name:path}`
#  segment would otherwise swallow `/categories/icons`. FastAPI matches in
#  registration order, so the icon routes above still resolve first.)
# ---------------------------------------------------------------------------


@router.get(
    "/categories/icons",
    response_model=CategoryIconsResponse,
    operation_id="listCategoryIcons",
    summary="Map of user-set category icon overrides",
)
async def list_category_icons(
    icon_svc: ICategoryIconService = Depends(get_category_icon_service),
):
    """Return the full map of user-set category icon overrides."""
    item = await run_sync(icon_svc.get_icons)
    if item is None:
        return CategoryIconsResponse(icons={}, version=0)
    return CategoryIconsResponse(
        icons=dict(item.get("Data", {})),
        version=int(item.get("Version", 0)),
    )


@router.put(
    "/categories/icons",
    response_model=CategoryIconsResponse,
    operation_id="setCategoryIcon",
    summary="Set or update a category's icon override",
)
async def set_category_icon(
    body: SetCategoryIconRequest,
    name: str = Query(..., description="Category name (case-insensitive key)"),
    icon_svc: ICategoryIconService = Depends(get_category_icon_service),
):
    """Set or update the icon override for a category.

    Name is a query parameter so category names containing slashes
    (e.g., "Restaurant/Dining") work without FastAPI path-param issues.
    """
    try:
        await run_with_conflict_handling(run_sync, icon_svc.set_icon, name, body.icon)
    except ValueError as e:
        # set_icon raises only for an icon outside the allowed catalog — an
        # invalid request value.
        raise HTTPException(status_code=422, detail=str(e)) from e
    return await list_category_icons(icon_svc)


@router.delete(
    "/categories/icons",
    response_model=CategoryIconsResponse,
    operation_id="clearCategoryIcon",
    summary="Remove a category's icon override (revert to default)",
)
async def clear_category_icon(
    name: str = Query(..., description="Category name (case-insensitive key)"),
    icon_svc: ICategoryIconService = Depends(get_category_icon_service),
):
    """Remove the icon override for a category (revert to default)."""
    await run_with_conflict_handling(run_sync, icon_svc.clear_icon, name)
    return await list_category_icons(icon_svc)


@router.post(
    "/categories",
    response_model=CategoriesManagementResponse,
    operation_id="addCategory",
    summary="Add a category, optionally placing it in a budget group",
)
async def add_category(
    body: CategoryAddRequest,
    cat_svc: ICategoryService = Depends(get_category_service),
    budget_svc: IBudgetService = Depends(get_budget_service),
):
    try:
        await run_with_conflict_handling(run_sync, cat_svc.add_category, body.name)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    # If group specified, add category to that budget group
    if body.group:
        await run_sync(add_category_to_group, budget_svc, body.name, body.group)

    invalidate_categories_cache()
    return await list_managed_categories(cat_svc, budget_svc)


# Registered before the `{old_name:path}` rename route below: the `:path`
# converter matches slashes greedily, so a two-segment PUT like
# `/categories/Groceries/group` would otherwise be swallowed by the rename
# route. This more-specific `/group` suffix route must win, so it comes first.
@router.put(
    "/categories/{name}/group",
    response_model=CategoryGroupUpdateResponse,
    operation_id="updateCategoryGroup",
    summary="Move a category to a different budget group, or remove from all groups",
)
async def update_category_group(
    name: str,
    body: CategoryGroupUpdateRequest,
    budget_svc: IBudgetService = Depends(get_budget_service),
):
    """Move a category to a different budget group, or remove from all groups."""
    year = app_today().year
    groups = await run_sync(_get_groups_for_year, budget_svc, year)
    group_map = _build_group_map(groups)
    old_group = group_map.get(name.lower())

    new_group = body.group

    # No-op if already in the target group
    if old_group == new_group:
        return CategoryGroupUpdateResponse(category=name, old_group=old_group, new_group=new_group)

    # Remove from old group (if any)
    if old_group:
        await run_sync(remove_category_from_group, budget_svc, name, old_group)

    # Add to new group (if specified)
    if new_group:
        await run_sync(add_category_to_group, budget_svc, name, new_group)

    return CategoryGroupUpdateResponse(category=name, old_group=old_group, new_group=new_group)


@router.put(
    "/categories/{old_name:path}",
    response_model=CategoryRenameResponse,
    operation_id="renameCategory",
    summary="Rename a category and cascade across overrides, budget, transactions",
)
async def rename_category(
    old_name: str,
    body: CategoryRenameRequest,
    cat_svc: ICategoryService = Depends(get_category_service),
    override_svc: IOverrideService = Depends(get_override_service),
    budget_svc: IBudgetService = Depends(get_budget_service),
    icon_svc: ICategoryIconService = Depends(get_category_icon_service),
    db: ITransactionsDB = Depends(get_transactions_db),
):
    new_name = body.new_name

    # 1. Rename in categories list
    try:
        await run_with_conflict_handling(run_sync, cat_svc.rename_category, old_name, new_name)
    except ValueError as e:
        # rename_category raises for several distinct meanings (not found,
        # name already exists, protected category) under one exception; the
        # message is the only discriminator. Rather than parse it, use a
        # deliberately coarse 409 (matching add_category above) — all are
        # request/state conflicts the caller must resolve.
        raise HTTPException(status_code=409, detail=str(e)) from e

    # 2. Update overrides: find values matching old name → replace with new name
    overrides_updated = await run_sync(cascade_overrides, override_svc, old_name, new_name)

    # 3. Update budget groups/targets: rekey to new name
    budget_groups_updated = await run_sync(cascade_budget, budget_svc, old_name, new_name)

    # 4. Rekey icon override (if any) to the new name
    await run_with_conflict_handling(run_sync, icon_svc.rename_category, old_name, new_name)

    # 5. Scan DynamoDB transactions with old category → batch update
    items = await run_sync(db.scan_by_category, old_name)
    transactions_updated = 0
    if items:
        transactions_updated = await run_sync(db.batch_update_category, items, new_name, "category_rename")

    invalidate_categories_cache()

    return CategoryRenameResponse(
        old_name=old_name,
        new_name=new_name,
        transactions_updated=transactions_updated,
        overrides_updated=overrides_updated,
        budget_groups_updated=budget_groups_updated,
    )


@router.delete(
    "/categories/{name:path}",
    response_model=CategoryDeleteResponse,
    operation_id="deleteCategory",
    summary="Delete a category, optionally reassigning its transactions",
)
async def delete_category(
    name: str,
    reassign_to: str | None = Query(None),
    cat_svc: ICategoryService = Depends(get_category_service),
    db: ITransactionsDB = Depends(get_transactions_db),
    override_svc: IOverrideService = Depends(get_override_service),
    budget_svc: IBudgetService = Depends(get_budget_service),
    icon_svc: ICategoryIconService = Depends(get_category_icon_service),
):
    # Check transaction count first
    txn_count = await run_sync(db.count_by_category, name)
    if txn_count > 0 and not reassign_to:
        raise HTTPException(
            status_code=409,
            detail=f"Category '{name}' has {txn_count} transactions. Provide reassign_to parameter.",
        )

    # Reassign transactions if needed
    transactions_reassigned = 0
    if txn_count > 0 and reassign_to:
        items = await run_sync(db.scan_by_category, name)
        transactions_reassigned = await run_sync(db.batch_update_category, items, reassign_to, "category_delete")

    # Remove from overrides (values matching this category)
    await run_sync(remove_category_from_overrides, override_svc, name)

    # Remove from budget groups
    await run_sync(remove_category_from_budget, budget_svc, name)

    # Remove icon override (if any)
    await run_with_conflict_handling(run_sync, icon_svc.delete_category, name)

    # Delete from categories list
    try:
        await run_with_conflict_handling(run_sync, cat_svc.delete_category, name)
    except ValueError as e:
        # delete_category raises for distinct meanings (not found, protected
        # category) under one exception; the message is the only discriminator.
        # Rather than parse it, use a deliberately coarse 409 (matching
        # add_category above) — both are conflicts the caller must resolve.
        raise HTTPException(status_code=409, detail=str(e)) from e

    invalidate_categories_cache()

    return CategoryDeleteResponse(
        deleted_name=name,
        transactions_reassigned=transactions_reassigned,
        reassigned_to=reassign_to,
    )


@router.get(
    "/categories/{name:path}/usage",
    response_model=CategoryUsageResponse,
    operation_id="getCategoryUsage",
    summary="Counts of transactions, overrides, and budget membership for a category",
)
async def get_category_usage(
    name: str,
    db: ITransactionsDB = Depends(get_transactions_db),
    override_svc: IOverrideService = Depends(get_override_service),
    budget_svc: IBudgetService = Depends(get_budget_service),
):
    txn_count = await run_sync(db.count_by_category, name)

    # Count overrides pointing to this category
    override_item = await run_sync(override_svc.get_overrides)
    override_count = 0
    if override_item:
        data = override_item.get("Data", {})
        override_count = sum(1 for v in data.values() if v.lower() == name.lower())

    # Check budget membership
    year = app_today().year
    targets_item = await run_sync(budget_svc.get_targets, year)
    in_budget = False
    if targets_item:
        cats = targets_item.get("Data", {}).get("categories", {})
        in_budget = name.lower() in {k.lower() for k in cats}

    # Check group membership
    groups = await run_sync(_get_groups_for_year, budget_svc, year)
    group_map = _build_group_map(groups)
    in_group = group_map.get(name.lower())

    return CategoryUsageResponse(
        category=name,
        transaction_count=txn_count,
        override_count=override_count,
        in_budget=in_budget,
        in_group=in_group,
    )
