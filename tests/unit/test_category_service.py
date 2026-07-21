"""Tests for CategoryService."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.finance import category_service
from src.finance.category_service import CategoryService, CategoryServiceBase


@pytest.fixture
def mock_table() -> MagicMock:
    return MagicMock(name="table")


@pytest.fixture
def svc(mock_table: MagicMock) -> CategoryService:
    dyn = MagicMock()
    dyn.Table.return_value = mock_table
    service = CategoryService(dyn_resource=dyn)
    # Prevent writes to real filesystem during tests
    service._write_backup = MagicMock(name="_write_backup")
    return service


class TestGetCategories:
    def test_returns_item(self, svc: CategoryService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {"Item": {"Data": ["Groceries", "Rent"], "Version": 3}}
        result = svc.get_categories()
        assert result is not None
        assert result["Data"] == ["Groceries", "Rent"]
        assert result["Version"] == 3

    def test_returns_none_when_missing(self, svc: CategoryService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {}
        assert svc.get_categories() is None

    def test_returns_none_on_error(self, svc: CategoryService, mock_table: MagicMock) -> None:
        mock_table.get_item.side_effect = Exception("network error")
        assert svc.get_categories() is None


class TestGetCategoriesList:
    def test_from_dynamo(self, svc: CategoryService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {"Item": {"Data": ["Groceries", "Rent"], "Version": 1}}
        assert svc.get_categories_list() == ["Groceries", "Rent"]

    def test_falls_back_to_json(self, svc: CategoryService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {}
        with patch.object(svc, "_load_from_json", return_value=["Alpha", "Beta"]):
            result = svc.get_categories_list()
        assert result == ["Alpha", "Beta"]


class TestAddCategory:
    def test_adds_new_category(self, svc: CategoryService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {"Item": {"Data": ["Groceries", "Rent"], "Version": 1}}
        result = svc.add_category("Travel")
        assert result == 2
        call_args = mock_table.put_item.call_args
        item = call_args[1]["Item"] if "Item" in call_args[1] else call_args[0][0]
        cats = item["Data"]
        assert "Travel" in cats
        assert cats == sorted(cats, key=str.lower)

    def test_rejects_duplicate_case_insensitive(self, svc: CategoryService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {"Item": {"Data": ["Groceries", "Rent"], "Version": 1}}
        with pytest.raises(ValueError, match="already exists"):
            svc.add_category("groceries")

    def test_seeds_from_json_when_no_dynamo(self, svc: CategoryService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {}
        with patch.object(svc, "_load_from_json", return_value=["Groceries"]):
            result = svc.add_category("Travel")
        assert result == 1
        call_args = mock_table.put_item.call_args
        item = call_args[1]["Item"]
        assert "Groceries" in item["Data"]
        assert "Travel" in item["Data"]


class TestRenameCategory:
    def test_renames_in_place(self, svc: CategoryService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {"Item": {"Data": ["Groceries", "Rent"], "Version": 2}}
        result = svc.rename_category("Rent", "Housing Rent")
        assert result == 3
        call_args = mock_table.put_item.call_args
        cats = call_args[1]["Item"]["Data"]
        assert "Housing Rent" in cats
        assert "Rent" not in cats

    def test_rejects_protected_category(self, svc: CategoryService, mock_table: MagicMock) -> None:
        with pytest.raises(ValueError, match="cannot be renamed"):
            svc.rename_category("Miscellaneous", "Other")

    def test_rejects_missing_category(self, svc: CategoryService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {"Item": {"Data": ["Groceries"], "Version": 1}}
        with pytest.raises(ValueError, match="not found"):
            svc.rename_category("Nonexistent", "New Name")

    def test_rejects_rename_to_existing(self, svc: CategoryService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {"Item": {"Data": ["Groceries", "Rent"], "Version": 1}}
        with pytest.raises(ValueError, match="already exists"):
            svc.rename_category("Groceries", "rent")

    def test_case_insensitive_find(self, svc: CategoryService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {"Item": {"Data": ["Groceries", "Rent"], "Version": 1}}
        result = svc.rename_category("groceries", "Food")
        assert result == 2


class TestDeleteCategory:
    def test_deletes_category(self, svc: CategoryService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {"Item": {"Data": ["Groceries", "Rent"], "Version": 1}}
        result = svc.delete_category("Rent")
        assert result == 2
        call_args = mock_table.put_item.call_args
        cats = call_args[1]["Item"]["Data"]
        assert "Rent" not in cats
        assert "Groceries" in cats

    def test_rejects_protected_category(self, svc: CategoryService, mock_table: MagicMock) -> None:
        with pytest.raises(ValueError, match="cannot be deleted"):
            svc.delete_category("Miscellaneous")

    def test_rejects_missing_category(self, svc: CategoryService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {"Item": {"Data": ["Groceries"], "Version": 1}}
        with pytest.raises(ValueError, match="not found"):
            svc.delete_category("Nonexistent")

    def test_case_insensitive_delete(self, svc: CategoryService, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {"Item": {"Data": ["Groceries", "Rent"], "Version": 1}}
        result = svc.delete_category("rent")
        assert result == 2


class TestPutAll:
    def test_optimistic_locking_first_write(self, svc: CategoryService, mock_table: MagicMock) -> None:
        svc._put_all(["A", "B"], expected_version=None)
        call_args = mock_table.put_item.call_args
        assert call_args[1]["ConditionExpression"] == "attribute_not_exists(Version)"
        assert call_args[1]["Item"]["Version"] == 1

    def test_optimistic_locking_subsequent_write(self, svc: CategoryService, mock_table: MagicMock) -> None:
        svc._put_all(["A", "B"], expected_version=3)
        call_args = mock_table.put_item.call_args
        assert call_args[1]["ConditionExpression"] == "Version = :expected"
        assert call_args[1]["ExpressionAttributeValues"][":expected"] == 3
        assert call_args[1]["Item"]["Version"] == 4

    def test_writes_json_backup(self, svc: CategoryService, mock_table: MagicMock) -> None:
        svc._put_all(["A", "B"], expected_version=None)
        assert isinstance(svc._write_backup, MagicMock)
        svc._write_backup.assert_called_once_with(["A", "B"])


class TestBackupPaths:
    """The backup must write to gitignored data/config/, never the tracked seed."""

    def test_write_backup_targets_personal_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        personal = tmp_path / "data" / "config"
        seed = tmp_path / "seed"
        seed.mkdir()
        (seed / "categories.json").write_text('["Seed"]\n')
        monkeypatch.setattr(category_service, "_PERSONAL_DIR", personal)
        monkeypatch.setattr(category_service, "_CONFIG_DIR", seed)

        CategoryServiceBase()._write_backup(["Groceries", "Rent"])

        assert json.loads((personal / "categories.json").read_text()) == ["Groceries", "Rent"]
        assert json.loads((seed / "categories.json").read_text()) == ["Seed"]

    def test_load_prefers_personal_backup(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        personal = tmp_path / "data" / "config"
        personal.mkdir(parents=True)
        (personal / "categories.json").write_text('["Personal"]\n')
        seed = tmp_path / "seed"
        seed.mkdir()
        (seed / "categories.json").write_text('["Seed"]\n')
        monkeypatch.setattr(category_service, "_PERSONAL_DIR", personal)
        monkeypatch.setattr(category_service, "_CONFIG_DIR", seed)

        assert CategoryServiceBase()._load_from_json() == ["Personal"]

    def test_load_falls_back_to_seed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        seed = tmp_path / "seed"
        seed.mkdir()
        (seed / "categories.json").write_text('["Seed"]\n')
        monkeypatch.setattr(category_service, "_PERSONAL_DIR", tmp_path / "missing")
        monkeypatch.setattr(category_service, "_CONFIG_DIR", seed)

        assert CategoryServiceBase()._load_from_json() == ["Seed"]
