"""Tests for the activity ledger's Phase 1 surface: principal plumbing,
throttled ``mark_used``, and ``GET /api/v1/whoami``.

The whoami endpoint reflects ``request.state.principal`` back to the caller, so
it doubles as the observable seam for the principal that the auth middleware
resolves on each channel (bearer → token, cookie → session, TOFU → tofu, dev
bypass → dev-bypass).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from src.api import activity as activity_module
from src.api import auth as auth_module
from src.api import dependencies as deps_module
from src.api.auth import Principal
from src.api.dependencies import get_merchant_alias_service
from src.api.main import create_app
from src.finance import agent_tokens, app_config
from src.finance.activity_store_local import ActivityStoreLocal
from src.finance.auth_session import COOKIE_NAME, hash_password, issue_session
from tests.asserts import assert_ok, assert_problem

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import Any


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Pin app_config persistence at a tmp file so tests can seed tokens cleanly."""
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(app_config, "_CONFIG_PATH", cfg_path)
    app_config.invalidate_config_cache()
    yield cfg_path
    app_config.invalidate_config_cache()


def _seed_password(plain: str = "correct-horse-battery-staple") -> None:
    app_config.update_config({"app_password_hash": hash_password(plain)})


# ---------------------------------------------------------------------------
# whoami — one row per auth channel; reflects the resolved principal
# ---------------------------------------------------------------------------


class TestWhoamiChannels:
    def test_bearer_returns_token_principal_with_id_label_scope(
        self, isolated_config: Path, api_client_factory
    ) -> None:
        record, raw = agent_tokens.add_token(label="laptop-claude", scope="read+write")
        client = api_client_factory(create_app())
        resp = client.get("/api/v1/whoami", headers={"Authorization": f"Bearer {raw}"})
        body = assert_ok(resp)
        assert body["kind"] == "token"
        assert body["token_id"] == record["id"]
        assert body["label"] == "laptop-claude"
        assert body["scope"] == "read+write"

    def test_read_token_reports_read_scope(self, isolated_config: Path, api_client_factory) -> None:
        _record, raw = agent_tokens.add_token(label="readonly", scope="read")
        client = api_client_factory(create_app())
        resp = client.get("/api/v1/whoami", headers={"Authorization": f"Bearer {raw}"})
        body = assert_ok(resp)
        assert body["kind"] == "token"
        assert body["scope"] == "read"

    def test_cookie_session_returns_session_principal(self, isolated_config: Path, api_client_factory) -> None:
        _seed_password()
        secret = app_config.get_session_signing_secret()
        version = int(app_config.get_config().get("session_version", 0) or 0)
        cookie = issue_session(version=version, secret=secret)
        client = api_client_factory(create_app())
        client.cookies.set(COOKIE_NAME, cookie)
        resp = client.get("/api/v1/whoami")
        body = assert_ok(resp)
        assert body["kind"] == "session"
        assert body["token_id"] is None
        assert body["label"] is None
        assert body["scope"] is None
        assert body["last_used_at"] is None

    def test_tofu_returns_tofu_principal(self, isolated_config: Path, api_client_factory) -> None:
        # No password, no tokens, no header → TOFU bootstrap allow.
        client = api_client_factory(create_app())
        resp = client.get("/api/v1/whoami")
        body = assert_ok(resp)
        assert body["kind"] == "tofu"
        assert body["token_id"] is None
        assert body["last_used_at"] is None

    def test_dev_bypass_returns_dev_bypass_principal(self, isolated_config: Path, api_client_factory) -> None:
        _seed_password()
        app_config.update_config({"auth_bypass_for_dev": True})
        client = api_client_factory(create_app())
        resp = client.get("/api/v1/whoami")
        body = assert_ok(resp)
        assert body["kind"] == "dev-bypass"
        assert body["token_id"] is None

    def test_unauth_whoami_401(self, isolated_config: Path, api_client_factory) -> None:
        """whoami is a normal /api/v1 endpoint — not public, not exempt."""
        _seed_password()
        agent_tokens.add_token(label="seed")
        client = api_client_factory(create_app())
        resp = client.get("/api/v1/whoami")
        assert_problem(resp, 401, "UNAUTHORIZED")

    def test_read_scope_permits_whoami_get(self, isolated_config: Path, api_client_factory) -> None:
        """whoami is a GET, so a strict `read` token reaches it (scope regression)."""
        _record, raw = agent_tokens.add_token(label="ro", scope="read")
        client = api_client_factory(create_app())
        resp = client.get("/api/v1/whoami", headers={"Authorization": f"Bearer {raw}"})
        assert_ok(resp)


class TestWhoamiLastUsedAt:
    def test_bearer_whoami_stamps_and_returns_last_used_at(
        self, isolated_config: Path, api_client_factory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bearer request stamps last_used_at (first, unthrottled call) so
        whoami reads back a non-null value.

        The stamp is now off the event loop (fire-and-forget, L9/FIX 5), so the
        write is driven and drained explicitly before the whoami read. The whoami
        request's own middleware call is throttled (same token, inside the
        window), so it does not re-stamp and the drained value is what is read."""
        monkeypatch.setattr(auth_module, "_mark_used_last", {})
        record, raw = agent_tokens.add_token(label="stamped", scope="read+write")
        assert record["last_used_at"] is None  # freshly minted

        async def _stamp() -> None:
            auth_module._maybe_mark_used(record["id"])
            await activity_module.drain_ledger_tasks()

        asyncio.run(_stamp())

        client = api_client_factory(create_app())
        resp = client.get("/api/v1/whoami", headers={"Authorization": f"Bearer {raw}"})
        body = assert_ok(resp)
        assert body["last_used_at"] is not None
        # And it is persisted on the record itself.
        stored = next(t for t in agent_tokens.list_tokens() if t["id"] == record["id"])
        assert stored["last_used_at"] is not None


# ---------------------------------------------------------------------------
# mark_used throttle — once per token per window (L9)
# ---------------------------------------------------------------------------


class _FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def monotonic(self) -> float:
        return self.now


class TestMarkUsedThrottle:
    """The actual ``mark_used`` is dispatched fire-and-forget (FIX 5), so each
    scenario drives ``_maybe_mark_used`` inside an event loop and drains the
    ledger task set before asserting which stamps actually fired. The throttle
    bookkeeping itself stays synchronous, so the throttle decisions are unchanged.
    """

    def test_called_once_then_throttled_within_window(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        monkeypatch.setattr(auth_module, "_mark_used_last", {})
        monkeypatch.setattr(auth_module, "mark_used", lambda tid: calls.append(tid))
        clock = _FakeClock()
        monkeypatch.setattr(auth_module, "time", clock)

        async def driver() -> None:
            auth_module._maybe_mark_used("tok1")
            clock.now += 60  # 1 minute later — inside the 15-minute window
            auth_module._maybe_mark_used("tok1")
            clock.now += 60
            auth_module._maybe_mark_used("tok1")
            await activity_module.drain_ledger_tasks()

        asyncio.run(driver())
        assert calls == ["tok1"]

    def test_fires_again_after_window_elapses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        monkeypatch.setattr(auth_module, "_mark_used_last", {})
        monkeypatch.setattr(auth_module, "mark_used", lambda tid: calls.append(tid))
        clock = _FakeClock()
        monkeypatch.setattr(auth_module, "time", clock)

        async def driver() -> None:
            auth_module._maybe_mark_used("tok1")
            clock.now += auth_module._MARK_USED_THROTTLE_SECONDS + 1
            auth_module._maybe_mark_used("tok1")
            await activity_module.drain_ledger_tasks()

        asyncio.run(driver())
        assert calls == ["tok1", "tok1"]

    def test_throttle_is_per_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        monkeypatch.setattr(auth_module, "_mark_used_last", {})
        monkeypatch.setattr(auth_module, "mark_used", lambda tid: calls.append(tid))
        clock = _FakeClock()
        monkeypatch.setattr(auth_module, "time", clock)

        async def driver() -> None:
            # Drain between dispatches so the two off-loop stamps land in order
            # (both tokens stamp: the throttle is per-token, not global).
            auth_module._maybe_mark_used("tok1")
            await activity_module.drain_ledger_tasks()
            auth_module._maybe_mark_used("tok2")
            await activity_module.drain_ledger_tasks()

        asyncio.run(driver())
        assert calls == ["tok1", "tok2"]

    def test_fail_open_when_mark_used_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A config-write failure must be swallowed, never propagated.

        The failing ``mark_used`` runs fire-and-forget; its exception is captured
        by the ledger task done-callback (logged, not raised), so neither the
        dispatch nor the drain surfaces it to the caller."""

        def _boom(_tid: str) -> None:
            raise RuntimeError("disk full")

        monkeypatch.setattr(auth_module, "_mark_used_last", {})
        monkeypatch.setattr(auth_module, "mark_used", _boom)

        async def driver() -> None:
            auth_module._maybe_mark_used("tok1")  # dispatch; the raise happens off-loop
            await activity_module.drain_ledger_tasks()  # must not propagate

        # Should not raise.
        asyncio.run(driver())


# ---------------------------------------------------------------------------
# Principal dataclass shape (L2)
# ---------------------------------------------------------------------------


class TestPrincipal:
    def test_defaults_none_for_non_token_fields(self) -> None:
        p = Principal(kind="session")
        assert p.kind == "session"
        assert p.token_id is None
        assert p.label is None
        assert p.scope is None

    def test_is_frozen(self) -> None:
        import dataclasses

        p = Principal(kind="token", token_id="abc", label="x", scope="read")
        with pytest.raises(dataclasses.FrozenInstanceError):
            p.kind = "session"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# GET /api/v1/activity — the write journal, fed by real middleware capture (P3)
# ---------------------------------------------------------------------------


class _FakeAliasService:
    """Minimal in-memory merchant-alias service for exercising a captured write.

    The put_alias handler reads the current aliases (before-image) and writes the
    new one — both are all this stub needs to implement.
    """

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get_aliases(self) -> dict[str, Any]:
        return {"Data": dict(self.data), "Version": 1}

    def put_alias(self, raw_name: str, canonical_name: str) -> None:
        self.data[raw_name] = canonical_name


@pytest.fixture
def sync_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ActivityStoreLocal:
    """Point the activity store at a temp DB and make capture synchronous.

    Capture is fire-and-forget in production (L7); for deterministic assertions
    the plan sanctions monkeypatching ``_dispatch_record`` to a synchronous
    ``store.record`` call. The store is redirected to a temp SQLite file so the
    test neither touches nor depends on the developer's ``data/`` tree.
    """
    store = ActivityStoreLocal(tmp_path / "activity.db")
    monkeypatch.setattr(deps_module, "_activity_store", store)
    monkeypatch.setattr(activity_module, "_dispatch_record", lambda s, entry: s.record(entry))
    return store


class TestActivityFeedCapture:
    def test_instrumented_put_alias_lands_a_reversible_entry(
        self, isolated_config: Path, sync_ledger: ActivityStoreLocal, api_client_factory
    ) -> None:
        record, raw = agent_tokens.add_token(label="kitchen-agent", scope="read+write")
        fake = _FakeAliasService()
        app = create_app()
        app.dependency_overrides[get_merchant_alias_service] = lambda: fake
        client = api_client_factory(app)
        headers = {"Authorization": f"Bearer {raw}"}

        put = client.put("/api/v1/merchant-aliases/amzn", json={"canonical_name": "Amazon"}, headers=headers)
        assert_ok(put)
        assert fake.data == {"amzn": "Amazon"}

        listed = assert_ok(client.get("/api/v1/activity", headers=headers))
        entries = listed["entries"]
        assert len(entries) == 1
        entry = entries[0]
        assert entry["operation_id"] == "putMerchantAlias"
        assert entry["method"] == "PUT"
        assert entry["resource_id"] == "amzn"
        assert entry["reversible"] is True
        assert entry["principal_kind"] == "token"
        assert entry["principal_id"] == record["id"]
        assert entry["principal_label"] == "kitchen-agent"
        assert entry["summary"] == "set merchant alias for amzn"
        # New alias → create-shaped empty before, after carries the written value.
        assert entry["before"] == {}
        assert entry["after"] == {"raw_name": "amzn", "canonical_name": "Amazon"}

    def test_capture_failure_never_fails_the_write(
        self, isolated_config: Path, sync_ledger: ActivityStoreLocal, api_client_factory, monkeypatch
    ) -> None:
        def _boom(_store: Any, _entry: Any) -> None:
            raise RuntimeError("ledger unavailable")

        monkeypatch.setattr(activity_module, "_dispatch_record", _boom)
        _record, raw = agent_tokens.add_token(label="agent", scope="read+write")
        fake = _FakeAliasService()
        app = create_app()
        app.dependency_overrides[get_merchant_alias_service] = lambda: fake
        client = api_client_factory(app)
        headers = {"Authorization": f"Bearer {raw}"}

        # The write still succeeds even though the ledger dispatch raises.
        resp = client.put("/api/v1/merchant-aliases/wf", json={"canonical_name": "Whole Foods"}, headers=headers)
        assert_ok(resp)
        assert fake.data == {"wf": "Whole Foods"}

    def test_principal_me_resolves_to_the_caller_token(
        self, isolated_config: Path, sync_ledger: ActivityStoreLocal, api_client_factory
    ) -> None:
        # Two tokens each make a write; ?principal=me returns only the caller's.
        rec_a, raw_a = agent_tokens.add_token(label="agent-a", scope="read+write")
        _rec_b, raw_b = agent_tokens.add_token(label="agent-b", scope="read+write")
        fake = _FakeAliasService()
        app = create_app()
        app.dependency_overrides[get_merchant_alias_service] = lambda: fake
        client = api_client_factory(app)

        assert_ok(
            client.put(
                "/api/v1/merchant-aliases/a",
                json={"canonical_name": "Alpha"},
                headers={"Authorization": f"Bearer {raw_a}"},
            )
        )
        assert_ok(
            client.put(
                "/api/v1/merchant-aliases/b",
                json={"canonical_name": "Beta"},
                headers={"Authorization": f"Bearer {raw_b}"},
            )
        )

        mine = assert_ok(client.get("/api/v1/activity?principal=me", headers={"Authorization": f"Bearer {raw_a}"}))
        entries = mine["entries"]
        assert len(entries) == 1
        assert entries[0]["principal_id"] == rec_a["id"]
        assert entries[0]["resource_id"] == "a"

        # And a raw token-id filter behaves the same as `me`.
        by_id = assert_ok(
            client.get(f"/api/v1/activity?principal={rec_a['id']}", headers={"Authorization": f"Bearer {raw_a}"})
        )
        assert len(by_id["entries"]) == 1

    def test_operation_and_limit_filters(
        self, isolated_config: Path, sync_ledger: ActivityStoreLocal, api_client_factory
    ) -> None:
        _record, raw = agent_tokens.add_token(label="agent", scope="read+write")
        fake = _FakeAliasService()
        app = create_app()
        app.dependency_overrides[get_merchant_alias_service] = lambda: fake
        client = api_client_factory(app)
        headers = {"Authorization": f"Bearer {raw}"}

        for name in ("one", "two", "three"):
            assert_ok(client.put(f"/api/v1/merchant-aliases/{name}", json={"canonical_name": name}, headers=headers))

        # operation filter matches only the alias puts.
        by_op = assert_ok(client.get("/api/v1/activity?operation=putMerchantAlias", headers=headers))
        assert len(by_op["entries"]) == 3
        # A non-matching operation returns nothing.
        none = assert_ok(client.get("/api/v1/activity?operation=putOverride", headers=headers))
        assert none["entries"] == []
        # limit caps the page.
        capped = assert_ok(client.get("/api/v1/activity?limit=2", headers=headers))
        assert len(capped["entries"]) == 2

    def test_limit_out_of_range_is_rejected(
        self, isolated_config: Path, sync_ledger: ActivityStoreLocal, api_client_factory
    ) -> None:
        _record, raw = agent_tokens.add_token(label="agent", scope="read+write")
        client = api_client_factory(create_app())
        headers = {"Authorization": f"Bearer {raw}"}
        assert_problem(client.get("/api/v1/activity?limit=0", headers=headers), 422)
        assert_problem(client.get("/api/v1/activity?limit=501", headers=headers), 422)
