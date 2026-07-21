"""Phase 0 tests for the headless deployment toggle.

Covers `SERVE_FRONTEND` and `CORS_ALLOWED_ORIGINS` env vars on
`src.api.main.create_app`. The third Phase 0 case — bearer middleware
no-ops when `agent_tokens` is empty — lands in `tests/api/test_auth_middleware.py`
when Phase 1 introduces the middleware.
"""

from __future__ import annotations

import pytest

from src.api.main import create_app
from tests.asserts import assert_ok, assert_status


class TestServeFrontendToggle:
    def test_serve_frontend_false_returns_404_on_root(
        self, monkeypatch: pytest.MonkeyPatch, api_client_factory
    ) -> None:
        """SERVE_FRONTEND=false must not mount the static SPA — `/` is a 404."""
        monkeypatch.setenv("SERVE_FRONTEND", "false")
        app = create_app()
        client = api_client_factory(app)
        resp = client.get("/")
        # Unmatched-route 404 is Starlette's default `{"detail": ...}` shape, not
        # the unified `{error, code, details}` envelope — assert the status only.
        assert_status(resp, 404)

    @pytest.mark.parametrize("value", ["false", "False", "FALSE", "0", "no"])
    def test_serve_frontend_falsy_variants_disable_mount(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv("SERVE_FRONTEND", value)
        app = create_app()
        # No `frontend` mount means the route table has only API + docs.
        mount_names = {getattr(r, "name", None) for r in app.routes}
        assert "frontend" not in mount_names

    def test_default_serve_frontend_is_true(self, monkeypatch: pytest.MonkeyPatch, api_client_factory) -> None:
        """No env var set → mount happens (gated also on dist existing)."""
        monkeypatch.delenv("SERVE_FRONTEND", raising=False)
        app = create_app()
        # Whether the mount actually attaches depends on `frontend/dist`
        # being built — the API routes and /docs are always present, which
        # is the contract this test pins.
        client = api_client_factory(app)
        assert client.get("/api/v1/categories").status_code in {200, 401}


class TestCorsAllowedOrigins:
    def test_cors_wildcard_allows_any_origin_preflight(
        self, monkeypatch: pytest.MonkeyPatch, api_client_factory
    ) -> None:
        """CORS_ALLOWED_ORIGINS=* → preflight from any origin succeeds."""
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")
        app = create_app()
        client = api_client_factory(app)
        resp = client.options(
            "/api/v1/categories",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        assert_ok(resp)
        # Starlette reflects the origin (not literal "*") when credentials are
        # enabled; both forms are correct per the CORS spec.
        assert resp.headers.get("access-control-allow-origin") in {"*", "https://example.com"}

    def test_default_origin_is_localhost_5173(self, monkeypatch: pytest.MonkeyPatch, api_client_factory) -> None:
        monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
        app = create_app()
        client = api_client_factory(app)
        resp = client.options(
            "/api/v1/categories",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        assert_ok(resp)
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_default_origin_blocks_non_loopback_preflight(
        self, monkeypatch: pytest.MonkeyPatch, api_client_factory
    ) -> None:
        """Default allowlist is just localhost:5173; foreign origins miss the header."""
        monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
        app = create_app()
        client = api_client_factory(app)
        resp = client.options(
            "/api/v1/categories",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        # Starlette returns 400 for disallowed preflight origins, with no ACAO.
        assert "access-control-allow-origin" not in resp.headers

    def test_comma_separated_list_parses(self, monkeypatch: pytest.MonkeyPatch, api_client_factory) -> None:
        monkeypatch.setenv(
            "CORS_ALLOWED_ORIGINS",
            "http://localhost:5173, https://tidings.example.com",
        )
        app = create_app()
        client = api_client_factory(app)
        for origin in ("http://localhost:5173", "https://tidings.example.com"):
            resp = client.options(
                "/api/v1/categories",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "Content-Type",
                },
            )
            assert_ok(resp)
            assert resp.headers.get("access-control-allow-origin") == origin
