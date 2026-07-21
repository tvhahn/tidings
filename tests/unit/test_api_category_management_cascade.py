"""Direct unit tests for the category cascade helpers in src/finance/category_cascade.py.

The router endpoints already have happy-path tests in test_api_category_management.py,
but those tests mock the cascade helpers (cascade_overrides, cascade_budget,
remove_category_from_*, add_category_to_group). This file exercises those helpers
directly so the iteration / version-bump / case-insensitive-key logic is covered.

The helpers are plain synchronous service calls, so plain MagicMock services work
without any further mocking.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

import src.finance.demo_clock as demo_clock
from src.api.routers.category_management import _get_groups_for_year
from src.finance.budget_service import DEFAULT_GROUPS
from src.finance.category_cascade import (
    add_category_to_group,
    cascade_budget,
    cascade_overrides,
    remove_category_from_budget,
    remove_category_from_group,
    remove_category_from_overrides,
)

# ---------------------------------------------------------------------------
# _get_groups_for_year — fallback to DEFAULT_GROUPS when item is None
# ---------------------------------------------------------------------------


class TestGetGroupsForYear:
    def test_returns_stored_groups(self) -> None:
        budget = MagicMock(name="budget")
        custom = [{"name": "Custom", "categories": ["foo"]}]
        budget.get_groups.return_value = {"Data": {"groups": custom}, "Version": 1}

        groups = _get_groups_for_year(budget, 2026)

        assert groups == custom
        budget.get_groups.assert_called_once_with(2026)

    def test_falls_back_to_defaults_when_item_is_none(self) -> None:
        budget = MagicMock(name="budget")
        budget.get_groups.return_value = None

        groups = _get_groups_for_year(budget, 2026)

        assert groups == DEFAULT_GROUPS

    def test_falls_back_when_item_has_no_groups_key(self) -> None:
        budget = MagicMock(name="budget")
        budget.get_groups.return_value = {"Data": {}, "Version": 1}

        groups = _get_groups_for_year(budget, 2026)

        assert groups == DEFAULT_GROUPS


# ---------------------------------------------------------------------------
# cascade_overrides — rename a category in the override map
# ---------------------------------------------------------------------------


class TestCascadeOverrides:
    def test_returns_zero_when_no_overrides_item(self) -> None:
        svc = MagicMock(name="svc")
        svc.get_overrides.return_value = None

        count = cascade_overrides(svc, "Old", "New")

        assert count == 0
        svc.put_all_overrides.assert_not_called()

    def test_returns_zero_when_no_matching_values(self) -> None:
        svc = MagicMock(name="svc")
        svc.get_overrides.return_value = {
            "Data": {"Store A": "Groceries", "Store B": "Rent"},
            "Version": 4,
        }

        count = cascade_overrides(svc, "Travel", "Vacation")

        assert count == 0
        svc.put_all_overrides.assert_not_called()

    def test_renames_matching_values_case_insensitive(self) -> None:
        svc = MagicMock(name="svc")
        svc.get_overrides.return_value = {
            "Data": {
                "Store A": "Groceries",
                "Store B": "groceries",  # lowercase, still matches
                "Store C": "Rent",
            },
            "Version": 2,
        }

        count = cascade_overrides(svc, "GROCERIES", "Food")

        assert count == 2
        svc.put_all_overrides.assert_called_once()
        updated, version = svc.put_all_overrides.call_args.args
        assert updated == {"Store A": "Food", "Store B": "Food", "Store C": "Rent"}
        assert version == 2


# ---------------------------------------------------------------------------
# remove_category_from_overrides — drop entries pointing to the deleted category
# ---------------------------------------------------------------------------


class TestRemoveCategoryFromOverrides:
    def test_returns_zero_when_no_overrides_item(self) -> None:
        svc = MagicMock(name="svc")
        svc.get_overrides.return_value = None

        count = remove_category_from_overrides(svc, "Travel")

        assert count == 0
        svc.put_all_overrides.assert_not_called()

    def test_returns_zero_when_no_matching_values(self) -> None:
        svc = MagicMock(name="svc")
        svc.get_overrides.return_value = {
            "Data": {"Store A": "Groceries"},
            "Version": 1,
        }

        count = remove_category_from_overrides(svc, "Travel")

        assert count == 0
        svc.put_all_overrides.assert_not_called()

    def test_removes_matching_entries(self) -> None:
        svc = MagicMock(name="svc")
        svc.get_overrides.return_value = {
            "Data": {
                "Store A": "Groceries",
                "Store B": "groceries",
                "Store C": "Rent",
            },
            "Version": 5,
        }

        count = remove_category_from_overrides(svc, "Groceries")

        assert count == 2
        updated, version = svc.put_all_overrides.call_args.args
        assert updated == {"Store C": "Rent"}
        assert version == 5


# ---------------------------------------------------------------------------
# cascade_budget — rename a category in budget targets and groups
# ---------------------------------------------------------------------------


class TestCascadeBudget:
    def test_returns_false_when_neither_targets_nor_groups_exist(self) -> None:
        budget = MagicMock(name="budget")
        budget.get_targets.return_value = None
        budget.get_groups.return_value = None

        changed = cascade_budget(budget, "Old", "New")

        assert changed is False
        budget.put_targets.assert_not_called()
        budget.put_groups.assert_not_called()

    def test_renames_in_targets_case_insensitive(self, freeze_clock) -> None:
        budget = MagicMock(name="budget")
        # The helper computes the target year from app_today() internally; freeze
        # demo_clock (which app_today reads) so the asserted year is stable
        # regardless of when the test runs.
        freeze_clock(demo_clock)
        year = 2026
        budget.get_targets.return_value = {
            "Data": {
                "categories": {"groceries": {"target": 600}, "rent": {"target": 2000}},
            },
            "Version": 3,
        }
        budget.get_groups.return_value = None

        changed = cascade_budget(budget, "GROCERIES", "Food")

        assert changed is True
        budget.put_targets.assert_called_once()
        called_year, data, version = budget.put_targets.call_args.args
        assert called_year == year
        assert "food" in data["categories"]
        assert "groceries" not in data["categories"]
        assert data["categories"]["food"] == {"target": 600}
        assert version == 3

    def test_no_targets_change_when_no_match(self) -> None:
        budget = MagicMock(name="budget")
        budget.get_targets.return_value = {
            "Data": {"categories": {"rent": {"target": 2000}}},
            "Version": 1,
        }
        budget.get_groups.return_value = None

        changed = cascade_budget(budget, "Travel", "Vacation")

        assert changed is False
        budget.put_targets.assert_not_called()

    def test_renames_in_groups(self) -> None:
        budget = MagicMock(name="budget")
        budget.get_targets.return_value = None
        budget.get_groups.return_value = {
            "Data": {
                "groups": [
                    {"name": "Food", "categories": ["groceries", "dining"]},
                    {"name": "Housing", "categories": ["rent"]},
                ]
            },
            "Version": 7,
        }

        changed = cascade_budget(budget, "groceries", "Pantry")

        assert changed is True
        _, data, version = budget.put_groups.call_args.args
        food_group = next(g for g in data["groups"] if g["name"] == "Food")
        assert "pantry" in food_group["categories"]
        assert "groceries" not in food_group["categories"]
        assert version == 7

    def test_renames_in_both_targets_and_groups(self) -> None:
        budget = MagicMock(name="budget")
        budget.get_targets.return_value = {
            "Data": {"categories": {"groceries": {"target": 600}}},
            "Version": 1,
        }
        budget.get_groups.return_value = {
            "Data": {"groups": [{"name": "Food", "categories": ["groceries"]}]},
            "Version": 2,
        }

        changed = cascade_budget(budget, "groceries", "Pantry")

        assert changed is True
        budget.put_targets.assert_called_once()
        budget.put_groups.assert_called_once()


# ---------------------------------------------------------------------------
# remove_category_from_budget — drop a category from targets and groups
# ---------------------------------------------------------------------------


class TestRemoveCategoryFromBudget:
    def test_no_op_when_neither_targets_nor_groups_exist(self) -> None:
        budget = MagicMock(name="budget")
        budget.get_targets.return_value = None
        budget.get_groups.return_value = None

        remove_category_from_budget(budget, "Travel")

        budget.put_targets.assert_not_called()
        budget.put_groups.assert_not_called()

    def test_removes_from_targets_case_insensitive(self) -> None:
        budget = MagicMock(name="budget")
        budget.get_targets.return_value = {
            "Data": {"categories": {"groceries": {"target": 600}, "rent": {"target": 2000}}},
            "Version": 4,
        }
        budget.get_groups.return_value = None

        remove_category_from_budget(budget, "GROCERIES")

        _, data, version = budget.put_targets.call_args.args
        assert "groceries" not in data["categories"]
        assert "rent" in data["categories"]
        assert version == 4

    def test_no_targets_write_when_no_match(self) -> None:
        budget = MagicMock(name="budget")
        budget.get_targets.return_value = {
            "Data": {"categories": {"rent": {"target": 2000}}},
            "Version": 1,
        }
        budget.get_groups.return_value = None

        remove_category_from_budget(budget, "Travel")

        budget.put_targets.assert_not_called()

    def test_removes_from_groups(self) -> None:
        budget = MagicMock(name="budget")
        budget.get_targets.return_value = None
        budget.get_groups.return_value = {
            "Data": {
                "groups": [
                    {"name": "Food", "categories": ["groceries", "dining"]},
                    {"name": "Other", "categories": ["misc"]},
                ]
            },
            "Version": 3,
        }

        remove_category_from_budget(budget, "groceries")

        _, data, version = budget.put_groups.call_args.args
        food_group = next(g for g in data["groups"] if g["name"] == "Food")
        assert food_group["categories"] == ["dining"]
        assert version == 3

    def test_no_groups_write_when_no_match(self) -> None:
        budget = MagicMock(name="budget")
        budget.get_targets.return_value = None
        budget.get_groups.return_value = {
            "Data": {"groups": [{"name": "Food", "categories": ["groceries"]}]},
            "Version": 1,
        }

        remove_category_from_budget(budget, "Travel")

        budget.put_groups.assert_not_called()


# ---------------------------------------------------------------------------
# remove_category_from_group — pull a category out of one named group
# ---------------------------------------------------------------------------


class TestRemoveCategoryFromGroup:
    def test_no_op_when_no_groups_item(self) -> None:
        budget = MagicMock(name="budget")
        budget.get_groups.return_value = None

        remove_category_from_group(budget, "groceries", "Food")

        budget.put_groups.assert_not_called()

    def test_removes_from_named_group(self) -> None:
        budget = MagicMock(name="budget")
        budget.get_groups.return_value = {
            "Data": {
                "groups": [
                    {"name": "Food", "categories": ["groceries", "dining"]},
                    {"name": "Housing", "categories": ["groceries"]},  # same name in other group
                ]
            },
            "Version": 5,
        }

        remove_category_from_group(budget, "GROCERIES", "Food")

        _, data, version = budget.put_groups.call_args.args
        food_group = next(g for g in data["groups"] if g["name"] == "Food")
        housing_group = next(g for g in data["groups"] if g["name"] == "Housing")
        # Removed only from Food, untouched in Housing.
        assert food_group["categories"] == ["dining"]
        assert "groceries" in housing_group["categories"]
        assert version == 5

    def test_no_write_when_group_missing_category(self) -> None:
        budget = MagicMock(name="budget")
        budget.get_groups.return_value = {
            "Data": {"groups": [{"name": "Food", "categories": ["dining"]}]},
            "Version": 1,
        }

        remove_category_from_group(budget, "groceries", "Food")

        budget.put_groups.assert_not_called()

    def test_no_write_when_target_group_does_not_exist(self) -> None:
        budget = MagicMock(name="budget")
        budget.get_groups.return_value = {
            "Data": {"groups": [{"name": "Food", "categories": ["groceries"]}]},
            "Version": 1,
        }

        remove_category_from_group(budget, "groceries", "Bogus")

        budget.put_groups.assert_not_called()


# ---------------------------------------------------------------------------
# add_category_to_group — add a category to a named group, dedup on case
# ---------------------------------------------------------------------------


class TestAddCategoryToGroup:
    def test_creates_groups_from_defaults_when_missing(self) -> None:
        budget = MagicMock(name="budget")
        budget.get_groups.return_value = None

        add_category_to_group(budget, "Travel", "Food & Dining")

        budget.put_groups.assert_called_once()
        called = budget.put_groups.call_args.args
        # put_groups called with (year, data, expected_version)
        _, data, expected_version = called
        food_group = next(g for g in data["groups"] if g["name"] == "Food & Dining")
        assert "travel" in food_group["categories"]
        assert expected_version is None  # signals "create" to the service

    def test_appends_to_existing_group(self) -> None:
        budget = MagicMock(name="budget")
        budget.get_groups.return_value = {
            "Data": {
                "groups": [
                    {"name": "Food", "categories": ["groceries"]},
                    {"name": "Housing", "categories": ["rent"]},
                ]
            },
            "Version": 8,
        }

        add_category_to_group(budget, "Dining", "Food")

        _, data, expected_version = budget.put_groups.call_args.args
        food_group = next(g for g in data["groups"] if g["name"] == "Food")
        assert "dining" in food_group["categories"]
        assert "groceries" in food_group["categories"]
        assert expected_version == 8

    def test_dedups_when_already_present_case_insensitive(self) -> None:
        budget = MagicMock(name="budget")
        budget.get_groups.return_value = {
            "Data": {
                "groups": [
                    {"name": "Food", "categories": ["groceries"]},
                ]
            },
            "Version": 1,
        }

        add_category_to_group(budget, "GROCERIES", "Food")

        _, data, _ = budget.put_groups.call_args.args
        food_group = next(g for g in data["groups"] if g["name"] == "Food")
        # Single entry, lowercase preserved; no second copy added.
        assert food_group["categories"] == ["groceries"]


# ---------------------------------------------------------------------------
# Smoke: hypothesis-style sanity check that DEFAULT_GROUPS itself has the shape
# the helpers depend on. Cheap insurance against a refactor of the constants.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("group", DEFAULT_GROUPS)
def test_default_groups_have_expected_keys(group: dict[str, Any]) -> None:
    assert "name" in group
    assert "categories" in group
    assert isinstance(group["categories"], list)
