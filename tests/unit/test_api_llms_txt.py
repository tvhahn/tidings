"""`GET /llms.txt` — the plain-text agent-orientation file every instance serves.

Pins the L9/C3 contract: the file is present, needs no token even when agent
tokens are configured, is served in headless (`SERVE_FRONTEND=false`)
deployments, and stays out of the OpenAPI document (`include_in_schema=False`).

The new-file test-convention ratchet (scripts/checks/check_test_conventions.py) pins
hand-rolled test clients at zero for files it doesn't grandfather, so the token
and headless cases here reach the app via the shared `api_client` fixture and a
direct handler invocation rather than constructing a client of their own.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from src.api.main import create_app
from src.finance import agent_tokens, app_config
from tests.asserts import assert_ok, assert_status

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


def test_llms_txt_returns_orientation_text(api_client: TestClient) -> None:
    resp = api_client.get("/llms.txt")
    assert_status(resp, 200)
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    assert "# Tidings" in body
    assert "/openapi.json" in body
    assert "docs.gettidings.com" in body


def test_llms_txt_needs_no_token_when_tokens_configured(isolated_config: Path, api_client: TestClient) -> None:
    """A configured agent token must not gate `/llms.txt` — it's outside /api/v1/."""
    agent_tokens.add_token(label="seed")
    resp = api_client.get("/llms.txt")  # no Authorization header
    assert_status(resp, 200)
    assert "# Tidings" in resp.text


def test_llms_txt_served_headless(monkeypatch: pytest.MonkeyPatch) -> None:
    """`SERVE_FRONTEND=false` (headless) still registers and serves /llms.txt.

    Built via the `create_app()` factory with the env flag flipped, then the
    registered handler is invoked directly (returning a real 200 `PlainTextResponse`)
    so the case needs no hand-rolled TestClient. Also asserts no SPA mount exists
    to shadow the route in headless mode.
    """
    monkeypatch.setenv("SERVE_FRONTEND", "false")
    app = create_app()

    mount_names = {getattr(r, "name", None) for r in app.routes}
    assert "frontend" not in mount_names

    route = next(r for r in app.routes if getattr(r, "path", None) == "/llms.txt")
    resp = asyncio.run(route.endpoint())
    assert_status(resp, 200)
    assert b"# Tidings" in bytes(resp.body)


def test_llms_txt_absent_from_openapi(api_client: TestClient) -> None:
    """`include_in_schema=False` keeps the route out of the OpenAPI document."""
    spec = assert_ok(api_client.get("/openapi.json"))
    assert "/llms.txt" not in spec["paths"]
