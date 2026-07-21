"""Shared test fixtures and helpers for all test modules.

Fixtures here apply to *every* test (unit, property, integration). Keep this
list narrow — anything API-specific lives in ``tests/unit/conftest.py`` so the
property + integration suites don't pay for monkeypatches they don't need.
"""

import json
import os
import sys
from collections.abc import Callable, Iterator
from datetime import date, datetime, tzinfo
from pathlib import Path
from typing import Any, Literal, get_args
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

import src.finance.config_loader as config_module
import src.finance.user_mapping as user_mapping_module

# Router modules that import ``run_sync`` from src.api.dependencies — the only
# valid targets for the ``mock_run_sync`` fixture below. Declared as a Literal so
# callers/helpers can annotate against it, with the runtime allowlist derived
# from the same source via ``get_args`` (no second list to keep in sync). A
# drift guard in tests/unit/test_mock_run_sync_fixture.py asserts this matches
# the actual source, so a newly-added router can't silently fall out of range.
RouterName = Literal[
    "attachments",
    "budget",
    "categories",
    "category_management",
    "coverage",
    "daily_summaries",
    "data",
    "groups",
    "ignore_rules",
    "income_statement",
    "ingestion",
    "insights",
    "journal",
    "merchant_aliases",
    "merchants",
    "overrides",
    "parse_failures",
    "search",
    "statements",
    "statements_crud",
    "summary",
    "tax",
    "transactions",
]
_RUN_SYNC_ROUTERS: frozenset[str] = frozenset(get_args(RouterName))

# ---------------------------------------------------------------------------
# Test data loading helpers
# ---------------------------------------------------------------------------

TEST_DATA_DIR = Path(__file__).parent / "test_data"


def read_file(filepath: str | Path) -> str:
    """Read a file and return its contents as a string."""
    with open(filepath) as file:
        return file.read()


def load_all_json_files(directory: str | Path) -> list[dict[str, Any]]:
    """Load all JSON files from a directory and return a list of dicts.

    Each dict gets a ``filename`` key with the JSON file's name.
    """
    json_files = sorted(Path(directory).glob("*.json"))
    all_data: list[dict[str, Any]] = []
    for json_file in json_files:
        with open(json_file) as file:
            data = json.load(file)
            data["filename"] = json_file.name
            all_data.append(data)
    return all_data


def load_test_data(institution: str) -> list[dict[str, Any]]:
    """Load all JSON test-data entries for a given institution.

    Parameters
    ----------
    institution : str
        Subdirectory name under ``tests/test_data/`` (e.g. ``"rbc"``).

    Returns
    -------
    list[dict]
    """
    return load_all_json_files(TEST_DATA_DIR / institution)


# ---------------------------------------------------------------------------
# User-id cache isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_user_id_cache():
    """Reset the global ``user_id_cache`` in user_mapping before each test."""
    user_mapping_module.user_id_cache.clear()
    yield
    user_mapping_module.user_id_cache.clear()


# ---------------------------------------------------------------------------
# Personal config isolation (applies to every test — config_loader is reachable
# from parsers + property tests, not just API code)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_config_caches(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Reset config caches and pin all config loading to the tracked defaults.

    Prevents personal ``data/config/`` overrides on the developer's machine
    from interfering with tests that expect the committed demo defaults.
    """
    # Force config_loader to use src/finance/config/ (never data/config/)
    monkeypatch.setattr(config_module, "_PERSONAL_DIR", Path("/nonexistent"))
    # Force user_mapping to use src/finance/user_mappings.csv (never data/config/)
    import src.finance.user_mapping as user_mapping_module2

    monkeypatch.setattr(user_mapping_module2, "_PERSONAL_MAPPINGS", Path("/nonexistent/user_mappings.csv"))

    config_module._simple_caches.clear()
    # Also clears the storage-backed category-list cache so get_category_list()
    # doesn't leak a populated list (DynamoDB or a test stub) across tests.
    config_module.invalidate_categories_cache()
    # Ignore rules are consulted at transaction-write time via a module-global
    # cache; clear it so a rule seeded in one test can't ignore rows in another.
    config_module.invalidate_ignore_rules_cache()
    yield
    config_module._simple_caches.clear()
    config_module.invalidate_categories_cache()
    config_module.invalidate_ignore_rules_cache()


# ---------------------------------------------------------------------------
# Activity-ledger isolation (applies to every test)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_activity_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the activity-ledger singleton at a per-test throwaway SQLite DB.

    The capture seam (`src.api.activity.capture_activity`) resolves the store
    via `dependencies.get_activity_store()` — a plain module-global read, not a
    FastAPI dependency — so `dependency_overrides` never reaches it. Without
    this fixture, every 2xx write a router test makes through TestClient would
    journal a real entry into the developer's `data/finance.db` (or, in
    DynamoDB mode, the real Activity table).
    """
    if "src.api.dependencies" in sys.modules:
        from src.finance.activity_store_local import ActivityStoreLocal

        deps = sys.modules["src.api.dependencies"]
        monkeypatch.setattr(deps, "_activity_store", ActivityStoreLocal(db_path=tmp_path / "activity-ledger.db"))


# ---------------------------------------------------------------------------
# Shared API test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client():
    """FastAPI TestClient with automatic dependency_overrides cleanup.

    Prefer this over module-level `client = TestClient(app)` — it guarantees
    that per-test dependency overrides don't bleed into sibling tests.

    Intentionally does NOT use `with TestClient(app) as c:` — that context
    manager triggers FastAPI startup/shutdown events which can block on
    lifecycle hooks (DB connections, background tasks).
    """
    from fastapi.testclient import TestClient

    from src.api.main import app

    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def api_client_raising():
    """Like `api_client`, but does NOT re-raise server-side exceptions.

    `TestClient(app, raise_server_exceptions=False)` returns the 500 response
    the app produced instead of propagating the exception into the test — the
    only way to observe the catch-all `unhandled_exception_handler` envelope.
    Constructing it here (not inline) keeps the `TestClient(` ban satisfied.
    """
    from fastapi.testclient import TestClient

    from src.api.main import app

    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def api_client_factory():
    """Build a TestClient around a CALLER-SUPPLIED FastAPI app.

    Why it exists: some API tests need a FRESH app per test rather than the
    process-wide singleton that `api_client` wraps — auth-middleware tests call
    `create_app()` after seeding isolated config so the middleware re-reads it,
    and the headless-toggle tests build `create_app()` under changed
    `SERVE_FRONTEND` / `CORS_ALLOWED_ORIGINS` env. `api_client` can't serve those
    because it only ever returns `TestClient(src.api.main.app)`. This fixture
    gives those files a sanctioned path so they can drop hand-rolled
    `TestClient(create_app())` and let the `scripts/checks/check_test_conventions.py`
    ratchet burn its baseline down to zero.

    Yields a builder ``(app: FastAPI) -> TestClient``; every client it builds has
    its app's `dependency_overrides` cleared on teardown so per-test overrides
    can't bleed across tests. Like `api_client`, it deliberately does NOT enter
    the `with TestClient(app)` context manager — startup/shutdown events must not
    run (they can block on lifecycle hooks: DB connections, background tasks).
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    built: list[FastAPI] = []

    def _build(app: FastAPI) -> TestClient:
        built.append(app)
        return TestClient(app)

    try:
        yield _build
    finally:
        for app in built:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Private-fixtures gating
# ---------------------------------------------------------------------------


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip @pytest.mark.private_fixtures tests unless RUN_PRIVATE_FIXTURES=1.

    Private fixtures are real (uncommitted) bank statements under
    tests/test_data/_private/. See that directory's README.md for usage.
    """
    if os.environ.get("RUN_PRIVATE_FIXTURES") == "1":
        return
    skip_marker = pytest.mark.skip(reason="set RUN_PRIVATE_FIXTURES=1 to run private-fixture tests")
    for item in items:
        if "private_fixtures" in item.keywords:
            item.add_marker(skip_marker)


@pytest.fixture
def mock_run_sync(request: pytest.FixtureRequest) -> Iterator[AsyncMock]:
    """Patch `run_sync` in a router module. Parametrize with the router name.

    The 14 `test_api_*.py` files each patch `src.api.routers.<name>.run_sync`
    above nearly every test method — 169+ decorator copies total. This fixture
    replaces the boilerplate with a single parametrized argument.

    Usage:
        @pytest.mark.parametrize("mock_run_sync", ["budget"], indirect=True)
        def test_foo(mock_run_sync, api_client):
            mock_run_sync.return_value = [...]
            resp = api_client.get("/api/v1/budget/...")

    For tests that patch multiple router modules in one method (rare), keep
    the explicit `@patch(...)` decorators — the fixture is additive, not
    mandatory.
    """
    router = request.param
    if router not in _RUN_SYNC_ROUTERS:
        pytest.fail(
            f"mock_run_sync: unknown router {router!r}. Valid routers (those importing "
            f"run_sync): {sorted(_RUN_SYNC_ROUTERS)}",
            pytrace=False,
        )
    with patch(f"src.api.routers.{router}.run_sync", new_callable=AsyncMock) as m:
        yield m


# ---------------------------------------------------------------------------
# Frozen-clock seam
# ---------------------------------------------------------------------------

# The one canonical instant every ``freeze_clock`` caller inherits unless it
# passes its own ``at=``. 20:00 Pacific on 2026-05-07 — carried over verbatim
# from the daily-summary scheduler's former local helper (kept identical for
# continuity). It is late enough in the day to sit past the schedule minutes the
# scheduler tests use ("00:01"/"19:00"), and it lands squarely inside 2026 so the
# budget tests can hard-code "current month == May" without a wall-clock read.
_FROZEN_TZ = ZoneInfo("America/Los_Angeles")
_DEFAULT_FROZEN_NOW = datetime(2026, 5, 7, 20, 0, tzinfo=_FROZEN_TZ)


@pytest.fixture
def freeze_clock(monkeypatch: pytest.MonkeyPatch) -> Callable[..., datetime]:
    """Pin a target module's clock to a fixed instant; return the frozen datetime.

    Kills a recurring flake class: a test reads the real wall clock
    (``date.today()`` / an implicit "now") while the code under test reads
    ``datetime.now(get_app_timezone())`` (app timezone, config-driven, default
    America/Los_Angeles — see src/finance/app_timezone.py). When the host ``TZ``
    or the day-of-run disagrees with the test's assumption, any assertion that
    pins "today" / "this month" flakes — a failure this suite has already shipped
    to CI. Freezing both sides to one instant removes the seam entirely.

    Usage::

        def test_foo(freeze_clock):
            frozen = freeze_clock(some_module)                    # default instant
            frozen = freeze_clock(some_module, at=datetime(...))  # custom instant

    Patches, on ``module``'s own namespace, whichever of these three names it
    actually binds — so it works for modules that did ``from datetime import
    datetime`` / ``from datetime import date`` as well as those that call
    ``get_app_timezone()``:

    * ``datetime`` → a subclass whose ``now(tz)`` returns the frozen aware
      instant (the passed ``tz`` is ignored — the instant already carries one).
    * ``date`` → a subclass whose ``today()`` returns the frozen local date.
    * ``get_app_timezone`` → returns the frozen instant's tzinfo.

    A module that binds none of the three is almost certainly the wrong freeze
    target; a silent no-op there would let the flake survive, so fail loudly
    (mirrors the ``mock_run_sync`` unknown-router guard above).
    """

    def _freeze(module: object, *, at: datetime = _DEFAULT_FROZEN_NOW) -> datetime:
        if at.tzinfo is None:
            pytest.fail("freeze_clock: `at` must be timezone-aware", pytrace=False)

        class _FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz: tzinfo | None = None) -> datetime:
                return at

        class _FrozenDate(date):
            @classmethod
            def today(cls) -> date:
                return at.date()

        patched: list[str] = []
        # Only rebind a name the module actually holds *as a type/callable* — a
        # module that did ``import datetime`` (the module, not the class) must
        # not be clobbered with a class.
        if isinstance(getattr(module, "datetime", None), type):
            monkeypatch.setattr(module, "datetime", _FrozenDatetime)
            patched.append("datetime")
        if isinstance(getattr(module, "date", None), type):
            monkeypatch.setattr(module, "date", _FrozenDate)
            patched.append("date")
        if callable(getattr(module, "get_app_timezone", None)):
            monkeypatch.setattr(module, "get_app_timezone", lambda: at.tzinfo)
            patched.append("get_app_timezone")

        if not patched:
            pytest.fail(
                f"freeze_clock: {getattr(module, '__name__', module)!r} binds none of "
                "datetime/date/get_app_timezone — nothing to freeze (wrong target?)",
                pytrace=False,
            )
        return at

    return _freeze
