"""Dual-backend contract for BudgetService (DynamoDB via moto) and BudgetServiceLocal (SQLite).

Covers ``list_budget_years`` — the year enumeration the backup export relies on
so a budget stored for any year (not just a window around today) is exported.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import boto3
import pytest
from moto import mock_aws

from src.finance.budget_service import BudgetService
from src.finance.budget_service_local import BudgetServiceLocal
from src.finance.local_db import CONFIG_INSERT_SQL, get_connection

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def dyn_resource() -> Iterator[Any]:
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
    with mock_aws():
        yield boto3.resource("dynamodb", region_name="us-west-2")


_TARGETS = {"spending_ceiling": 1000, "categories": {"groceries": {"target": 1200}}}
_GROUPS = {"groups": [{"name": "Food", "categories": ["groceries"]}]}


class TestListBudgetYearsContract:
    @pytest.fixture(params=["dynamodb", "sqlite"])
    def backend(self, request: pytest.FixtureRequest, dyn_resource: Any, tmp_path: Path) -> dict[str, Any]:
        if request.param == "dynamodb":
            svc = BudgetService(dyn_resource=dyn_resource, user_id="default")
            svc.create_table()
            other = BudgetService(dyn_resource=dyn_resource, user_id="someone-else")
            return {"svc": svc, "other": other, "db_path": None}
        db_path = tmp_path / "budget.db"
        return {
            "svc": BudgetServiceLocal(db_path=db_path, user_id="default"),
            "other": BudgetServiceLocal(db_path=db_path, user_id="someone-else"),
            "db_path": db_path,
        }

    def test_empty_store_has_no_years(self, backend: dict[str, Any]) -> None:
        assert backend["svc"].list_budget_years() == []

    def test_returns_sorted_distinct_years_with_targets_or_groups(self, backend: dict[str, Any]) -> None:
        svc = backend["svc"]
        svc._store_targets(2031, _TARGETS, expected_version=None)
        svc._store_groups(2031, _GROUPS, expected_version=None)  # same year twice → one entry
        svc._store_groups(2020, _GROUPS, expected_version=None)  # groups-only year
        svc._store_targets(2026, _TARGETS, expected_version=None)  # targets-only year

        assert svc.list_budget_years() == [2020, 2026, 2031]

    def test_scoped_to_the_user(self, backend: dict[str, Any]) -> None:
        backend["other"]._store_targets(2029, _TARGETS, expected_version=None)
        backend["svc"]._store_targets(2026, _TARGETS, expected_version=None)

        assert backend["svc"].list_budget_years() == [2026]
        assert backend["other"].list_budget_years() == [2029]

    def test_ignores_non_budget_config_items(self, backend: dict[str, Any]) -> None:
        # Config items for every service share one table/partition per user.
        if backend["db_path"] is not None:
            conn = get_connection(backend["db_path"])
            try:
                conn.execute(CONFIG_INSERT_SQL, ("USER#default", "CONFIG#category_overrides", "{}", 1, "2026-01-01"))
                conn.commit()
            finally:
                conn.close()
        else:
            backend["svc"].table.put_item(Item={"PK": "USER#default", "SK": "CONFIG#category_overrides"})
        backend["svc"]._store_targets(2027, _TARGETS, expected_version=None)

        assert backend["svc"].list_budget_years() == [2027]
