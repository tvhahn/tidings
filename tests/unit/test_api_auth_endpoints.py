"""Tests for the /api/v1/auth/* endpoints (Phase 4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from src.api.main import create_app
from src.finance import app_config
from src.finance.auth_session import COOKIE_NAME, hash_password
from tests.asserts import assert_ok, assert_problem

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from fastapi.testclient import TestClient


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(app_config, "_CONFIG_PATH", cfg_path)
    app_config.invalidate_config_cache()
    yield cfg_path
    app_config.invalidate_config_cache()


@pytest.fixture
def client(isolated_config: Path, api_client_factory) -> TestClient:
    # Fresh app per test so create_app() re-reads the isolated config; built via
    # the sanctioned api_client_factory fixture (tests/conftest.py).
    return api_client_factory(create_app())


class TestSetPasswordTofu:
    def test_first_password_omits_current_password(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/auth/set-password",
            json={"password": "correct-horse-battery-staple"},
        )
        assert_ok(resp)
        assert resp.json()["status"] == "ok"
        # Cookie set on the response.
        assert COOKIE_NAME in resp.cookies
        # app_password_hash is now persisted.
        assert app_config.get_config().get("app_password_hash") is not None

    def test_first_password_bumps_session_version(self, client: TestClient) -> None:
        client.post(
            "/api/v1/auth/set-password",
            json={"password": "correct-horse-battery-staple"},
        )
        # Initial version was 0; after set-password it's at least 1.
        assert int(app_config.get_config().get("session_version", 0) or 0) >= 1

    def test_caller_session_persists_across_requests(self, client: TestClient) -> None:
        client.post(
            "/api/v1/auth/set-password",
            json={"password": "correct-horse-battery-staple"},
        )
        # The cookie set in the response is now on `client` thanks to
        # TestClient's cookie jar — subsequent gets should succeed.
        resp = client.get("/api/v1/categories")
        assert_ok(resp)

    def test_short_password_rejected(self, client: TestClient) -> None:
        resp = client.post("/api/v1/auth/set-password", json={"password": "short"})
        assert_problem(resp, 422)  # pydantic min_length


class TestSetPasswordAuthenticated:
    def test_change_requires_current_password(
        self,
        isolated_config: Path,
        client: TestClient,
    ) -> None:
        # Pre-seed a password hash directly to skip TOFU.
        app_config.update_config({"app_password_hash": hash_password("old-password")})
        resp = client.post(
            "/api/v1/auth/set-password",
            json={"password": "new-correct-password"},
        )
        assert_problem(resp, 401, "UNAUTHORIZED")

    def test_change_with_wrong_current_password(
        self,
        isolated_config: Path,
        client: TestClient,
    ) -> None:
        app_config.update_config({"app_password_hash": hash_password("old-password")})
        resp = client.post(
            "/api/v1/auth/set-password",
            json={"password": "new-correct-password", "current_password": "wrong"},
        )
        assert_problem(resp, 401)

    def test_change_with_correct_current_password_succeeds(
        self,
        isolated_config: Path,
        client: TestClient,
    ) -> None:
        app_config.update_config({"app_password_hash": hash_password("old-password")})
        before_version = int(app_config.get_config().get("session_version", 0) or 0)
        resp = client.post(
            "/api/v1/auth/set-password",
            json={
                "password": "new-correct-password",
                "current_password": "old-password",
            },
        )
        assert_ok(resp)
        # Version bumped → all old cookies (if any existed) are invalidated.
        after_version = int(app_config.get_config().get("session_version", 0) or 0)
        assert after_version == before_version + 1


class TestLogin:
    def test_login_with_correct_password_sets_cookie(
        self,
        isolated_config: Path,
        client: TestClient,
    ) -> None:
        app_config.update_config({"app_password_hash": hash_password("right")})
        resp = client.post("/api/v1/auth/login", json={"password": "right"})
        assert_ok(resp)
        assert COOKIE_NAME in resp.cookies

    def test_login_with_wrong_password_returns_401(
        self,
        isolated_config: Path,
        client: TestClient,
    ) -> None:
        app_config.update_config({"app_password_hash": hash_password("right")})
        resp = client.post("/api/v1/auth/login", json={"password": "wrong"})
        assert_problem(resp, 401, "UNAUTHORIZED")

    def test_login_when_no_password_set_returns_401(self, client: TestClient) -> None:
        # Before any password is set, login is meaningless.
        resp = client.post("/api/v1/auth/login", json={"password": "anything"})
        assert_problem(resp, 401)


class TestLogout:
    def test_logout_clears_cookie(self, client: TestClient) -> None:
        # Establish a session via set-password (TOFU).
        client.post(
            "/api/v1/auth/set-password",
            json={"password": "correct-horse-battery-staple"},
        )
        resp = client.post("/api/v1/auth/logout")
        assert_ok(resp)
        # Subsequent gets after logout AND password set must 401 (no TOFU).
        client.cookies.clear()
        resp2 = client.get("/api/v1/categories")
        assert_problem(resp2, 401)


class TestSignOutAll:
    def test_sign_out_all_bumps_version(self, client: TestClient) -> None:
        client.post(
            "/api/v1/auth/set-password",
            json={"password": "correct-horse-battery-staple"},
        )
        before = int(app_config.get_config().get("session_version", 0) or 0)
        resp = client.post("/api/v1/auth/sign-out-all")
        assert_ok(resp)
        after = int(app_config.get_config().get("session_version", 0) or 0)
        assert after == before + 1

    def test_caller_stays_signed_in_after_sign_out_all(self, client: TestClient) -> None:
        """The caller's cookie is rotated in the same response — they stay in."""
        client.post(
            "/api/v1/auth/set-password",
            json={"password": "correct-horse-battery-staple"},
        )
        client.post("/api/v1/auth/sign-out-all")
        # The response set a fresh cookie that's now in the jar.
        resp = client.get("/api/v1/categories")
        assert_ok(resp)

    def test_password_set_no_cookie_no_body_rejected(
        self,
        isolated_config: Path,
        client: TestClient,
    ) -> None:
        """Password set, no session cookie, no body → 401 (self-enforced)."""
        app_config.update_config({"app_password_hash": hash_password("old-password")})
        resp = client.post("/api/v1/auth/sign-out-all")
        assert_problem(resp, 401, "UNAUTHORIZED")

    def test_password_set_wrong_current_password_rejected(
        self,
        isolated_config: Path,
        client: TestClient,
    ) -> None:
        app_config.update_config({"app_password_hash": hash_password("old-password")})
        resp = client.post(
            "/api/v1/auth/sign-out-all",
            json={"current_password": "wrong"},
        )
        assert_problem(resp, 401, "UNAUTHORIZED")

    def test_correct_password_invalidates_old_cookie_and_rotates(
        self,
        isolated_config: Path,
        client: TestClient,
    ) -> None:
        app_config.update_config({"app_password_hash": hash_password("old-password")})
        # Establish a session, then capture and drop its cookie so the
        # sign-out-all call is authenticated purely by the password path.
        client.post("/api/v1/auth/login", json={"password": "old-password"})
        old_cookie = client.cookies.get(COOKIE_NAME)
        assert old_cookie is not None
        client.cookies.clear()

        resp = client.post(
            "/api/v1/auth/sign-out-all",
            json={"current_password": "old-password"},
        )
        assert_ok(resp)
        # A fresh cookie is issued in the same response.
        assert COOKIE_NAME in resp.cookies
        # The rotated cookie (now in the jar) is accepted by the middleware.
        assert_ok(client.get("/api/v1/categories"))
        # The pre-bump cookie is now stale → rejected.
        client.cookies.clear()
        client.cookies.set(COOKIE_NAME, old_cookie)
        assert_problem(client.get("/api/v1/categories"), 401)

    def test_valid_cookie_no_body_allowed(
        self,
        isolated_config: Path,
        client: TestClient,
    ) -> None:
        app_config.update_config({"app_password_hash": hash_password("old-password")})
        # A valid session cookie proves the operator — no body needed.
        client.post("/api/v1/auth/login", json={"password": "old-password"})
        resp = client.post("/api/v1/auth/sign-out-all")
        assert_ok(resp)

    def test_tofu_no_hash_allowed(self, client: TestClient) -> None:
        """No password set → sign-out-all allows through (bootstrap behavior)."""
        resp = client.post("/api/v1/auth/sign-out-all")
        assert_ok(resp)


class TestHealthAuthRequired:
    def test_health_reports_false_in_tofu(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health")
        assert_ok(resp)
        assert resp.json()["auth_required"] is False

    def test_health_reports_true_after_password_set(
        self,
        isolated_config: Path,
        client: TestClient,
    ) -> None:
        app_config.update_config({"app_password_hash": hash_password("x" * 8)})
        resp = client.get("/api/v1/health")
        assert_ok(resp)
        assert resp.json()["auth_required"] is True
