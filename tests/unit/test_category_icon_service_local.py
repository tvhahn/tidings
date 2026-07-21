"""Tests for CategoryIconServiceLocal (SQLite) — CRUD + allowlist + version lock."""

from pathlib import Path

import pytest

from src.finance.category_icon_service_local import CategoryIconServiceLocal
from src.finance.exceptions import VersionConflictError


@pytest.fixture
def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CategoryIconServiceLocal:
    monkeypatch.setattr(CategoryIconServiceLocal, "_write_backup", lambda self, *a, **kw: None)
    return CategoryIconServiceLocal(db_path=tmp_path / "test.db", user_id="test")


class TestGetIcons:
    def test_returns_none_when_not_seeded(self, service: CategoryIconServiceLocal) -> None:
        assert service.get_icons() is None

    def test_get_icons_map_empty_when_unseeded(self, service: CategoryIconServiceLocal) -> None:
        assert service.get_icons_map() == {}


class TestSetIcon:
    def test_first_set_creates_with_version_one(self, service: CategoryIconServiceLocal) -> None:
        v = service.set_icon("Dining", "Utensils")

        assert v == 1
        assert service.get_icons_map() == {"dining": "Utensils"}

    def test_lowercases_category_key(self, service: CategoryIconServiceLocal) -> None:
        service.set_icon("GROCERIES", "ShoppingCart")

        assert service.get_icons_map() == {"groceries": "ShoppingCart"}

    def test_version_increments(self, service: CategoryIconServiceLocal) -> None:
        v1 = service.set_icon("Dining", "Utensils")
        v2 = service.set_icon("Gasoline", "Fuel")

        assert v1 == 1
        assert v2 == 2

    def test_update_existing(self, service: CategoryIconServiceLocal) -> None:
        service.set_icon("Dining", "Utensils")
        service.set_icon("Dining", "Pizza")

        assert service.get_icons_map() == {"dining": "Pizza"}

    def test_rejects_unknown_icon(self, service: CategoryIconServiceLocal) -> None:
        with pytest.raises(ValueError, match="not in the allowed icon catalog"):
            service.set_icon("Dining", "NotARealIcon")


class TestClearIcon:
    def test_removes_entry(self, service: CategoryIconServiceLocal) -> None:
        service.set_icon("Dining", "Utensils")
        service.set_icon("Gasoline", "Fuel")

        service.clear_icon("Dining")

        assert service.get_icons_map() == {"gasoline": "Fuel"}

    def test_case_insensitive(self, service: CategoryIconServiceLocal) -> None:
        service.set_icon("DINING", "Utensils")

        service.clear_icon("dining")

        assert service.get_icons_map() == {}

    def test_noop_when_absent(self, service: CategoryIconServiceLocal) -> None:
        service.set_icon("Dining", "Utensils")

        # Does not raise; returns current version
        v = service.clear_icon("NotThere")

        assert v == 1
        assert service.get_icons_map() == {"dining": "Utensils"}

    def test_noop_when_nothing_stored(self, service: CategoryIconServiceLocal) -> None:
        v = service.clear_icon("Anything")

        assert v == 0


class TestRenameCategory:
    def test_rekeys_override(self, service: CategoryIconServiceLocal) -> None:
        service.set_icon("Dining", "Utensils")

        service.rename_category("Dining", "Food & Dining")

        assert service.get_icons_map() == {"food & dining": "Utensils"}

    def test_noop_when_no_override(self, service: CategoryIconServiceLocal) -> None:
        service.set_icon("Dining", "Utensils")

        v = service.rename_category("NotThere", "Other")

        assert v == 1
        assert service.get_icons_map() == {"dining": "Utensils"}

    def test_noop_when_nothing_stored(self, service: CategoryIconServiceLocal) -> None:
        v = service.rename_category("A", "B")

        assert v == 0


class TestDeleteCategory:
    def test_removes_entry(self, service: CategoryIconServiceLocal) -> None:
        service.set_icon("Dining", "Utensils")
        service.set_icon("Gasoline", "Fuel")

        service.delete_category("Dining")

        assert service.get_icons_map() == {"gasoline": "Fuel"}


class TestOptimisticLocking:
    def test_version_conflict_raises(self, service: CategoryIconServiceLocal) -> None:
        service.set_icon("Dining", "Utensils")

        with pytest.raises(VersionConflictError):
            service._put_all({"x": "Utensils"}, expected_version=0)


class TestBackupWriter:
    def test_backup_called_on_put(self, tmp_path: Path) -> None:
        calls: list[dict[str, str]] = []
        svc = CategoryIconServiceLocal(db_path=tmp_path / "test.db", user_id="test")
        svc._write_backup = lambda data, _calls=calls: _calls.append(dict(data))

        svc.set_icon("Dining", "Utensils")

        assert calls == [{"dining": "Utensils"}]
