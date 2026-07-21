"""Consistency check: every default category lives in exactly one default group.

Catches the orphan-bug class where a category exists in `categories.json` but
isn't placed in any `DEFAULT_GROUPS` bucket (so the Settings UI can't render
it under any group), and the inverse where a group references a category
that no longer exists in the default set.
"""

from src.finance.budget_service_base import DEFAULT_GROUPS
from src.finance.config_loader import get_categories


def _norm(s: str) -> str:
    return s.strip().lower()


def test_every_default_category_appears_in_exactly_one_group() -> None:
    categories = {_norm(c) for c in get_categories()}
    grouped: list[str] = []
    for group in DEFAULT_GROUPS:
        grouped.extend(_norm(c) for c in group["categories"])

    grouped_set = set(grouped)

    missing = categories - grouped_set
    extra = grouped_set - categories
    duplicates = [c for c in grouped_set if grouped.count(c) > 1]

    assert not missing, f"Categories not assigned to any group: {sorted(missing)}"
    assert not extra, f"Groups reference unknown categories: {sorted(extra)}"
    assert not duplicates, f"Categories appearing in multiple groups: {sorted(duplicates)}"


def test_miscellaneous_is_grouped() -> None:
    """Miscellaneous is the protected default — must always have a home."""
    grouped = {_norm(c) for group in DEFAULT_GROUPS for c in group["categories"]}
    assert "miscellaneous" in grouped


def test_default_group_names_unique() -> None:
    names = [g["name"] for g in DEFAULT_GROUPS]
    assert len(names) == len(set(names)), f"Duplicate group names: {names}"
