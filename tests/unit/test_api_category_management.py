"""Tests for category management API endpoints."""

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from src.finance import demo_clock
from tests.asserts import assert_ok, assert_problem

# 2026-12-31 16:30 Pacific == 2027-01-01 00:30 UTC. Pacific-expressed so
# ``freeze_clock`` makes ``app_today()`` resolve the Pacific date (year 2026).
_YEAR_BOUNDARY = datetime(2026, 12, 31, 16, 30, tzinfo=ZoneInfo("America/Los_Angeles"))


def _mock_cat_item(categories: list[str] | None = None, version: int = 1) -> dict[str, Any]:
    """Build a fake DynamoDB categories item."""
    return {
        "Data": categories or ["Groceries", "Miscellaneous", "Rent"],
        "Version": version,
    }


def _mock_groups_item(groups: list[dict[str, Any]] | None = None, version: int = 1) -> dict[str, Any]:
    """Build a fake DynamoDB groups item."""
    return {
        "Data": {
            "groups": groups
            or [
                {"name": "Food & Dining", "categories": ["groceries"]},
                {"name": "Housing", "categories": ["rent"]},
            ]
        },
        "Version": version,
    }


# ---------------------------------------------------------------------------
# GET /api/v1/categories/managed
# ---------------------------------------------------------------------------


class TestListManagedCategories:
    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_returns_categories_with_groups(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.side_effect = [
            _mock_cat_item(),  # get_categories
            [  # _get_groups_for_year
                {"name": "Food & Dining", "categories": ["groceries"]},
                {"name": "Housing", "categories": ["rent"]},
            ],
        ]

        resp = api_client.get("/api/v1/categories/managed")
        assert_ok(resp)
        data = resp.json()
        assert data["count"] == 3
        assert data["version"] == 1
        assert len(data["groups"]) == 2

        names = [c["name"] for c in data["categories"]]
        assert "Groceries" in names
        assert "Rent" in names

        # Check group assignment
        groceries = next(c for c in data["categories"] if c["name"] == "Groceries")
        assert groceries["group"] == "Food & Dining"

        misc = next(c for c in data["categories"] if c["name"] == "Miscellaneous")
        assert misc["group"] is None

    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_year_read_uses_app_timezone_not_utc(self, mock_run_sync: AsyncMock, api_client, freeze_clock) -> None:
        # The handler resolves "this year" for _get_groups_for_year from
        # app_today(). Frozen at 2026-12-31 16:30 Pacific (== 2027-01-01 UTC),
        # it must pass 2026, not the container's UTC 2027.
        freeze_clock(demo_clock, at=_YEAR_BOUNDARY)  # router reads app_today() → demo_clock
        mock_run_sync.side_effect = [
            _mock_cat_item(),  # get_categories
            [{"name": "Food & Dining", "categories": ["groceries"]}],  # _get_groups_for_year
        ]
        resp = api_client.get("/api/v1/categories/managed")
        assert_ok(resp)
        # Second run_sync call is _get_groups_for_year(budget_svc, year).
        year_arg = mock_run_sync.call_args_list[1].args[2]
        assert year_arg == 2026

    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_falls_back_to_json(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.side_effect = [
            None,  # get_categories returns None
            ["Groceries", "Rent"],  # get_categories_list fallback
            [{"name": "Food & Dining", "categories": ["groceries"]}],
        ]

        resp = api_client.get("/api/v1/categories/managed")
        assert_ok(resp)
        data = resp.json()
        assert data["count"] == 2
        assert data["version"] == 0


# ---------------------------------------------------------------------------
# POST /api/v1/categories
# ---------------------------------------------------------------------------


class TestAddCategory:
    @patch("src.api.routers.category_management.add_category_to_group", new_callable=MagicMock)
    @patch("src.api.routers.category_management.invalidate_categories_cache")
    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_add_category(
        self, mock_invalidate: MagicMock, mock_add_group: MagicMock, mock_run_sync: AsyncMock, api_client
    ) -> None:
        # add_category returns new version
        mock_run_sync.side_effect = [
            2,  # add_category
            _mock_cat_item(["Groceries", "Miscellaneous", "Rent", "Travel"], version=2),
            [{"name": "Food & Dining", "categories": ["groceries"]}],
        ]

        resp = api_client.post(
            "/api/v1/categories",
            json={"name": "Travel", "group": None},
        )
        assert_ok(resp)
        data = resp.json()
        assert data["count"] == 4
        mock_invalidate.assert_called_once()

    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_add_duplicate_returns_409(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.side_effect = ValueError("Category 'Groceries' already exists")

        resp = api_client.post(
            "/api/v1/categories",
            json={"name": "Groceries"},
        )
        assert_problem(resp, 409)

    @patch("src.api.routers.category_management.add_category_to_group", new_callable=MagicMock)
    @patch("src.api.routers.category_management.invalidate_categories_cache")
    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_add_with_group(
        self, mock_invalidate: MagicMock, mock_add_group: MagicMock, mock_run_sync: AsyncMock, api_client
    ) -> None:
        mock_run_sync.side_effect = [
            2,  # add_category
            None,  # add_category_to_group (dispatched via run_sync; return ignored)
            _mock_cat_item(["Groceries", "Miscellaneous", "Rent", "Travel"], version=2),
            [{"name": "Entertainment", "categories": ["travel"]}],
        ]

        resp = api_client.post(
            "/api/v1/categories",
            json={"name": "Travel", "group": "Entertainment"},
        )
        assert_ok(resp)
        # The helper is now dispatched through run_sync, so assert it was the
        # function handed to run_sync exactly once.
        add_dispatches = [c for c in mock_run_sync.call_args_list if c.args and c.args[0] is mock_add_group]
        assert len(add_dispatches) == 1


# ---------------------------------------------------------------------------
# Endpoint PUT /api/v1/categories/{old_name}
# ---------------------------------------------------------------------------


class TestRenameCategory:
    @patch("src.api.routers.category_management.invalidate_categories_cache")
    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_rename_with_cascade(self, mock_invalidate: MagicMock, mock_run_sync: AsyncMock, api_client) -> None:
        # cascade_overrides / cascade_budget are now dispatched through run_sync,
        # so their return values come straight from the run_sync sequence.
        mock_run_sync.side_effect = [
            3,  # rename_category
            1,  # cascade_overrides → overrides_updated
            True,  # cascade_budget → budget_groups_updated
            1,  # icon_svc.rename_category (cascade)
            [{"ForwardedTo": "u@e.com", "DateFileName": "2026.01.01_00.00_test.eml"}],  # scan
            1,  # batch_update_category
        ]

        resp = api_client.put(
            "/api/v1/categories/Groceries",
            json={"new_name": "Food"},
        )
        assert_ok(resp)
        data = resp.json()
        assert data["old_name"] == "Groceries"
        assert data["new_name"] == "Food"
        assert data["transactions_updated"] == 1
        assert data["overrides_updated"] == 1
        assert data["budget_groups_updated"] is True
        mock_invalidate.assert_called_once()

    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_rename_protected_returns_409(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.side_effect = ValueError("'Miscellaneous' cannot be renamed")

        resp = api_client.put(
            "/api/v1/categories/Miscellaneous",
            json={"new_name": "Other"},
        )
        assert_problem(resp, 409)


# ---------------------------------------------------------------------------
# Endpoint DELETE /api/v1/categories/{name}
# ---------------------------------------------------------------------------


class TestDeleteCategory:
    @patch("src.api.routers.category_management.invalidate_categories_cache")
    @patch("src.api.routers.category_management.remove_category_from_overrides", new_callable=MagicMock)
    @patch("src.api.routers.category_management.remove_category_from_budget", new_callable=MagicMock)
    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_delete_unused(
        self, mock_rmb: MagicMock, mock_rmo: MagicMock, mock_invalidate: MagicMock, mock_run_sync: AsyncMock, api_client
    ) -> None:
        mock_run_sync.side_effect = [
            0,  # count_by_category
            None,  # remove_category_from_overrides (dispatched via run_sync)
            None,  # remove_category_from_budget (dispatched via run_sync)
            0,  # icon_svc.delete_category (cascade, no-op returns 0)
            2,  # delete_category
        ]

        resp = api_client.delete("/api/v1/categories/Travel")
        assert_ok(resp)
        data = resp.json()
        assert data["deleted_name"] == "Travel"
        assert data["transactions_reassigned"] == 0

    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_delete_with_transactions_no_reassign_returns_409(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = 5  # count_by_category

        resp = api_client.delete("/api/v1/categories/Groceries")
        assert_problem(resp, 409)
        assert "5 transactions" in resp.json()["error"]

    @patch("src.api.routers.category_management.invalidate_categories_cache")
    @patch("src.api.routers.category_management.remove_category_from_overrides", new_callable=MagicMock)
    @patch("src.api.routers.category_management.remove_category_from_budget", new_callable=MagicMock)
    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_delete_with_reassign(
        self, mock_rmb: MagicMock, mock_rmo: MagicMock, mock_invalidate: MagicMock, mock_run_sync: AsyncMock, api_client
    ) -> None:
        mock_run_sync.side_effect = [
            3,  # count_by_category
            [  # scan_by_category
                {"ForwardedTo": "u@e.com", "DateFileName": "a.eml"},
                {"ForwardedTo": "u@e.com", "DateFileName": "b.eml"},
                {"ForwardedTo": "u@e.com", "DateFileName": "c.eml"},
            ],
            3,  # batch_update_category
            None,  # remove_category_from_overrides (dispatched via run_sync)
            None,  # remove_category_from_budget (dispatched via run_sync)
            0,  # icon_svc.delete_category (cascade)
            2,  # delete_category
        ]

        resp = api_client.delete("/api/v1/categories/Groceries?reassign_to=Food")
        assert_ok(resp)
        data = resp.json()
        assert data["transactions_reassigned"] == 3
        assert data["reassigned_to"] == "Food"

    @patch("src.api.routers.category_management.remove_category_from_overrides", new_callable=MagicMock)
    @patch("src.api.routers.category_management.remove_category_from_budget", new_callable=MagicMock)
    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_delete_protected_returns_409(
        self, mock_rmb: MagicMock, mock_rmo: MagicMock, mock_run_sync: AsyncMock, api_client
    ) -> None:
        mock_run_sync.side_effect = [
            0,  # count_by_category
            None,  # remove_category_from_overrides (dispatched via run_sync)
            None,  # remove_category_from_budget (dispatched via run_sync)
            0,  # icon_svc.delete_category (cascade, no-op)
            ValueError("'Miscellaneous' cannot be deleted"),  # delete_category
        ]

        resp = api_client.delete("/api/v1/categories/Miscellaneous")
        assert_problem(resp, 409)


# ---------------------------------------------------------------------------
# Endpoint GET /api/v1/categories/{name}/usage
# ---------------------------------------------------------------------------


class TestCategoryUsage:
    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_returns_usage_info(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.side_effect = [
            5,  # count_by_category
            {"Data": {"Store A": "Groceries", "Store B": "Rent"}, "Version": 1},  # get_overrides
            {  # get_targets
                "Data": {"categories": {"groceries": {"target": 400}}},
                "Version": 1,
            },
            [  # _get_groups_for_year
                {"name": "Food & Dining", "categories": ["groceries"]},
            ],
        ]

        resp = api_client.get("/api/v1/categories/Groceries/usage")
        assert_ok(resp)
        data = resp.json()
        assert data["category"] == "Groceries"
        assert data["transaction_count"] == 5
        assert data["override_count"] == 1
        assert data["in_budget"] is True
        assert data["in_group"] == "Food & Dining"

    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_unused_category(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.side_effect = [
            0,  # count_by_category
            {"Data": {}, "Version": 1},  # get_overrides
            None,  # get_targets (no budget)
            [{"name": "Food & Dining", "categories": ["groceries"]}],
        ]

        resp = api_client.get("/api/v1/categories/NewCategory/usage")
        assert_ok(resp)
        data = resp.json()
        assert data["transaction_count"] == 0
        assert data["override_count"] == 0
        assert data["in_budget"] is False
        assert data["in_group"] is None


# ---------------------------------------------------------------------------
# Endpoint PUT /api/v1/categories/{name}/group
# ---------------------------------------------------------------------------


class TestUpdateCategoryGroup:
    @patch("src.api.routers.category_management.add_category_to_group", new_callable=MagicMock)
    @patch("src.api.routers.category_management.remove_category_from_group", new_callable=MagicMock)
    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_move_to_new_group(
        self, mock_remove: MagicMock, mock_add: MagicMock, mock_run_sync: AsyncMock, api_client
    ) -> None:
        mock_run_sync.return_value = [
            {"name": "Food & Dining", "categories": ["groceries"]},
            {"name": "Shopping", "categories": ["clothing"]},
        ]

        resp = api_client.put(
            "/api/v1/categories/Groceries/group",
            json={"group": "Shopping"},
        )
        assert_ok(resp)
        data = resp.json()
        assert data["category"] == "Groceries"
        assert data["old_group"] == "Food & Dining"
        assert data["new_group"] == "Shopping"
        # Both helpers are dispatched through run_sync, once each.
        dispatched = [c.args[0] for c in mock_run_sync.call_args_list if c.args]
        assert dispatched.count(mock_remove) == 1
        assert dispatched.count(mock_add) == 1

    @patch("src.api.routers.category_management.remove_category_from_group", new_callable=MagicMock)
    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_remove_from_group(self, mock_remove: MagicMock, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = [
            {"name": "Food & Dining", "categories": ["groceries"]},
        ]

        resp = api_client.put(
            "/api/v1/categories/Groceries/group",
            json={"group": None},
        )
        assert_ok(resp)
        data = resp.json()
        assert data["old_group"] == "Food & Dining"
        assert data["new_group"] is None
        dispatched = [c.args[0] for c in mock_run_sync.call_args_list if c.args]
        assert dispatched.count(mock_remove) == 1

    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_noop_same_group(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = [
            {"name": "Food & Dining", "categories": ["groceries"]},
        ]

        resp = api_client.put(
            "/api/v1/categories/Groceries/group",
            json={"group": "Food & Dining"},
        )
        assert_ok(resp)
        data = resp.json()
        assert data["old_group"] == "Food & Dining"
        assert data["new_group"] == "Food & Dining"


# ---------------------------------------------------------------------------
# Category icon overrides: GET / PUT / DELETE /api/v1/categories/icons
# ---------------------------------------------------------------------------


class TestCategoryIcons:
    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_list_empty_when_unseeded(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = None  # get_icons

        resp = api_client.get("/api/v1/categories/icons")
        assert_ok(resp)
        assert resp.json() == {"icons": {}, "version": 0}

    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_list_returns_map(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = {
            "Data": {"dining": "Utensils", "gasoline": "Fuel"},
            "Version": 3,
        }

        resp = api_client.get("/api/v1/categories/icons")
        assert_ok(resp)
        data = resp.json()
        assert data["icons"] == {"dining": "Utensils", "gasoline": "Fuel"}
        assert data["version"] == 3

    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_set_icon(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.side_effect = [
            2,  # set_icon returns new version
            {"Data": {"dining": "Pizza"}, "Version": 2},  # list reread
        ]

        resp = api_client.put(
            "/api/v1/categories/icons?name=Dining",
            json={"icon": "Pizza"},
        )
        assert_ok(resp)
        data = resp.json()
        assert data["icons"] == {"dining": "Pizza"}
        assert data["version"] == 2

    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_set_icon_rejects_unknown(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.side_effect = ValueError("Icon 'NotARealIcon' is not in the allowed icon catalog")

        resp = api_client.put(
            "/api/v1/categories/icons?name=Dining",
            json={"icon": "NotARealIcon"},
        )
        assert_problem(resp, 422)

    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_set_icon_supports_slashes_in_name(self, mock_run_sync: AsyncMock, api_client) -> None:
        """Regression: categories like 'Restaurant/Dining' must be settable via query param."""
        mock_run_sync.side_effect = [
            1,  # set_icon
            {"Data": {"restaurant/dining": "Pizza"}, "Version": 1},  # reread
        ]

        resp = api_client.put(
            "/api/v1/categories/icons?name=Restaurant%2FDining",
            json={"icon": "Pizza"},
        )
        assert_ok(resp)
        assert resp.json()["icons"] == {"restaurant/dining": "Pizza"}

    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_clear_icon(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.side_effect = [
            3,  # clear_icon
            {"Data": {}, "Version": 3},  # list reread
        ]

        resp = api_client.delete("/api/v1/categories/icons?name=Dining")
        assert_ok(resp)
        data = resp.json()
        assert data["icons"] == {}
        assert data["version"] == 3


# ---------------------------------------------------------------------------
# Slash-bearing category names route via `:path` params (A6 / L3)
# ---------------------------------------------------------------------------


class TestSlashBearingCategoryNames:
    """Category names containing `/` (e.g. "Restaurant/Dining") must route to the
    rename/delete/usage handlers verbatim via the `:path` converters — before the
    change these were 404s because `{name}` stops at the first slash."""

    @patch("src.api.routers.category_management.invalidate_categories_cache")
    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_rename_routes_with_slash(self, mock_invalidate: MagicMock, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.side_effect = [
            3,  # rename_category
            1,  # cascade_overrides
            True,  # cascade_budget
            1,  # icon_svc.rename_category
            [],  # scan_by_category
        ]

        resp = api_client.put(
            "/api/v1/categories/Restaurant/Dining",
            json={"new_name": "Dining"},
        )
        assert_ok(resp)
        # Handler received the full slash-bearing name, not a truncated segment.
        assert mock_run_sync.call_args_list[0].args[1] == "Restaurant/Dining"

    @patch("src.api.routers.category_management.invalidate_categories_cache")
    @patch("src.api.routers.category_management.remove_category_from_overrides", new_callable=MagicMock)
    @patch("src.api.routers.category_management.remove_category_from_budget", new_callable=MagicMock)
    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_delete_routes_with_slash(
        self, mock_rmb: MagicMock, mock_rmo: MagicMock, mock_invalidate: MagicMock, mock_run_sync: AsyncMock, api_client
    ) -> None:
        mock_run_sync.side_effect = [
            0,  # count_by_category
            None,  # remove_category_from_overrides
            None,  # remove_category_from_budget
            0,  # icon_svc.delete_category
            2,  # delete_category
        ]

        resp = api_client.delete("/api/v1/categories/Restaurant/Dining")
        assert_ok(resp)
        assert resp.json()["deleted_name"] == "Restaurant/Dining"
        assert mock_run_sync.call_args_list[0].args[1] == "Restaurant/Dining"

    @pytest.mark.parametrize("mock_run_sync", ["category_management"], indirect=True)
    def test_usage_routes_with_slash(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.side_effect = [
            0,  # count_by_category
            {"Data": {}, "Version": 1},  # get_overrides
            None,  # get_targets
            [],  # _get_groups_for_year
        ]

        resp = api_client.get("/api/v1/categories/Restaurant/Dining/usage")
        assert_ok(resp)
        assert resp.json()["category"] == "Restaurant/Dining"
        assert mock_run_sync.call_args_list[0].args[1] == "Restaurant/Dining"
