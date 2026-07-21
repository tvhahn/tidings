"""Parity tests for BudgetServiceLocal — SQLite implementation of budget config CRUD.

Mirrors test_budget_service.py behavior against an in-memory SQLite backend.
Covers the storage-specific paths: insert vs update, version increment, and
version-conflict raising via IntegrityError and UPDATE rowcount=0.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from src.finance.budget_service_local import BudgetServiceLocal
from src.finance.exceptions import VersionConflictError


@pytest.fixture
def service(tmp_path: Path) -> BudgetServiceLocal:
    return BudgetServiceLocal(db_path=tmp_path / "test.db", user_id="test")


TARGETS_PAYLOAD = {
    "spending_ceiling": Decimal(120000),
    "categories": {
        "groceries": {
            "target": Decimal(18000),
            "input_mode": "monthly",
            "category_type": "variable",
            "monthly_amount": Decimal(1500),
        }
    },
}


class TestGetTargets:
    def test_returns_none_when_not_seeded(self, service: BudgetServiceLocal) -> None:
        assert service.get_targets(2026) is None

    def test_returns_data_and_version_after_put(self, service: BudgetServiceLocal) -> None:
        service._store_targets(2026, TARGETS_PAYLOAD, expected_version=None)

        item = service.get_targets(2026)
        assert item is not None
        assert item["Version"] == 1
        assert item["PK"] == "USER#test"
        assert item["SK"] == "BUDGET#targets#2026"


class TestStoreTargets:
    def test_insert_with_no_prior_version(self, service: BudgetServiceLocal) -> None:
        v = service._store_targets(2026, TARGETS_PAYLOAD, expected_version=None)
        assert v == 1

    def test_insert_conflict_when_already_exists(self, service: BudgetServiceLocal) -> None:
        service._store_targets(2026, TARGETS_PAYLOAD, expected_version=None)

        with pytest.raises(VersionConflictError):
            service._store_targets(2026, TARGETS_PAYLOAD, expected_version=None)

    def test_update_with_correct_version_succeeds(self, service: BudgetServiceLocal) -> None:
        service._store_targets(2026, TARGETS_PAYLOAD, expected_version=None)

        v2 = service._store_targets(2026, TARGETS_PAYLOAD, expected_version=1)
        assert v2 == 2

    def test_update_with_stale_version_raises(self, service: BudgetServiceLocal) -> None:
        service._store_targets(2026, TARGETS_PAYLOAD, expected_version=None)

        with pytest.raises(VersionConflictError):
            service._store_targets(2026, TARGETS_PAYLOAD, expected_version=0)

    def test_year_isolation(self, service: BudgetServiceLocal) -> None:
        service._store_targets(2026, TARGETS_PAYLOAD, expected_version=None)
        service._store_targets(2025, TARGETS_PAYLOAD, expected_version=None)

        assert service.get_targets(2026) is not None
        assert service.get_targets(2025) is not None


class TestGroups:
    GROUPS_PAYLOAD = {"groups": [{"name": "Housing", "categories": ["rent", "utilities"]}]}

    def test_store_and_get_groups(self, service: BudgetServiceLocal) -> None:
        v = service._store_groups(2026, self.GROUPS_PAYLOAD, expected_version=None)

        assert v == 1
        item = service.get_groups(2026)
        assert item is not None
        assert item["Data"]["groups"][0]["name"] == "Housing"

    def test_groups_version_conflict(self, service: BudgetServiceLocal) -> None:
        service._store_groups(2026, self.GROUPS_PAYLOAD, expected_version=None)

        with pytest.raises(VersionConflictError):
            service._store_groups(2026, self.GROUPS_PAYLOAD, expected_version=None)


class TestDecimalRoundTrip:
    def test_decimal_values_serialize_through_json(self, service: BudgetServiceLocal) -> None:
        # Values are stored as JSON via _DecimalEncoder. Reading them back returns
        # plain numbers (int/float) — the base class is responsible for any Decimal
        # rehydration in public getters; the storage layer must simply round-trip OK.
        service._store_targets(2026, TARGETS_PAYLOAD, expected_version=None)
        item = service.get_targets(2026)

        assert item is not None
        assert item["Data"]["spending_ceiling"] == 120000
        assert item["Data"]["categories"]["groceries"]["target"] == 18000
