"""Parity tests for MerchantAliasServiceLocal — SQLite implementation of alias CRUD.

Mirrors test_merchant_alias_service.py behavior against an in-memory SQLite backend.
"""

from pathlib import Path

import pytest

from src.finance.exceptions import VersionConflictError
from src.finance.merchant_alias_service_local import MerchantAliasServiceLocal


@pytest.fixture
def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MerchantAliasServiceLocal:
    monkeypatch.setattr(MerchantAliasServiceLocal, "_write_backup", lambda self, *a, **kw: None)
    return MerchantAliasServiceLocal(db_path=tmp_path / "test.db", user_id="test")


class TestGetAliases:
    def test_returns_none_when_not_seeded(self, service: MerchantAliasServiceLocal) -> None:
        assert service.get_aliases() is None

    def test_get_aliases_map_empty_when_unseeded(self, service: MerchantAliasServiceLocal) -> None:
        assert service.get_aliases_map() == {}


class TestPutAlias:
    def test_first_put_creates_with_version_one(self, service: MerchantAliasServiceLocal) -> None:
        v = service.put_alias("COSTCO #1234", "Costco")

        assert v == 1
        # Keys lowercased
        assert service.get_aliases_map() == {"costco #1234": "Costco"}

    def test_version_increments_on_repeat_put(self, service: MerchantAliasServiceLocal) -> None:
        v1 = service.put_alias("COSTCO #1234", "Costco")
        v2 = service.put_alias("SHELL #567", "Shell")

        assert v1 == 1
        assert v2 == 2

    def test_update_existing_alias(self, service: MerchantAliasServiceLocal) -> None:
        service.put_alias("COSTCO #1234", "Costco")
        service.put_alias("COSTCO #1234", "Costco Wholesale")

        assert service.get_aliases_map() == {"costco #1234": "Costco Wholesale"}


class TestDeleteAlias:
    def test_removes_entry(self, service: MerchantAliasServiceLocal) -> None:
        service.put_alias("COSTCO #1234", "Costco")
        service.put_alias("SHELL #567", "Shell")

        service.delete_alias("COSTCO #1234")

        assert service.get_aliases_map() == {"shell #567": "Shell"}

    def test_case_insensitive_via_lowercased_key(self, service: MerchantAliasServiceLocal) -> None:
        service.put_alias("COSTCO #1234", "Costco")

        service.delete_alias("costco #1234")  # matches stored lowercased key

        assert service.get_aliases_map() == {}

    def test_raises_keyerror_when_absent(self, service: MerchantAliasServiceLocal) -> None:
        service.put_alias("COSTCO #1234", "Costco")

        with pytest.raises(KeyError):
            service.delete_alias("NOT_THERE")

    def test_raises_keyerror_when_no_aliases_exist(self, service: MerchantAliasServiceLocal) -> None:
        with pytest.raises(KeyError):
            service.delete_alias("Anything")


class TestOptimisticLocking:
    def test_version_conflict_raises(self, service: MerchantAliasServiceLocal) -> None:
        service.put_alias("COSTCO #1234", "Costco")

        with pytest.raises(VersionConflictError):
            service._put_all({"x": "y"}, expected_version=0)  # stale


class TestBackupWriter:
    def test_backup_called_on_put(self, tmp_path: Path) -> None:
        calls: list[dict[str, str]] = []
        svc = MerchantAliasServiceLocal(db_path=tmp_path / "test.db", user_id="test")
        svc._write_backup = lambda data, _calls=calls: _calls.append(dict(data))

        svc.put_alias("COSTCO", "Costco")

        assert calls == [{"costco": "Costco"}]
