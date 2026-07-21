"""Router↔service↔storage integration tests — no mocked ``run_sync``.

Every ``test_api_*.py`` module patches ``run_sync`` and feeds the router
hand-crafted DynamoDB items from ``tests/factories.py``. That proves the
router's response *shape*, but never that those factory items match what the
service actually persists — the coupling is maintained only by the factory
docstrings ("Matches the shape written by BudgetService.put_targets()"). If a
service's write shape drifted, the mocked tests would stay green while
production 500s on the read.

These tests close that seam. They override the FastAPI service dependency with
a *real* service — DynamoDB-side against a ``moto`` fake, SQLite-side against a
tmp DB — and drive a write→read round-trip through the HTTP layer. Nothing is
hand-crafted: the bytes the service writes are the bytes the router reads back,
across the same ``run_sync`` executor hop production uses. Parametrized over
both backends so the two implementations stay in lockstep at the API boundary
(complements ``test_dual_backend_contract.py``, which exercises the
service↔storage seam directly, one layer below the router).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from src.api.dependencies import get_budget_service, get_override_service
from src.api.main import app
from tests.asserts import assert_ok, assert_problem

if TYPE_CHECKING:
    from pathlib import Path


def _override_service(backend: str, dyn_resource: Any, tmp_path: Path) -> Any:
    if backend == "dynamodb":
        from src.finance.override_service import OverrideService

        return OverrideService(dyn_resource=dyn_resource)
    from src.finance.override_service_local import OverrideServiceLocal

    return OverrideServiceLocal(db_path=tmp_path / "overrides.db")


def _budget_service(backend: str, dyn_resource: Any, tmp_path: Path) -> Any:
    if backend == "dynamodb":
        from src.finance.budget_service import BudgetService

        return BudgetService(dyn_resource=dyn_resource)
    from src.finance.budget_service_local import BudgetServiceLocal

    return BudgetServiceLocal(db_path=tmp_path / "budget.db")


@pytest.fixture(params=["dynamodb", "sqlite"])
def override_client(request: pytest.FixtureRequest, api_client: Any, dyn_resource: Any, tmp_path: Path) -> Any:
    """``api_client`` with ``get_override_service`` wired to a real backend.

    ``api_client`` (root conftest) clears ``dependency_overrides`` on teardown.
    """
    svc = _override_service(request.param, dyn_resource, tmp_path)
    app.dependency_overrides[get_override_service] = lambda: svc
    return api_client


@pytest.fixture(params=["dynamodb", "sqlite"])
def budget_client(request: pytest.FixtureRequest, api_client: Any, dyn_resource: Any, tmp_path: Path) -> Any:
    """``api_client`` with ``get_budget_service`` wired to a real backend."""
    svc = _budget_service(request.param, dyn_resource, tmp_path)
    app.dependency_overrides[get_budget_service] = lambda: svc
    return api_client


class TestOverrideRoundTrip:
    """PUT → GET through the real OverrideService (shared config-service base)."""

    def test_put_then_independent_get_returns_written_value(self, override_client: Any) -> None:
        put = assert_ok(override_client.put("/api/v1/overrides/STARBUCKS", json={"category": "coffee"}))
        assert any(o["company"] == "STARBUCKS" and o["category"] == "coffee" for o in put["overrides"])

        # A fresh GET reads the persisted row back — not the PUT's echo.
        listing = assert_ok(override_client.get("/api/v1/overrides"))
        assert listing["count"] == 1
        assert listing["overrides"] == [{"company": "STARBUCKS", "category": "coffee"}]

    def test_version_increments_across_writes(self, override_client: Any) -> None:
        v1 = assert_ok(override_client.put("/api/v1/overrides/STARBUCKS", json={"category": "coffee"}))["version"]
        v2 = assert_ok(override_client.put("/api/v1/overrides/TIMHORTONS", json={"category": "coffee"}))["version"]
        assert v2 > v1

    def test_overwrite_same_company_updates_category(self, override_client: Any) -> None:
        assert_ok(override_client.put("/api/v1/overrides/STARBUCKS", json={"category": "coffee"}))
        assert_ok(override_client.put("/api/v1/overrides/STARBUCKS", json={"category": "dining"}))
        listing = assert_ok(override_client.get("/api/v1/overrides"))
        assert listing["count"] == 1
        assert listing["overrides"][0]["category"] == "dining"

    def test_delete_removes_the_row(self, override_client: Any) -> None:
        assert_ok(override_client.put("/api/v1/overrides/STARBUCKS", json={"category": "coffee"}))
        assert_ok(override_client.delete("/api/v1/overrides/STARBUCKS"))
        assert assert_ok(override_client.get("/api/v1/overrides"))["count"] == 0

    def test_delete_missing_is_404(self, override_client: Any) -> None:
        assert_problem(override_client.delete("/api/v1/overrides/NOPE"), 404)


_BUDGET_BODY = {
    "spending_ceiling": 60000,
    "categories": {
        "groceries": {"target": 7200, "input_mode": "monthly", "category_type": "variable"},
        "rent": {"target": 24000, "input_mode": "monthly", "category_type": "fixed"},
    },
    "groups": [{"name": "Essentials", "categories": ["groceries", "rent"]}],
    "targets_version": None,
    "groups_version": None,
}


class TestBudgetConfigRoundTrip:
    """PUT → GET through the real BudgetService (separate impls; targets + groups)."""

    def test_put_then_independent_get_matches(self, budget_client: Any) -> None:
        put = assert_ok(budget_client.put("/api/v1/budget/config?year=2026", json=_BUDGET_BODY))
        get = assert_ok(budget_client.get("/api/v1/budget/config?year=2026"))

        # The read reflects exactly what the service persisted — no factory stand-in.
        assert get["spending_ceiling"] == 60000
        assert set(get["categories"]) == {"groceries", "rent"}
        assert get["categories"]["groceries"]["target"] == 7200
        assert get["categories"]["rent"]["category_type"] == "fixed"
        assert [g["name"] for g in get["groups"]] == ["Essentials"]
        assert get["groups"][0]["categories"] == ["groceries", "rent"]
        # First write establishes version 1 on both rows; GET agrees with PUT.
        assert put["targets_version"] == get["targets_version"] == 1
        assert put["groups_version"] == get["groups_version"] == 1

    def test_second_write_bumps_versions(self, budget_client: Any) -> None:
        assert_ok(budget_client.put("/api/v1/budget/config?year=2026", json=_BUDGET_BODY))
        body_v2 = {**_BUDGET_BODY, "spending_ceiling": 72000, "targets_version": 1, "groups_version": 1}
        put2 = assert_ok(budget_client.put("/api/v1/budget/config?year=2026", json=body_v2))
        assert put2["targets_version"] == 2
        assert assert_ok(budget_client.get("/api/v1/budget/config?year=2026"))["spending_ceiling"] == 72000

    def test_stale_version_conflicts(self, budget_client: Any) -> None:
        assert_ok(budget_client.put("/api/v1/budget/config?year=2026", json=_BUDGET_BODY))  # → version 1
        # Re-submitting with the now-stale None (create) version must 409, not clobber.
        assert_problem(budget_client.put("/api/v1/budget/config?year=2026", json=_BUDGET_BODY), 409)

    def test_get_before_any_write_is_404(self, budget_client: Any) -> None:
        assert_problem(budget_client.get("/api/v1/budget/config?year=2099"), 404)
