"""Tests for CategoryIconService (DynamoDB) — CRUD + allowlist + version lock.

Mirrors tests/unit/test_category_icon_service_local.py for the DynamoDB backend,
using the MagicMock-table pattern established in test_category_service.py.
"""

from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from src.finance.category_icon_service import CategoryIconService
from src.finance.exceptions import VersionConflictError


@pytest.fixture
def mock_table() -> MagicMock:
    return MagicMock(name="table")


@pytest.fixture
def svc(mock_table: MagicMock) -> CategoryIconService:
    dyn = MagicMock()
    dyn.Table.return_value = mock_table
    service = CategoryIconService(dyn_resource=dyn)
    # Prevent writes to real filesystem during tests
    service._write_backup = MagicMock(name="_write_backup")
    return service


def _put_item(mock_table: MagicMock) -> dict:
    """Extract the Item dict from the most recent put_item call."""
    return mock_table.put_item.call_args[1]["Item"]


class TestGetIcons:
    def test_returns_item(self, svc: CategoryIconService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {"Item": {"Data": {"dining": "Utensils"}, "Version": 2}}
        result = svc.get_icons()
        assert result is not None
        assert result["Data"] == {"dining": "Utensils"}
        assert result["Version"] == 2

    def test_returns_none_when_not_seeded(self, svc: CategoryIconService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {}
        assert svc.get_icons() is None

    def test_returns_none_on_error(self, svc: CategoryIconService, mock_table: MagicMock) -> None:
        mock_table.get_item.side_effect = Exception("network error")
        assert svc.get_icons() is None

    def test_get_icons_map_empty_when_unseeded(self, svc: CategoryIconService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {}
        assert svc.get_icons_map() == {}

    def test_get_icons_map_returns_data(self, svc: CategoryIconService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {"Item": {"Data": {"dining": "Utensils"}, "Version": 1}}
        assert svc.get_icons_map() == {"dining": "Utensils"}


class TestSetIcon:
    def test_first_set_creates_with_version_one(self, svc: CategoryIconService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {}
        v = svc.set_icon("Dining", "Utensils")

        assert v == 1
        item = _put_item(mock_table)
        assert item["Data"] == {"dining": "Utensils"}
        assert item["Version"] == 1
        # First write uses the attribute_not_exists guard.
        assert mock_table.put_item.call_args[1]["ConditionExpression"] == "attribute_not_exists(Version)"

    def test_lowercases_category_key(self, svc: CategoryIconService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {}
        svc.set_icon("GROCERIES", "ShoppingCart")

        assert _put_item(mock_table)["Data"] == {"groceries": "ShoppingCart"}

    def test_update_existing_increments_version(self, svc: CategoryIconService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {"Item": {"Data": {"dining": "Utensils"}, "Version": 1}}
        v = svc.set_icon("Dining", "Pizza")

        assert v == 2
        item = _put_item(mock_table)
        assert item["Data"] == {"dining": "Pizza"}
        assert item["Version"] == 2
        # Subsequent write asserts the expected version.
        call = mock_table.put_item.call_args[1]
        assert call["ConditionExpression"] == "Version = :expected"
        assert call["ExpressionAttributeValues"][":expected"] == 1

    def test_adds_to_existing_map(self, svc: CategoryIconService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {"Item": {"Data": {"dining": "Utensils"}, "Version": 1}}
        svc.set_icon("Gasoline", "Fuel")

        assert _put_item(mock_table)["Data"] == {
            "dining": "Utensils",
            "gasoline": "Fuel",
        }

    def test_rejects_unknown_icon(self, svc: CategoryIconService, mock_table: MagicMock) -> None:
        with pytest.raises(ValueError, match="not in the allowed icon catalog"):
            svc.set_icon("Dining", "NotARealIcon")
        mock_table.put_item.assert_not_called()


class TestClearIcon:
    def test_removes_entry(self, svc: CategoryIconService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {"Item": {"Data": {"dining": "Utensils", "gasoline": "Fuel"}, "Version": 2}}
        v = svc.clear_icon("Dining")

        assert v == 3
        assert _put_item(mock_table)["Data"] == {"gasoline": "Fuel"}

    def test_case_insensitive(self, svc: CategoryIconService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {"Item": {"Data": {"dining": "Utensils"}, "Version": 1}}
        svc.clear_icon("DINING")

        assert _put_item(mock_table)["Data"] == {}

    def test_noop_when_absent(self, svc: CategoryIconService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {"Item": {"Data": {"dining": "Utensils"}, "Version": 1}}
        v = svc.clear_icon("NotThere")

        assert v == 1
        mock_table.put_item.assert_not_called()

    def test_noop_when_nothing_stored(self, svc: CategoryIconService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {}
        v = svc.clear_icon("Anything")

        assert v == 0
        mock_table.put_item.assert_not_called()


class TestRenameCategory:
    def test_rekeys_override(self, svc: CategoryIconService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {"Item": {"Data": {"dining": "Utensils"}, "Version": 1}}
        v = svc.rename_category("Dining", "Food & Dining")

        assert v == 2
        assert _put_item(mock_table)["Data"] == {"food & dining": "Utensils"}

    def test_noop_when_no_override(self, svc: CategoryIconService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {"Item": {"Data": {"dining": "Utensils"}, "Version": 1}}
        v = svc.rename_category("NotThere", "Other")

        assert v == 1
        mock_table.put_item.assert_not_called()

    def test_noop_when_nothing_stored(self, svc: CategoryIconService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {}
        v = svc.rename_category("A", "B")

        assert v == 0
        mock_table.put_item.assert_not_called()


class TestDeleteCategory:
    def test_removes_entry(self, svc: CategoryIconService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {"Item": {"Data": {"dining": "Utensils", "gasoline": "Fuel"}, "Version": 1}}
        v = svc.delete_category("Dining")

        assert v == 2
        assert _put_item(mock_table)["Data"] == {"gasoline": "Fuel"}

    def test_noop_when_nothing_stored(self, svc: CategoryIconService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {}
        assert svc.delete_category("Anything") == 0
        mock_table.put_item.assert_not_called()


class TestPutAll:
    def test_optimistic_locking_first_write(self, svc: CategoryIconService, mock_table: MagicMock) -> None:
        v = svc._put_all({"dining": "Utensils"}, expected_version=None)

        assert v == 1
        call = mock_table.put_item.call_args[1]
        assert call["ConditionExpression"] == "attribute_not_exists(Version)"
        assert call["Item"]["Version"] == 1

    def test_optimistic_locking_subsequent_write(self, svc: CategoryIconService, mock_table: MagicMock) -> None:
        v = svc._put_all({"dining": "Utensils"}, expected_version=3)

        assert v == 4
        call = mock_table.put_item.call_args[1]
        assert call["ConditionExpression"] == "Version = :expected"
        assert call["ExpressionAttributeValues"][":expected"] == 3
        assert call["Item"]["Version"] == 4

    def test_version_conflict_raises(self, svc: CategoryIconService, mock_table: MagicMock) -> None:
        mock_table.put_item.side_effect = ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        with pytest.raises(VersionConflictError):
            svc._put_all({"dining": "Utensils"}, expected_version=0)

    def test_writes_backup_on_put(self, svc: CategoryIconService, mock_table: MagicMock) -> None:
        svc._put_all({"dining": "Utensils"}, expected_version=None)

        assert isinstance(svc._write_backup, MagicMock)
        svc._write_backup.assert_called_once_with({"dining": "Utensils"})
