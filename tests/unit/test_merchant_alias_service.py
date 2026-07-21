"""Tests for MerchantAliasService — DynamoDB CRUD with MagicMock."""

from unittest.mock import MagicMock, patch

import pytest

from src.finance.merchant_alias_service import MerchantAliasService


def _make_service() -> MerchantAliasService:
    dyn_resource = MagicMock()
    dyn_resource.Table.return_value = MagicMock(name="table")
    return MerchantAliasService(dyn_resource=dyn_resource)


class TestGetAliases:
    def test_returns_none_when_empty(self):
        svc = _make_service()
        svc.table.get_item.return_value = {}
        assert svc.get_aliases() is None

    def test_returns_item_when_present(self):
        item = {
            "PK": "USER#default",
            "SK": "CONFIG#merchant_aliases",
            "Data": {"safeway #1234": "Safeway"},
            "Version": 1,
        }
        svc = _make_service()
        svc.table.get_item.return_value = {"Item": item}
        result = svc.get_aliases()
        assert result is not None
        assert result["Data"]["safeway #1234"] == "Safeway"
        assert result["Version"] == 1

    def test_uses_correct_key(self):
        svc = _make_service()
        svc.table.get_item.return_value = {}
        svc.get_aliases()
        svc.table.get_item.assert_called_once_with(Key={"PK": "USER#default", "SK": "CONFIG#merchant_aliases"})


class TestGetAliasesMap:
    def test_returns_empty_when_no_item(self):
        svc = _make_service()
        svc.table.get_item.return_value = {}
        assert svc.get_aliases_map() == {}

    def test_returns_data_map(self):
        svc = _make_service()
        svc.table.get_item.return_value = {"Item": {"Data": {"safeway": "Safeway"}, "Version": 1}}
        assert svc.get_aliases_map() == {"safeway": "Safeway"}


class TestPutAlias:
    @patch.object(MerchantAliasService, "_write_backup")
    def test_creates_initial_item(self, mock_backup: MagicMock) -> None:
        svc = _make_service()
        svc.table.get_item.return_value = {}  # No existing item
        version = svc.put_alias("safeway", "Safeway")
        assert version == 1
        svc.table.put_item.assert_called_once()
        call_item = svc.table.put_item.call_args[1]["Item"]
        assert call_item["Data"]["safeway"] == "Safeway"
        assert call_item["Version"] == 1

    @patch.object(MerchantAliasService, "_write_backup")
    def test_adds_to_existing(self, mock_backup: MagicMock) -> None:
        svc = _make_service()
        svc.get_aliases = MagicMock(return_value={"Data": {"safeway": "Safeway"}, "Version": 1})
        version = svc.put_alias("costco", "Costco")
        assert version == 2
        call_item = svc.table.put_item.call_args[1]["Item"]
        assert call_item["Data"]["safeway"] == "Safeway"
        assert call_item["Data"]["costco"] == "Costco"

    @patch.object(MerchantAliasService, "_write_backup")
    def test_lowercases_key(self, mock_backup: MagicMock) -> None:
        svc = _make_service()
        svc.table.get_item.return_value = {}
        svc.put_alias("SAFEWAY Store 123", "Safeway")
        call_item = svc.table.put_item.call_args[1]["Item"]
        assert "safeway store 123" in call_item["Data"]


class TestDeleteAlias:
    @patch.object(MerchantAliasService, "_write_backup")
    def test_deletes_existing(self, mock_backup: MagicMock) -> None:
        svc = _make_service()
        svc.get_aliases = MagicMock(return_value={"Data": {"safeway": "Safeway", "costco": "Costco"}, "Version": 2})
        version = svc.delete_alias("safeway")
        assert version == 3
        call_item = svc.table.put_item.call_args[1]["Item"]
        assert "safeway" not in call_item["Data"]
        assert "costco" in call_item["Data"]

    def test_raises_when_not_found(self):
        svc = _make_service()
        svc.get_aliases = MagicMock(return_value={"Data": {"safeway": "Safeway"}, "Version": 1})
        with pytest.raises(KeyError):
            svc.delete_alias("nonexistent")

    def test_raises_when_no_item(self):
        svc = _make_service()
        svc.table.get_item.return_value = {}
        with pytest.raises(KeyError):
            svc.delete_alias("anything")
