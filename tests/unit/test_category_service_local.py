"""Parity tests for CategoryServiceLocal — SQLite implementation of category list CRUD.

Mirrors test_category_service.py behavior against an in-memory SQLite backend.
"""

from pathlib import Path

import pytest

from src.finance.category_service_local import CategoryServiceLocal
from src.finance.exceptions import VersionConflictError


@pytest.fixture
def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CategoryServiceLocal:
    monkeypatch.setattr(CategoryServiceLocal, "_write_backup", lambda self, *a, **kw: None)
    # Point JSON-fallback load to an empty list so tests start clean
    monkeypatch.setattr(CategoryServiceLocal, "_load_from_json", lambda self: [])
    return CategoryServiceLocal(db_path=tmp_path / "test.db", user_id="test")


class TestGetCategories:
    def test_returns_none_when_not_seeded(self, service: CategoryServiceLocal) -> None:
        assert service.get_categories() is None

    def test_get_categories_list_falls_back_to_json_when_unseeded(self, service: CategoryServiceLocal) -> None:
        # _load_from_json is stubbed to return [] in the fixture
        assert service.get_categories_list() == []


class TestAddCategory:
    def test_first_add_creates_item_with_version_one(self, service: CategoryServiceLocal) -> None:
        v = service.add_category("Groceries")

        assert v == 1
        item = service.get_categories()
        assert item is not None
        assert "Groceries" in item["Data"]

    def test_second_add_increments_version(self, service: CategoryServiceLocal) -> None:
        service.add_category("Groceries")
        v = service.add_category("Rent")

        assert v == 2

    def test_categories_kept_sorted_case_insensitive(self, service: CategoryServiceLocal) -> None:
        service.add_category("rent")
        service.add_category("Groceries")
        service.add_category("apple")

        item = service.get_categories()
        assert item is not None
        assert item["Data"] == ["apple", "Groceries", "rent"]

    def test_duplicate_name_raises_value_error(self, service: CategoryServiceLocal) -> None:
        service.add_category("Groceries")

        with pytest.raises(ValueError, match="already exists"):
            service.add_category("groceries")  # case-insensitive


class TestRenameCategory:
    def test_renames_in_place_and_sorts(self, service: CategoryServiceLocal) -> None:
        service.add_category("Apples")
        service.add_category("Zebra")

        service.rename_category("Apples", "Oranges")

        item = service.get_categories()
        assert item is not None
        data = item["Data"]
        assert "Oranges" in data
        assert "Apples" not in data

    def test_rename_missing_raises(self, service: CategoryServiceLocal) -> None:
        service.add_category("Groceries")

        with pytest.raises(ValueError, match="not found"):
            service.rename_category("Nonexistent", "X")

    def test_rename_to_existing_raises(self, service: CategoryServiceLocal) -> None:
        service.add_category("Groceries")
        service.add_category("Rent")

        with pytest.raises(ValueError, match="already exists"):
            service.rename_category("Rent", "groceries")  # case-insensitive

    def test_rename_protected_miscellaneous_raises(self, service: CategoryServiceLocal) -> None:
        service.add_category("Miscellaneous")

        with pytest.raises(ValueError, match="cannot be renamed"):
            service.rename_category("Miscellaneous", "Other")


class TestDeleteCategory:
    def test_removes_entry(self, service: CategoryServiceLocal) -> None:
        service.add_category("Groceries")
        service.add_category("Rent")

        service.delete_category("Groceries")

        item = service.get_categories()
        assert item is not None
        assert item["Data"] == ["Rent"]

    def test_delete_missing_raises(self, service: CategoryServiceLocal) -> None:
        service.add_category("Groceries")

        with pytest.raises(ValueError, match="not found"):
            service.delete_category("Nothing")

    def test_delete_protected_miscellaneous_raises(self, service: CategoryServiceLocal) -> None:
        service.add_category("Miscellaneous")

        with pytest.raises(ValueError, match="cannot be deleted"):
            service.delete_category("miscellaneous")


class TestOptimisticLocking:
    def test_version_conflict_raises(self, service: CategoryServiceLocal) -> None:
        service.add_category("Groceries")

        with pytest.raises(VersionConflictError):
            service._put_all(["X"], expected_version=0)  # stale version


class TestBackupWriter:
    def test_backup_called_on_add(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Stub JSON fallback so we aren't colliding with the bundled real category list
        monkeypatch.setattr(CategoryServiceLocal, "_load_from_json", lambda self: [])
        calls: list[list[str]] = []
        svc = CategoryServiceLocal(db_path=tmp_path / "test.db", user_id="test")
        svc._write_backup = lambda categories, _calls=calls: _calls.append(list(categories))

        svc.add_category("TestCategory")

        assert calls == [["TestCategory"]]
