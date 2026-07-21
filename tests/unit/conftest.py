"""Unit-test-scope fixtures.

These fixtures only make sense for the API + service unit tests under
``tests/unit/``. They were previously declared autouse in the root
``tests/conftest.py``, where they also ran on every property test in
``tests/property/`` and every integration test — taxing 200+ hypothesis
example runs with monkeypatches and per-test SQLite stores they didn't need.

Anything autouse declared here applies to ``tests/unit/**`` only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

# Preloaded at collection time so StatementStore() is built before
# PYTEST_CURRENT_TEST is set — see _isolate_statement_store below.
import src.api.dependencies as _deps_preload
import src.api.routers.statement_helpers as _stmt_helpers_preload
import src.api.routers.statements as _stmts_router_preload
import src.api.routers.statements_crud as _stmts_crud_preload

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import Any


@pytest.fixture(autouse=True)
def _isolate_statement_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Redirect the StatementStore singleton + raw-PDF dir to a tmp path per test.

    Without this, tests that exercise /statements/upload end-to-end (see
    tests/unit/test_api_statement_persistence.py) write real rows into
    data/statements.db and real PDFs into data/raw/statements/, which then
    appear as "dummy" entries on the Statements tab in the running app.
    """
    from src.finance.statement_store import StatementStore

    tmp_store = StatementStore(db_path=tmp_path / "statements.db")
    tmp_raw = tmp_path / "raw" / "statements"
    monkeypatch.setattr(_deps_preload, "_statement_store", tmp_store)
    monkeypatch.setattr(_stmt_helpers_preload, "STATEMENTS_RAW_DIR", tmp_raw)
    monkeypatch.setattr(_stmts_router_preload, "STATEMENTS_RAW_DIR", tmp_raw)
    monkeypatch.setattr(_stmts_crud_preload, "STATEMENTS_RAW_DIR", tmp_raw)
    return


@pytest.fixture(autouse=True)
def _isolate_tax_override_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Redirect the TaxOverrideStore singleton to a tmp path per test.

    The store's ``__init__`` refuses its real ``data/tax_overrides.db`` under
    ``PYTEST_CURRENT_TEST``; without this, any test that resolves
    ``get_tax_override_store`` (the /tax-pack routes) would hit that guard or
    write real overrides. Mirrors ``_isolate_statement_store``.
    """
    from src.finance.tax_override_store import TaxOverrideStore

    tmp_store = TaxOverrideStore(db_path=tmp_path / "tax_overrides.db")
    monkeypatch.setattr(_deps_preload, "_tax_override_store", tmp_store)
    return


@pytest.fixture(autouse=True)
def _isolate_finance_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Per-test SQLite DB at tmp_path/finance.db with the schema initialized.

    Without this, any code path that queries `config_store` from the default
    `data/finance.db` crashes with `sqlite3.OperationalError: no such table:
    config_store` on a fresh checkout. `sqlite3.connect()` creates an empty
    file but doesn't run DDL — the schema only exists if production startup
    has called `ensure_schema()`. CI never does.

    Concretely this unblocks /api/v1/health (TestHealthAuthRequired,
    TestPublicPaths.test_health_is_public_without_token), which calls
    `imap_poller.get_imap_last_poll()` on every request.
    """
    from src.finance import local_db, poller_state, storage
    from src.finance.local_db import ensure_schema

    db_path = tmp_path / "finance.db"
    ensure_schema(db_path)

    # get_imap_last_poll() now lives in poller_state and resolves its default
    # path from poller_state.DEFAULT_DB_PATH at call time (health.py re-exports
    # it via imap_poller). Patch it there so the freshness probe hits the tmp DB.
    monkeypatch.setattr(poller_state, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(local_db, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(storage, "_FINANCE_DB_PATH", db_path)
    monkeypatch.setattr(storage, "_DEMO_DB_PATH", db_path)
    return


@pytest.fixture(autouse=True)
def _isolate_personal_config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Redirect every service's JSON-backup write target to a per-test tmp dir.

    The config services (override, category, merchant-alias, category-icon,
    budget) mirror each mutation into ``data/config/*.json`` via
    ``_write_backup``. Without this, any unit test that drives a mutation
    through an unpatched service clobbers the developer's real backup files
    (observed: ``category_overrides.json`` reduced to ``{"A": "B"}``).
    ``config_loader._PERSONAL_DIR`` is already pinned in the root conftest;
    this covers the five writer modules. Tests that assert on backup paths
    override with their own ``monkeypatch.setattr``.
    """
    import src.finance.budget_service_base as budget_base
    import src.finance.category_icon_service as icon_svc_module
    import src.finance.category_service as category_svc_module
    import src.finance.merchant_alias_service as alias_svc_module
    import src.finance.override_service as override_svc_module

    fake_personal_dir = tmp_path / "personal_config_isolated"
    for module in (budget_base, icon_svc_module, category_svc_module, alias_svc_module, override_svc_module):
        monkeypatch.setattr(module, "_PERSONAL_DIR", fake_personal_dir)
    return


@pytest.fixture(autouse=True)
def _isolate_app_config_auth(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Pin app_config into TOFU mode so API tests don't inherit a developer's
    real data/config.json.

    Without this, a local `data/config.json` with `app_password_hash` set (and
    `auth_bypass_for_dev: false`) makes the auth middleware leave TOFU mode, so
    every auth-gated /api/v1/* endpoint returns 401 and ~354 API tests fail. CI
    is unaffected only because data/config.json is gitignored there (absent →
    auto-detected `app_password_hash=None` → TOFU). This mirrors how
    `_reset_config_caches` (root conftest) isolates config_loader.

    Starts from the resolved config so storage/timezone/etc. are preserved
    (`_isolate_finance_db` already redirects the SQLite paths) and overrides only
    the two auth keys. Auth-specific tests (test_api_auth_*) override this via
    their own `isolated_config` fixture, which invalidates the cache and pins
    `_CONFIG_PATH` to a per-test tmp file.
    """
    from src.finance import app_config

    cfg = dict(app_config.get_config())
    cfg["app_password_hash"] = None
    cfg["auth_bypass_for_dev"] = False
    monkeypatch.setattr(app_config, "_cache", cfg)
    return


@pytest.fixture(autouse=True)
def _isolate_data_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Point secrets.py's data/.env at a per-test tmp file.

    POST /config/test-openai persists a live API key to this path and
    secrets.py reads it back (Tier 3). Without this, a test exercising that
    endpoint truncates the developer's real data/.env — the same incident
    class _isolate_personal_config_dir exists to prevent.
    """
    from src.finance import secrets

    # Mirrors the endpoint's real ``data/.env`` layout under tmp so the existing
    # TestOpenAIConnection endpoint tests (which write/read ``tmp_path/data/.env``
    # via ``monkeypatch.chdir``) still resolve to the redirected file.
    monkeypatch.setattr(secrets, "DATA_ENV_PATH", tmp_path / "data" / ".env")
    secrets.get_openai_api_key.cache_clear()
    yield
    secrets.get_openai_api_key.cache_clear()


@pytest.fixture(autouse=True)
def _reset_app_dependency_overrides() -> Iterator[None]:
    """Clear FastAPI ``app.dependency_overrides`` between tests.

    The ``api_client`` fixture in the root conftest already cleans up on
    teardown, but several ``test_api_*.py`` modules build their own
    ``TestClient(app)`` in a fixture or helper and rely on the shared app's
    overrides being cleared between tests.
    """
    from src.api.main import app

    yield
    app.dependency_overrides.clear()


@pytest.fixture
def dyn_resource() -> Iterator[Any]:
    """In-memory moto DynamoDB with the three production tables provisioned.

    Yields a real boto3 DynamoDB resource backed by ``moto`` so tests exercise
    the same code path production uses — optimistic locking
    (``ConditionExpression``), update-expression evaluation, ``Decimal``
    coercion, and query pagination — instead of a hand-built ``MagicMock``.

    Shared by ``test_dual_backend_contract.py`` and available to any unit test
    that wants storage fidelity. Not autouse: the moto import cost is only paid
    by tests that request it.
    """
    import os

    import boto3
    from moto import mock_aws

    # AWS credentials must be set for boto3 even when moto intercepts.
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name="us-west-2")
        for table_name in ("CategoryConfig", "BudgetConfig"):
            resource.create_table(
                TableName=table_name,
                KeySchema=[
                    {"AttributeName": "PK", "KeyType": "HASH"},
                    {"AttributeName": "SK", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "PK", "AttributeType": "S"},
                    {"AttributeName": "SK", "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",
            )
        resource.create_table(
            TableName="Transactions",
            KeySchema=[
                {"AttributeName": "ForwardedTo", "KeyType": "HASH"},
                {"AttributeName": "DateFileName", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "ForwardedTo", "AttributeType": "S"},
                {"AttributeName": "DateFileName", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield resource
