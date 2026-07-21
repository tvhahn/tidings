"""Unit tests for `_warn_if_auth_bypass_exposed` (audit T3, reduced scope).

Drives the warning helper directly — monkeypatching `sys.argv` for the bind
host and stubbing `get_config` for the bypass flag — rather than standing up
the full lifespan (the conftest documents why TestClient startup is avoided).
"""

import logging
import sys
from unittest.mock import patch

import pytest

from src.api.main import _warn_if_auth_bypass_exposed

_LOGGER = "src.api.main"
_EXPOSED_HOST = "0.0.0.0"  # noqa: S104 — the off-box bind we assert the warning fires for


def _invoke(monkeypatch: pytest.MonkeyPatch, argv: list[str], config: dict[str, object]) -> None:
    monkeypatch.setattr(sys, "argv", argv)
    with patch("src.finance.app_config.get_config", return_value=config):
        _warn_if_auth_bypass_exposed()


def test_warns_when_bypass_on_and_non_loopback(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        _invoke(monkeypatch, ["uvicorn", "--host", _EXPOSED_HOST], {"auth_bypass_for_dev": True})

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "auth_bypass_for_dev is ON" in msg
    assert _EXPOSED_HOST in msg


def test_warns_with_host_equals_form(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        _invoke(monkeypatch, ["uvicorn", f"--host={_EXPOSED_HOST}"], {"auth_bypass_for_dev": True})

    assert any("auth_bypass_for_dev is ON" in r.getMessage() for r in caplog.records)


def test_no_warning_on_loopback(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        _invoke(monkeypatch, ["uvicorn", "--host", "127.0.0.1"], {"auth_bypass_for_dev": True})

    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []


def test_no_warning_when_bypass_off(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        _invoke(monkeypatch, ["uvicorn", "--host", _EXPOSED_HOST], {"auth_bypass_for_dev": False})

    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []


def test_no_warning_when_host_absent(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """No `--host` flag → uvicorn binds loopback, so no exposure warning."""
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        _invoke(monkeypatch, ["uvicorn"], {"auth_bypass_for_dev": True})

    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []
