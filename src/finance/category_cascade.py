"""Category rename/delete cascade helpers (backend-agnostic, synchronous).

When a category is renamed or deleted, the change must ripple through the
override map and the budget targets/groups for the current year. These six
helpers own that ripple. They are plain synchronous service calls — the API
router drives them through ``run_sync`` — and they carry no HTTP concerns
(no FastAPI, no ``HTTPException``).

Every mutation is an optimistic-lock read-modify-write routed through
:func:`src.finance.versioned_update.versioned_update`, which owns the
write/skip mechanic; :func:`item_version` owns the version extraction.

Quirks are load-bearing and preserved exactly:

* :func:`cascade_overrides` writes ``new_name`` verbatim, while
  :func:`cascade_budget` rekeys targets/groups to ``new_name.lower()``.
* :func:`add_category_to_group` uses ``expected_version=None`` (a "create"
  signal) when it materializes groups from ``DEFAULT_GROUPS``.
* Category matching is case-insensitive everywhere it exists today.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.finance.budget_service import DEFAULT_GROUPS
from src.finance.demo_clock import app_today
from src.finance.versioned_update import Update, item_version, versioned_update

if TYPE_CHECKING:
    from src.finance.protocols import IBudgetService, IOverrideService


def cascade_overrides(override_svc: IOverrideService, old_name: str, new_name: str) -> int:
    """Rename category values in overrides. Returns count of updated entries."""
    item = override_svc.get_overrides()
    if item is None:
        return 0

    data = dict(item.get("Data", {}))
    count = 0
    updated = {}
    for company, category in data.items():
        if category.lower() == old_name.lower():
            updated[company] = new_name
            count += 1
        else:
            updated[company] = category

    versioned_update(
        lambda: Update(data=updated, version=item_version(item)) if count > 0 else None,
        override_svc.put_all_overrides,
    )

    return count


def remove_category_from_overrides(override_svc: IOverrideService, name: str) -> int:
    """Remove override entries whose value matches the deleted category."""
    item = override_svc.get_overrides()
    if item is None:
        return 0

    data = dict(item.get("Data", {}))
    to_remove = [k for k, v in data.items() if v.lower() == name.lower()]
    if not to_remove:
        return 0

    for k in to_remove:
        del data[k]

    versioned_update(
        lambda: Update(data=data, version=item_version(item)),
        override_svc.put_all_overrides,
    )
    return len(to_remove)


def cascade_budget(budget_svc: IBudgetService, old_name: str, new_name: str) -> bool:
    """Rename category in budget targets and groups. Returns True if any change was made."""
    year = app_today().year
    changed = False

    # Update targets
    targets_item = budget_svc.get_targets(year)
    if targets_item:
        data = dict(targets_item.get("Data", {}))
        cats = data.get("categories", {})
        # Find case-insensitive match
        old_key = None
        for k in cats:
            if k.lower() == old_name.lower():
                old_key = k
                break
        if old_key is not None:
            cats[new_name.lower()] = cats.pop(old_key)
            data["categories"] = cats
            versioned_update(
                lambda: Update(data=data, version=item_version(targets_item)),
                lambda d, v: budget_svc.put_targets(year, d, v),
            )
            changed = True

    # Update groups
    groups_item = budget_svc.get_groups(year)
    if groups_item:
        data = dict(groups_item.get("Data", {}))
        groups = data.get("groups", [])
        group_changed = False
        for g in groups:
            new_cats = []
            for c in g.get("categories", []):
                if c.lower() == old_name.lower():
                    new_cats.append(new_name.lower())
                    group_changed = True
                else:
                    new_cats.append(c)
            g["categories"] = new_cats
        if group_changed:
            data["groups"] = groups
            versioned_update(
                lambda: Update(data=data, version=item_version(groups_item)),
                lambda d, v: budget_svc.put_groups(year, d, v),
            )
            changed = True

    return changed


def remove_category_from_budget(budget_svc: IBudgetService, name: str) -> None:
    """Remove category from budget targets and groups."""
    year = app_today().year

    # Remove from targets
    targets_item = budget_svc.get_targets(year)
    if targets_item:
        data = dict(targets_item.get("Data", {}))
        cats = data.get("categories", {})
        old_key = None
        for k in cats:
            if k.lower() == name.lower():
                old_key = k
                break
        if old_key is not None:
            del cats[old_key]
            data["categories"] = cats
            versioned_update(
                lambda: Update(data=data, version=item_version(targets_item)),
                lambda d, v: budget_svc.put_targets(year, d, v),
            )

    # Remove from groups
    groups_item = budget_svc.get_groups(year)
    if groups_item:
        data = dict(groups_item.get("Data", {}))
        groups = data.get("groups", [])
        group_changed = False
        for g in groups:
            new_cats = [c for c in g.get("categories", []) if c.lower() != name.lower()]
            if len(new_cats) != len(g.get("categories", [])):
                group_changed = True
            g["categories"] = new_cats
        if group_changed:
            data["groups"] = groups
            versioned_update(
                lambda: Update(data=data, version=item_version(groups_item)),
                lambda d, v: budget_svc.put_groups(year, d, v),
            )


def remove_category_from_group(budget_svc: IBudgetService, category_name: str, group_name: str) -> None:
    """Remove a category from a specific budget group."""
    year = app_today().year
    groups_item = budget_svc.get_groups(year)
    if groups_item is None:
        return

    data = dict(groups_item.get("Data", {}))
    groups = data.get("groups", [])
    changed = False
    for g in groups:
        if g["name"] == group_name:
            new_cats = [c for c in g.get("categories", []) if c.lower() != category_name.lower()]
            if len(new_cats) != len(g.get("categories", [])):
                g["categories"] = new_cats
                changed = True
            break

    if changed:
        data["groups"] = groups
        versioned_update(
            lambda: Update(data=data, version=item_version(groups_item)),
            lambda d, v: budget_svc.put_groups(year, d, v),
        )


def add_category_to_group(budget_svc: IBudgetService, category_name: str, group_name: str) -> None:
    """Add a category to a budget group."""
    year = app_today().year
    groups_item = budget_svc.get_groups(year)

    expected_version: int | None
    if groups_item is None:
        # Create from defaults
        groups = [dict(g) for g in DEFAULT_GROUPS]
        for g in groups:
            g["categories"] = list(g["categories"])
        expected_version = None
    else:
        data = groups_item.get("Data", {})
        groups = data.get("groups", [])
        expected_version = item_version(groups_item)

    # Find the target group and add category
    for g in groups:
        if g["name"] == group_name:
            cat_lower = category_name.lower()
            if cat_lower not in [c.lower() for c in g.get("categories", [])]:
                g["categories"].append(cat_lower)
            break

    groups_data: dict[str, Any] = {"groups": groups}
    versioned_update(
        lambda: Update(data=groups_data, version=expected_version),
        lambda d, v: budget_svc.put_groups(year, d, v),
    )
