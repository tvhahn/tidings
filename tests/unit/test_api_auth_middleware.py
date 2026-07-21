"""Tests for the bearer-auth middleware.

Three channels under test:
- Phase 1 bearer: `Authorization: Bearer fin_…` against `agent_tokens`.
- Phase 4 cookie: `tidings_session` HMAC + matching `session_version`.
- Phase 4 TOFU: `app_password_hash is None` allows everything.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from src.api.auth import scope_allows
from src.api.main import create_app
from src.finance import agent_tokens, app_config
from src.finance.auth_session import COOKIE_NAME, hash_password, issue_session
from tests.asserts import assert_ok, assert_problem

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from fastapi.testclient import TestClient


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Pin app_config persistence at a tmp file so tests can seed tokens cleanly."""
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(app_config, "_CONFIG_PATH", cfg_path)
    app_config.invalidate_config_cache()
    yield cfg_path
    app_config.invalidate_config_cache()


@pytest.fixture
def app_client(isolated_config: Path, api_client_factory) -> TestClient:
    """A fresh app + TestClient sharing the isolated config.

    Built via the sanctioned api_client_factory fixture (tests/conftest.py) —
    a fresh `create_app()` is required so the middleware re-reads isolated config.
    """
    return api_client_factory(create_app())


def _seed_password(plain: str = "correct-horse-battery-staple") -> None:
    """Set `app_password_hash` so the middleware leaves TOFU mode."""
    app_config.update_config({"app_password_hash": hash_password(plain)})


# ---------------------------------------------------------------------------
# Scope-allowlist pure-function tests (no app needed)
# ---------------------------------------------------------------------------


class TestScopeAllows:
    def test_read_permits_any_get_under_v1(self) -> None:
        assert scope_allows("read", "GET", "/api/v1/transactions") is True
        assert scope_allows("read", "GET", "/api/v1/categories") is True
        assert scope_allows("read", "GET", "/api/v1/summary") is True

    def test_read_blocks_writes(self) -> None:
        assert scope_allows("read", "POST", "/api/v1/transactions") is False
        assert scope_allows("read", "DELETE", "/api/v1/transactions/x") is False
        assert scope_allows("read", "PATCH", "/api/v1/transactions/bulk") is False
        assert scope_allows("read", "PUT", "/api/v1/overrides") is False

    def test_read_write_permits_writes(self) -> None:
        assert scope_allows("read+write", "POST", "/api/v1/transactions") is True
        assert scope_allows("read+write", "DELETE", "/api/v1/transactions/x") is True
        assert scope_allows("read+write", "PATCH", "/api/v1/transactions/bulk") is True
        assert scope_allows("read+write", "GET", "/api/v1/summary") is True

    def test_unknown_scope_allows_nothing(self) -> None:
        assert scope_allows("admin", "GET", "/api/v1/transactions") is False
        assert scope_allows("", "GET", "/api/v1/transactions") is False

    def test_paths_outside_v1_not_allowlisted(self) -> None:
        # Auth middleware only gates /api/v1/* anyway, but the scope
        # allowlist still says "no" for non-API paths.
        assert scope_allows("read", "GET", "/health") is False
        assert scope_allows("read+write", "GET", "/static/foo") is False


# ---------------------------------------------------------------------------
# No-op when no tokens configured (Tier 0 row 3 / Phase 0 boundary)
# ---------------------------------------------------------------------------


class TestNoTokensNoAuth:
    def test_no_tokens_configured_means_no_auth_required(self, app_client: TestClient) -> None:
        """Empty agent_tokens + no Authorization header → request still succeeds."""
        # Categories is a stable read endpoint that doesn't need DB seeding.
        resp = app_client.get("/api/v1/categories")
        assert_ok(resp)

    def test_no_tokens_post_also_unblocked(self, app_client: TestClient) -> None:
        """Writes are NOT gated when agent_tokens is empty — preserves zero-config UX."""
        # /api/v1/groups POST exists; we're not asserting anything about its body
        # beyond it not 401-ing (it may 422 on missing body, which is fine).
        resp = app_client.post("/api/v1/groups", json={})
        assert resp.status_code != 401


# ---------------------------------------------------------------------------
# Public paths bypass auth even when tokens exist
# ---------------------------------------------------------------------------


class TestPublicPaths:
    def test_health_is_public_without_token(self, isolated_config: Path, api_client_factory) -> None:
        agent_tokens.add_token(label="seed")
        client = api_client_factory(create_app())
        resp = client.get("/api/v1/health")
        assert_ok(resp)
        assert "status" in resp.json()

    def test_openapi_is_public(self, isolated_config: Path, api_client_factory) -> None:
        agent_tokens.add_token(label="seed")
        client = api_client_factory(create_app())
        resp = client.get("/openapi.json")
        assert_ok(resp)
        assert resp.json()["info"]["title"] == "Finance Dashboard API"

    def test_docs_is_public(self, isolated_config: Path, api_client_factory) -> None:
        agent_tokens.add_token(label="seed")
        client = api_client_factory(create_app())
        resp = client.get("/docs")
        assert_ok(resp)


# ---------------------------------------------------------------------------
# 401 paths
# ---------------------------------------------------------------------------


class TestUnauthRequest:
    """Once a password is set, the middleware leaves TOFU mode and unauthed
    requests on /api/v1/* are 401."""

    def test_unauth_request_returns_401_with_unified_shape(self, isolated_config: Path, api_client_factory) -> None:
        _seed_password()
        agent_tokens.add_token(label="seed")
        client = api_client_factory(create_app())
        resp = client.get("/api/v1/categories")
        assert_problem(resp, 401, "UNAUTHORIZED")

    def test_wrong_scheme_returns_401(self, isolated_config: Path, api_client_factory) -> None:
        _seed_password()
        agent_tokens.add_token(label="seed")
        client = api_client_factory(create_app())
        resp = client.get("/api/v1/categories", headers={"Authorization": "Basic abc:def"})
        assert_problem(resp, 401, "UNAUTHORIZED")

    def test_invalid_token_returns_401(self, isolated_config: Path, api_client_factory) -> None:
        _seed_password()
        agent_tokens.add_token(label="seed")
        client = api_client_factory(create_app())
        resp = client.get(
            "/api/v1/categories",
            headers={"Authorization": "Bearer fin_definitely_not_a_real_token"},
        )
        assert_problem(resp, 401, "UNAUTHORIZED")

    def test_token_without_fin_prefix_returns_401(self, isolated_config: Path, api_client_factory) -> None:
        # Even if the bytes happen to match a stored hash, missing prefix is a 401.
        _seed_password()
        agent_tokens.add_token(label="seed")
        client = api_client_factory(create_app())
        resp = client.get(
            "/api/v1/categories",
            headers={"Authorization": "Bearer not_fin_prefix_token"},
        )
        assert_problem(resp, 401)

    def test_password_set_no_auth_returns_401(self, isolated_config: Path, api_client_factory) -> None:
        """Phase 4: setting a password leaves TOFU mode. No tokens, no cookie, no header → 401."""
        _seed_password()
        client = api_client_factory(create_app())
        resp = client.get("/api/v1/categories")
        assert_problem(resp, 401)


# ---------------------------------------------------------------------------
# Happy path + scope enforcement
# ---------------------------------------------------------------------------


class TestValidToken:
    def test_valid_read_token_allows_get(self, isolated_config: Path, api_client_factory) -> None:
        _, raw = agent_tokens.add_token(label="readonly", scope="read")
        client = api_client_factory(create_app())
        resp = client.get(
            "/api/v1/categories",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert_ok(resp)

    def test_valid_read_write_token_allows_get(self, isolated_config: Path, api_client_factory) -> None:
        _, raw = agent_tokens.add_token(label="rw", scope="read+write")
        client = api_client_factory(create_app())
        resp = client.get(
            "/api/v1/categories",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert_ok(resp)


class TestScopeEnforcement:
    def test_read_token_blocked_on_post_returns_403(self, isolated_config: Path, api_client_factory) -> None:
        _, raw = agent_tokens.add_token(label="readonly", scope="read")
        client = api_client_factory(create_app())
        resp = client.post(
            "/api/v1/groups",
            json={"name": "test", "categories": []},
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert_problem(resp, 403, "FORBIDDEN")

    def test_read_token_blocked_on_delete_returns_403(self, isolated_config: Path, api_client_factory) -> None:
        _, raw = agent_tokens.add_token(label="readonly", scope="read")
        client = api_client_factory(create_app())
        resp = client.delete(
            "/api/v1/transactions/foo/bar",
            headers={"Authorization": f"Bearer {raw}"},
        )
        # Either 403 (scope blocks) or — if route doesn't exist — 404. The
        # contract this test pins is "scope check fires before the route
        # handler," so 403 is the only acceptable answer.
        assert_problem(resp, 403)


class TestPreflightUnaffected:
    def test_options_preflight_bypasses_auth(self, isolated_config: Path, api_client_factory) -> None:
        _seed_password()
        agent_tokens.add_token(label="seed")
        client = api_client_factory(create_app())
        resp = client.options(
            "/api/v1/categories",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        assert_ok(resp)
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


# ---------------------------------------------------------------------------
# Phase 4: cookie session
# ---------------------------------------------------------------------------


class TestCookieSession:
    def test_valid_cookie_allows_request(self, isolated_config: Path, api_client_factory) -> None:
        _seed_password()
        secret = app_config.get_session_signing_secret()
        version = int(app_config.get_config().get("session_version", 0) or 0)
        cookie = issue_session(version=version, secret=secret)
        client = api_client_factory(create_app())
        client.cookies.set(COOKIE_NAME, cookie)
        resp = client.get("/api/v1/categories")
        assert_ok(resp)

    def test_tampered_cookie_returns_401(self, isolated_config: Path, api_client_factory) -> None:
        _seed_password()
        secret = app_config.get_session_signing_secret()
        cookie = issue_session(version=0, secret=secret)
        # Flip one character in the signature half — HMAC mismatch.
        head, _, sig = cookie.partition(".")
        tampered = f"{head}.{'A' * len(sig)}"
        client = api_client_factory(create_app())
        client.cookies.set(COOKIE_NAME, tampered)
        resp = client.get("/api/v1/categories")
        assert_problem(resp, 401)

    def test_stale_session_version_returns_401(self, isolated_config: Path, api_client_factory) -> None:
        _seed_password()
        secret = app_config.get_session_signing_secret()
        # Issue a cookie at version 0, then bump to 5 → cookie invalid.
        old_cookie = issue_session(version=0, secret=secret)
        app_config.update_config({"session_version": 5})
        client = api_client_factory(create_app())
        client.cookies.set(COOKIE_NAME, old_cookie)
        resp = client.get("/api/v1/categories")
        assert_problem(resp, 401)

    def test_garbage_cookie_returns_401(self, isolated_config: Path, api_client_factory) -> None:
        _seed_password()
        client = api_client_factory(create_app())
        client.cookies.set(COOKIE_NAME, "not.a.valid.cookie")
        resp = client.get("/api/v1/categories")
        assert_problem(resp, 401)


# ---------------------------------------------------------------------------
# Phase 4: TOFU bootstrap mode
# ---------------------------------------------------------------------------


class TestTofuMode:
    def test_no_password_no_tokens_allows_anything(self, isolated_config: Path, api_client_factory) -> None:
        client = api_client_factory(create_app())
        # No password, no tokens, no cookie, no header → TOFU allow.
        resp = client.get("/api/v1/categories")
        assert_ok(resp)

    def test_no_password_with_tokens_still_tofu(self, isolated_config: Path, api_client_factory) -> None:
        """Per spec table: null password row allows browser-no-cookie to pass."""
        agent_tokens.add_token(label="seed")
        client = api_client_factory(create_app())
        resp = client.get("/api/v1/categories")
        # No Authorization header → TOFU branch (because password is null).
        assert_ok(resp)

    def test_no_password_invalid_bearer_still_401(self, isolated_config: Path, api_client_factory) -> None:
        """Authorization-present takes priority over TOFU. A garbage bearer 401s."""
        agent_tokens.add_token(label="seed")
        client = api_client_factory(create_app())
        resp = client.get(
            "/api/v1/categories",
            headers={"Authorization": "Bearer fin_garbage"},
        )
        assert_problem(resp, 401)


# ---------------------------------------------------------------------------
# Dev escape hatch: auth_bypass_for_dev
# ---------------------------------------------------------------------------


class TestDevBypass:
    """`auth_bypass_for_dev=True` short-circuits the cookie/no-credential path
    so the agent driving Chrome DevTools can hit /api/v1/* without a session.
    Bearer enforcement still fires before the bypass branch."""

    def test_bypass_allows_cookieless_request_when_password_set(
        self, isolated_config: Path, api_client_factory
    ) -> None:
        _seed_password()
        app_config.update_config({"auth_bypass_for_dev": True})
        client = api_client_factory(create_app())
        resp = client.get("/api/v1/categories")
        assert_ok(resp)

    def test_bypass_off_still_requires_auth(self, isolated_config: Path, api_client_factory) -> None:
        """Default (bypass absent / False) preserves Phase 4 enforcement."""
        _seed_password()
        app_config.update_config({"auth_bypass_for_dev": False})
        client = api_client_factory(create_app())
        resp = client.get("/api/v1/categories")
        assert_problem(resp, 401)

    def test_invalid_bearer_still_401_under_bypass(self, isolated_config: Path, api_client_factory) -> None:
        """Bearer branch runs before the bypass — a malformed bearer still fails fast."""
        _seed_password()
        app_config.update_config({"auth_bypass_for_dev": True})
        client = api_client_factory(create_app())
        resp = client.get(
            "/api/v1/categories",
            headers={"Authorization": "Bearer fin_garbage"},
        )
        assert_problem(resp, 401)


# ---------------------------------------------------------------------------
# chatgpt-oauth handlers: under the /api/v1/auth/ middleware exemption but
# NOT bootstrap endpoints — they enforce the channels via router dependency.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Regression guard: every /api/v1/auth/* route self-enforces
# ---------------------------------------------------------------------------

# Endpoints that are deliberately reachable without credentials while a
# password is set. Anything new under /api/v1/auth/ must be added here
# CONSCIOUSLY or carry its own auth check.
_PUBLIC_AUTH_ROUTES = {
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/auth/set-password"),  # self-enforces current_password internally
}


def _iter_leaf_routes(routes: object, prefix: str = ""):
    """Yield (method, full_path) for every leaf route.

    FastAPI ≥ this version wraps `include_router` results in `_IncludedRouter`
    branch nodes rather than flattening APIRoutes onto `app.routes`, so a plain
    `for route in app.routes` no longer sees mounted paths. Recurse through the
    branch nodes (and tolerate flat APIRoutes) to reconstruct full paths.
    """
    from fastapi.routing import _IncludedRouter

    for route in routes:  # type: ignore[attr-defined]
        if isinstance(route, _IncludedRouter):
            sub_prefix = prefix + (route.include_context.prefix or "")
            yield from _iter_leaf_routes(route.original_router.routes, sub_prefix)
            continue
        path = getattr(route, "path", None)
        if path is None:
            continue
        for method in getattr(route, "methods", set()) or set():
            yield method, prefix + path


def test_every_auth_prefixed_route_self_enforces(app_client: TestClient) -> None:
    _seed_password()

    seen: list[tuple[str, str]] = []
    for method, path in _iter_leaf_routes(app_client.app.routes):
        if not path.startswith("/api/v1/auth/"):
            continue
        if method in {"HEAD", "OPTIONS"}:
            continue
        seen.append((method, path))
        if (method, path) in _PUBLIC_AUTH_ROUTES:
            continue
        resp = app_client.request(method, path)
        assert resp.status_code in (401, 403), (
            f"{method} {path} is reachable without credentials — every "
            f"/api/v1/auth/* route must self-enforce (middleware skips this prefix)"
        )

    # Sanity: the walk actually found the auth surface (guards against a
    # traversal regression silently asserting nothing).
    assert ("POST", "/api/v1/auth/sign-out-all") in seen
    assert ("POST", "/api/v1/auth/chatgpt/start") in seen


class TestChatgptOauthRequiresAuth:
    def test_disconnect_requires_auth_when_password_set(self, isolated_config: Path, api_client_factory) -> None:
        _seed_password()
        client = api_client_factory(create_app())
        resp = client.post("/api/v1/auth/chatgpt/disconnect")
        assert_problem(resp, 401)

    def test_start_requires_auth_when_password_set(self, isolated_config: Path, api_client_factory) -> None:
        _seed_password()
        client = api_client_factory(create_app())
        resp = client.post("/api/v1/auth/chatgpt/start")
        assert_problem(resp, 401)

    def test_status_requires_auth_when_password_set(self, isolated_config: Path, api_client_factory) -> None:
        _seed_password()
        client = api_client_factory(create_app())
        resp = client.get("/api/v1/auth/chatgpt/status")
        assert_problem(resp, 401)

    def test_valid_cookie_allows_disconnect(
        self, isolated_config: Path, monkeypatch: pytest.MonkeyPatch, api_client_factory
    ) -> None:
        from src.finance import chatgpt_oauth as chatgpt_oauth_module

        monkeypatch.setattr(chatgpt_oauth_module, "disconnect", lambda: None)
        _seed_password()
        secret = app_config.get_session_signing_secret()
        version = int(app_config.get_config().get("session_version", 0) or 0)
        cookie = issue_session(version=version, secret=secret)
        client = api_client_factory(create_app())
        client.cookies.set(COOKIE_NAME, cookie)
        resp = client.post("/api/v1/auth/chatgpt/disconnect")
        assert_ok(resp)
        assert resp.json() == {"ok": True}

    def test_tofu_mode_allows_start(
        self, isolated_config: Path, monkeypatch: pytest.MonkeyPatch, api_client_factory
    ) -> None:
        """No password set → TOFU allows, consistent with the rest of the API."""
        from src.finance import chatgpt_oauth as chatgpt_oauth_module

        monkeypatch.setattr(
            chatgpt_oauth_module,
            "start_login",
            lambda: {"verification_url": "https://auth.example/device", "user_code": "ABCD-12345"},
        )
        client = api_client_factory(create_app())
        resp = client.post("/api/v1/auth/chatgpt/start")
        assert_ok(resp)
        assert resp.json()["user_code"] == "ABCD-12345"

    def test_login_stays_reachable_without_auth(self, isolated_config: Path, api_client_factory) -> None:
        """The bootstrap endpoints must keep working without credentials."""
        _seed_password("hunter2-but-longer")
        client = api_client_factory(create_app())
        resp = client.post("/api/v1/auth/login", json={"password": "wrong"})
        # Reachable (handler ran and rejected the password) — not a middleware 401 shape.
        assert resp.status_code in (401, 403)
