"""Parity tests for OverrideServiceLocal — SQLite implementation of override CRUD.

These tests mirror the behavior verified in test_override_service.py (DynamoDB)
against an in-memory SQLite backend. They guard against drift between the two
implementations of the dual-backend config service.
"""

from pathlib import Path

import pytest

from src.finance.exceptions import VersionConflictError
from src.finance.override_service_local import OverrideServiceLocal


@pytest.fixture
def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> OverrideServiceLocal:
    """Fresh OverrideServiceLocal with tmp DB and stubbed backup writer."""
    # Prevent backup writes from touching the real filesystem
    monkeypatch.setattr(OverrideServiceLocal, "_write_backup", lambda self, *a, **kw: None)
    return OverrideServiceLocal(db_path=tmp_path / "test.db", user_id="test")


class TestGetOverrides:
    def test_returns_none_when_not_seeded(self, service: OverrideServiceLocal) -> None:
        assert service.get_overrides() is None

    def test_returns_data_version_and_updated_at_after_put(self, service: OverrideServiceLocal) -> None:
        service.put_override("NorthMobile", "Communication/Cell")

        item = service.get_overrides()
        assert item is not None
        assert item["Data"] == {"NorthMobile": "Communication/Cell"}
        assert item["Version"] == 1
        assert item["UpdatedAt"]  # ISO date string
        assert item["Dismissed"] == {}


class TestPutOverride:
    def test_version_increments_on_repeat_put(self, service: OverrideServiceLocal) -> None:
        v1 = service.put_override("NorthMobile", "Communication/Cell")
        v2 = service.put_override("Costco", "Groceries")

        assert v1 == 1
        assert v2 == 2

    def test_overrides_map_accumulates(self, service: OverrideServiceLocal) -> None:
        service.put_override("NorthMobile", "Communication/Cell")
        service.put_override("Costco", "Groceries")

        item = service.get_overrides()
        assert item is not None
        assert item["Data"] == {"NorthMobile": "Communication/Cell", "Costco": "Groceries"}

    def test_update_existing_company(self, service: OverrideServiceLocal) -> None:
        service.put_override("NorthMobile", "Communication/Cell")
        service.put_override("NorthMobile", "Utilities")

        item = service.get_overrides()
        assert item is not None
        assert item["Data"] == {"NorthMobile": "Utilities"}


class TestLookupCategory:
    def test_case_insensitive_match(self, service: OverrideServiceLocal) -> None:
        service.put_override("North Mobile", "Communication/Cell")

        assert service.lookup_category("north mobile") == "Communication/Cell"
        assert service.lookup_category("NORTH MOBILE") == "Communication/Cell"
        assert service.lookup_category("North Mobile") == "Communication/Cell"

    def test_returns_none_when_company_absent(self, service: OverrideServiceLocal) -> None:
        service.put_override("NorthMobile", "Communication/Cell")
        assert service.lookup_category("SomeOther") is None

    def test_returns_none_when_no_overrides_exist(self, service: OverrideServiceLocal) -> None:
        assert service.lookup_category("Anything") is None


class TestDeleteOverride:
    def test_removes_entry(self, service: OverrideServiceLocal) -> None:
        service.put_override("NorthMobile", "Communication/Cell")
        service.put_override("Costco", "Groceries")
        service.delete_override("NorthMobile")

        item = service.get_overrides()
        assert item is not None
        assert item["Data"] == {"Costco": "Groceries"}

    def test_case_insensitive_delete(self, service: OverrideServiceLocal) -> None:
        service.put_override("NorthMobile", "Communication/Cell")
        service.delete_override("NORTHMOBILE")

        item = service.get_overrides()
        assert item is not None
        assert item["Data"] == {}

    def test_raises_keyerror_when_absent(self, service: OverrideServiceLocal) -> None:
        service.put_override("NorthMobile", "Communication/Cell")
        with pytest.raises(KeyError):
            service.delete_override("NotThere")

    def test_raises_keyerror_when_no_overrides_exist(self, service: OverrideServiceLocal) -> None:
        with pytest.raises(KeyError):
            service.delete_override("Anything")


class TestOptimisticLocking:
    def test_version_conflict_when_expected_version_stale(self, service: OverrideServiceLocal) -> None:
        service.put_override("NorthMobile", "Communication/Cell")
        # Raw _put_all_with_dismissed with a stale expected_version should raise
        with pytest.raises(VersionConflictError):
            service._put_all_with_dismissed({"X": "Y"}, {}, expected_version=0)


class TestDismissals:
    def test_dismiss_adds_entry_to_dismissed_map(self, service: OverrideServiceLocal) -> None:
        service.dismiss_suggestion("NorthMobile", "Communication/Cell")

        item = service.get_overrides()
        assert item is not None
        assert "northmobile|communication/cell" in item["Dismissed"]

    def test_undismiss_removes_entry(self, service: OverrideServiceLocal) -> None:
        service.dismiss_suggestion("NorthMobile", "Communication/Cell")
        service.undismiss_suggestion("northmobile|communication/cell")

        item = service.get_overrides()
        assert item is not None
        assert item["Dismissed"] == {}

    def test_undismiss_nonexistent_is_noop(self, service: OverrideServiceLocal) -> None:
        # Should not raise
        service.undismiss_suggestion("nothing|here")


class TestBackupWriter:
    def test_backup_called_on_put(self, tmp_path: Path) -> None:
        calls: list[tuple[dict[str, str], dict[str, str]]] = []

        def fake_backup(
            self: OverrideServiceLocal,
            data: dict[str, str],
            dismissed: dict[str, str] | None = None,
        ) -> None:
            calls.append((dict(data), dict(dismissed) if dismissed else {}))

        # Use a fresh service without the fixture's stub
        svc = OverrideServiceLocal(db_path=tmp_path / "test.db", user_id="test")
        svc._write_backup = fake_backup.__get__(svc, OverrideServiceLocal)

        svc.put_override("NorthMobile", "Communication/Cell")

        assert len(calls) == 1
        assert calls[0][0] == {"NorthMobile": "Communication/Cell"}
