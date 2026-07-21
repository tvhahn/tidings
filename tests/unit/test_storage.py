"""Tests for the storage factory — the config -> concrete-backend routing.

This is the decision that makes demo mode safe and keeps DynamoDB out of
local/demo runs; asserting each branch guards against a subtle deploy-time
regression (e.g. someone flipping a default).
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.finance import storage
from src.finance.transaction_db import TransactionsDB
from src.finance.transaction_db_local import TransactionsDBLocal


@pytest.fixture(autouse=True)
def _isolate_db_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect the SQLite paths so local-backend construction (which runs
    ``ensure_schema`` in ``__init__``) never touches the developer's real
    ``data/finance.db`` / ``data/demo.db``."""
    monkeypatch.setattr(storage, "_FINANCE_DB_PATH", tmp_path / "finance.db")
    monkeypatch.setattr(storage, "_DEMO_DB_PATH", tmp_path / "demo.db")


@pytest.fixture
def patched_get_config(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Return a helper that stubs ``src.finance.storage.get_config`` per test."""

    def _apply(**overrides: Any) -> None:
        base = {"storage": "sqlite", "demo_mode": False, "user_id": "default"}
        base.update(overrides)
        monkeypatch.setattr(storage, "get_config", lambda: dict(base))

    return _apply


@pytest.fixture
def stub_dynamo_resource(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace ``_dynamo_resource`` with a MagicMock so boto3/AWS is never touched."""
    fake = MagicMock(name="dyn_resource")
    monkeypatch.setattr(storage, "_dynamo_resource", lambda: fake)
    return fake


class TestCreateTransactionsDB:
    def test_sqlite_config_returns_local(self, patched_get_config: Callable[..., None]) -> None:
        patched_get_config(storage="sqlite", demo_mode=False)
        db = storage.create_transactions_db()
        assert isinstance(db, TransactionsDBLocal)

    def test_dynamodb_config_returns_dynamo(
        self, patched_get_config: Callable[..., None], stub_dynamo_resource: MagicMock
    ) -> None:
        patched_get_config(storage="dynamodb", demo_mode=False)
        db = storage.create_transactions_db()
        assert isinstance(db, TransactionsDB)

    def test_demo_mode_overrides_dynamodb(self, patched_get_config: Callable[..., None]) -> None:
        """demo_mode=True must force SQLite even if storage='dynamodb' is set."""
        patched_get_config(storage="dynamodb", demo_mode=True)
        db = storage.create_transactions_db()
        assert isinstance(db, TransactionsDBLocal)

    def test_unknown_storage_value_falls_back_to_local(self, patched_get_config: Callable[..., None]) -> None:
        """Defensive: any non-'dynamodb' value lands on the SQLite branch."""
        patched_get_config(storage="mystery", demo_mode=False)
        db = storage.create_transactions_db()
        assert isinstance(db, TransactionsDBLocal)


class TestGetUserId:
    """The user-id resolution that stamps every DynamoDB partition key.

    The env-var-wins rule is what lets Lambda (which never ships the personal
    ``data/config.json``) resolve the right user; breaking it would silently
    write every user's data under the ``default`` partition.
    """

    def test_env_var_wins_over_config(
        self, patched_get_config: Callable[..., None], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patched_get_config(user_id="from_config")
        monkeypatch.setenv("USER_ID", "from_env")
        assert storage._get_user_id() == "from_env"

    def test_falls_back_to_config_when_env_absent(
        self, patched_get_config: Callable[..., None], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patched_get_config(user_id="from_config")
        monkeypatch.delenv("USER_ID", raising=False)
        assert storage._get_user_id() == "from_config"

    def test_defaults_when_neither_env_nor_config_set(
        self, patched_get_config: Callable[..., None], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # patched_get_config drops the key so the config lookup misses.
        monkeypatch.setattr(storage, "get_config", lambda: {"storage": "sqlite"})
        monkeypatch.delenv("USER_ID", raising=False)
        assert storage._get_user_id() == "default"

    def test_empty_env_var_is_ignored_in_favor_of_config(
        self, patched_get_config: Callable[..., None], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty USER_ID is falsy — config must still win rather than yielding ''."""
        patched_get_config(user_id="from_config")
        monkeypatch.setenv("USER_ID", "")
        assert storage._get_user_id() == "from_config"


class TestDynamoResource:
    """The deferred boto3 handle used by every DynamoDB factory."""

    def test_builds_resource_in_configured_region(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import boto3

        sentinel = object()
        calls: list[tuple[str, str]] = []

        def _fake_resource(service: str, region_name: str) -> object:
            calls.append((service, region_name))
            return sentinel

        monkeypatch.setattr(boto3, "resource", _fake_resource)
        monkeypatch.setattr(storage, "get_aws_region", lambda: "eu-west-2")

        result = storage._dynamo_resource()

        assert result is sentinel
        assert calls == [("dynamodb", "eu-west-2")]


class TestCreateSpendingSummary:
    """Summary factory routing — mirrors the transactions-db decision so a
    flipped default can't silently point demo runs at DynamoDB."""

    def test_sqlite_config_returns_local(self, patched_get_config: Callable[..., None]) -> None:
        from src.finance.spending_summary_local import SpendingSummaryLocal

        patched_get_config(storage="sqlite", demo_mode=False)
        assert isinstance(storage.create_spending_summary(), SpendingSummaryLocal)

    def test_dynamodb_config_returns_dynamo(
        self, patched_get_config: Callable[..., None], stub_dynamo_resource: MagicMock
    ) -> None:
        from src.finance.spending_summary import SpendingSummary

        patched_get_config(storage="dynamodb", demo_mode=False)
        assert isinstance(storage.create_spending_summary(), SpendingSummary)

    def test_demo_mode_overrides_dynamodb(self, patched_get_config: Callable[..., None]) -> None:
        from src.finance.spending_summary_local import SpendingSummaryLocal

        patched_get_config(storage="dynamodb", demo_mode=True)
        assert isinstance(storage.create_spending_summary(), SpendingSummaryLocal)

    def test_unknown_storage_value_falls_back_to_local(self, patched_get_config: Callable[..., None]) -> None:
        from src.finance.spending_summary_local import SpendingSummaryLocal

        patched_get_config(storage="mystery", demo_mode=False)
        assert isinstance(storage.create_spending_summary(), SpendingSummaryLocal)


def _service_cases() -> list[tuple[str, str, str, str]]:
    """(factory_name, dynamo_module, dynamo_cls, local_cls) for each service
    routed through the generic ``_create_service`` helper."""
    return [
        ("create_budget_service", "budget_service", "BudgetService", "BudgetServiceLocal"),
        ("create_override_service", "override_service", "OverrideService", "OverrideServiceLocal"),
        ("create_category_service", "category_service", "CategoryService", "CategoryServiceLocal"),
        (
            "create_merchant_alias_service",
            "merchant_alias_service",
            "MerchantAliasService",
            "MerchantAliasServiceLocal",
        ),
        ("create_parse_failure_store", "parse_failure_store", "ParseFailureStore", "ParseFailureStoreLocal"),
        (
            "create_category_icon_service",
            "category_icon_service",
            "CategoryIconService",
            "CategoryIconServiceLocal",
        ),
    ]


def _import_cls(module: str, cls: str) -> type[Any]:
    import importlib

    return getattr(importlib.import_module(f"src.finance.{module}"), cls)


@pytest.mark.parametrize(
    ("factory_name", "dynamo_module", "dynamo_cls", "local_cls"),
    _service_cases(),
    ids=[c[0] for c in _service_cases()],
)
class TestGenericServiceRouting:
    """Each dual-backend factory built on ``_create_service`` must honor the
    same three-way decision: demo and non-dynamodb configs stay on SQLite,
    only an explicit ``storage='dynamodb'`` reaches the AWS class.

    Parametrizing the six services proves the shared helper wires every one
    correctly — a per-service ``_dynamo`` closure that imported the wrong
    class would surface here.
    """

    def test_sqlite_config_returns_local(
        self,
        patched_get_config: Callable[..., None],
        factory_name: str,
        dynamo_module: str,
        dynamo_cls: str,
        local_cls: str,
    ) -> None:
        patched_get_config(storage="sqlite", demo_mode=False)
        instance = getattr(storage, factory_name)()
        assert isinstance(instance, _import_cls(f"{dynamo_module}_local", local_cls))

    def test_dynamodb_config_returns_dynamo(
        self,
        patched_get_config: Callable[..., None],
        stub_dynamo_resource: MagicMock,
        factory_name: str,
        dynamo_module: str,
        dynamo_cls: str,
        local_cls: str,
    ) -> None:
        patched_get_config(storage="dynamodb", demo_mode=False)
        instance = getattr(storage, factory_name)()
        assert isinstance(instance, _import_cls(dynamo_module, dynamo_cls))

    def test_demo_mode_overrides_dynamodb(
        self,
        patched_get_config: Callable[..., None],
        factory_name: str,
        dynamo_module: str,
        dynamo_cls: str,
        local_cls: str,
    ) -> None:
        patched_get_config(storage="dynamodb", demo_mode=True)
        instance = getattr(storage, factory_name)()
        assert isinstance(instance, _import_cls(f"{dynamo_module}_local", local_cls))


class TestDynamoServiceUsesResolvedUserId:
    """The DynamoDB closures stamp the resolved user id onto the service so
    partition keys are namespaced per user (not left at ``default``)."""

    def test_budget_service_receives_user_id(
        self,
        patched_get_config: Callable[..., None],
        stub_dynamo_resource: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        patched_get_config(storage="dynamodb", demo_mode=False, user_id="alice")
        monkeypatch.delenv("USER_ID", raising=False)
        svc = storage.create_budget_service()
        assert svc.USER_PK == "USER#alice"


class TestCreateTransactionContextEnricher:
    """The enricher must be wired with both services from the configured
    backend — a missing budget dependency would silently drop budget context."""

    def test_wires_both_services_from_configured_backend(self, patched_get_config: Callable[..., None]) -> None:
        from src.finance.budget_service_local import BudgetServiceLocal
        from src.finance.transaction_context import TransactionContextEnricher

        patched_get_config(storage="sqlite", demo_mode=False)
        enricher = storage.create_transaction_context_enricher()

        assert isinstance(enricher, TransactionContextEnricher)
        assert isinstance(enricher.transactions_db, TransactionsDBLocal)
        assert isinstance(enricher.budget_service, BudgetServiceLocal)
