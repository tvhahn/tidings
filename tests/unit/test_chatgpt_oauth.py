"""Tests for the Codex CLI device-auth wrapper (src/finance/chatgpt_oauth.py)."""

from __future__ import annotations

import base64
import io
import json
import subprocess
import time
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

from src.finance import chatgpt_oauth

if TYPE_CHECKING:
    from pathlib import Path

# Real shape of `codex login --device-auth` output, ANSI colors included.
DEVICE_AUTH_OUTPUT = (
    "Welcome to Codex [v\x1b[90m0.139.0\x1b[0m]\n"
    "\x1b[90mOpenAI's command-line coding agent\x1b[0m\n"
    "\n"
    "Follow these steps to sign in with ChatGPT using device code authorization:\n"
    "\n"
    "1. Open this link in your browser and sign in to your account\n"
    "   \x1b[94mhttps://auth.openai.com/codex/device\x1b[0m\n"
    "\n"
    "2. Enter this one-time code \x1b[90m(expires in 15 minutes)\x1b[0m\n"
    "   \x1b[94mGCCN-QR5SB\x1b[0m\n"
    "\n"
    "\x1b[90mDevice codes are a common phishing target. Never share this code.\x1b[0m\n"
)


class FakeProcess:
    """Stand-in for the `codex login --device-auth` subprocess."""

    def __init__(self, output: str = DEVICE_AUTH_OUTPUT, exits_with: int | None = None) -> None:
        self.stdout = io.StringIO(output)
        self.returncode: int | None = exits_with
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None and self.killed:
            self.returncode = -9
        return self.returncode if self.returncode is not None else 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def _make_jwt(payload: dict[str, Any]) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"header.{body}.signature"


def _write_auth_json(codex_home: Path, email: str | None = "user@example.com") -> None:
    codex_home.mkdir(parents=True, exist_ok=True)
    tokens: dict[str, Any] = {"access_token": "at", "refresh_token": "rt", "account_id": "acct"}
    if email is not None:
        tokens["id_token"] = _make_jwt({"email": email})
    (codex_home / "auth.json").write_text(json.dumps({"openai_api_key": None, "tokens": tokens}))


@pytest.fixture(autouse=True)
def isolated_codex_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    chatgpt_oauth._reset_for_tests()
    yield
    chatgpt_oauth._reset_for_tests()


class TestStartLogin:
    @patch("src.finance.chatgpt_oauth.subprocess.Popen")
    @patch("src.finance.chatgpt_oauth.shutil.which", return_value="/usr/bin/codex")
    def test_parses_url_and_code_from_cli_output(self, _which, mock_popen) -> None:
        mock_popen.return_value = FakeProcess()
        result = chatgpt_oauth.start_login()
        assert result["verification_url"] == "https://auth.openai.com/codex/device"
        assert result["user_code"] == "GCCN-QR5SB"

    @patch("src.finance.chatgpt_oauth.shutil.which", return_value=None)
    def test_missing_cli_raises(self, _which) -> None:
        with pytest.raises(RuntimeError, match="Codex CLI not found"):
            chatgpt_oauth.start_login()

    @patch("src.finance.chatgpt_oauth.subprocess.Popen")
    @patch("src.finance.chatgpt_oauth.shutil.which", return_value="/usr/bin/codex")
    def test_immediate_cli_failure_raises_with_output(self, _which, mock_popen) -> None:
        mock_popen.return_value = FakeProcess(output="error: something exploded\n", exits_with=1)
        with pytest.raises(RuntimeError, match="something exploded"):
            chatgpt_oauth.start_login()

    @patch("src.finance.chatgpt_oauth.subprocess.Popen")
    @patch("src.finance.chatgpt_oauth.shutil.which", return_value="/usr/bin/codex")
    def test_new_login_kills_previous_pending_process(self, _which, mock_popen) -> None:
        first = FakeProcess()
        second = FakeProcess()
        mock_popen.side_effect = [first, second]
        chatgpt_oauth.start_login()
        chatgpt_oauth.start_login()
        assert first.killed


class TestLoginStatus:
    @patch("src.finance.chatgpt_oauth.subprocess.Popen")
    @patch("src.finance.chatgpt_oauth.shutil.which", return_value="/usr/bin/codex")
    def test_pending_surfaces_url_and_code(self, _which, mock_popen) -> None:
        mock_popen.return_value = FakeProcess()
        chatgpt_oauth.start_login()
        status = chatgpt_oauth.login_status()
        assert status["pending"] is True
        assert status["connected"] is False
        assert status["verification_url"] == "https://auth.openai.com/codex/device"
        assert status["user_code"] == "GCCN-QR5SB"
        assert status["error"] is None

    @patch("src.finance.chatgpt_oauth.subprocess.Popen")
    @patch("src.finance.chatgpt_oauth.shutil.which", return_value="/usr/bin/codex")
    def test_connected_after_cli_writes_auth_json(self, _which, mock_popen) -> None:
        process = FakeProcess()
        mock_popen.return_value = process
        chatgpt_oauth.start_login()
        # Simulate the CLI finishing: auth.json appears, process exits 0.
        _write_auth_json(chatgpt_oauth._codex_home())
        process.returncode = 0
        status = chatgpt_oauth.login_status()
        assert status["connected"] is True
        assert status["pending"] is False
        assert status["email"] == "user@example.com"
        assert status["error"] is None

    @patch("src.finance.chatgpt_oauth.subprocess.Popen")
    @patch("src.finance.chatgpt_oauth.shutil.which", return_value="/usr/bin/codex")
    def test_failed_login_reports_error(self, _which, mock_popen) -> None:
        process = FakeProcess()
        mock_popen.return_value = process
        chatgpt_oauth.start_login()
        # Give the reader thread a moment to drain stdout to EOF.
        time.sleep(0.05)
        process.returncode = 1
        status = chatgpt_oauth.login_status()
        assert status["connected"] is False
        assert status["pending"] is False
        assert status["error"] is not None

    def test_no_session_no_auth_file(self) -> None:
        status = chatgpt_oauth.login_status()
        assert status == {
            "connected": False,
            "pending": False,
            "email": None,
            "error": None,
            "verification_url": None,
            "user_code": None,
        }


class TestConnectionState:
    def test_is_connected_with_chatgpt_tokens(self) -> None:
        _write_auth_json(chatgpt_oauth._codex_home())
        assert chatgpt_oauth.is_connected() is True

    def test_api_key_only_login_is_not_connected(self) -> None:
        # `codex login --with-api-key` writes auth.json without an id_token.
        _write_auth_json(chatgpt_oauth._codex_home(), email=None)
        assert chatgpt_oauth.is_connected() is False

    def test_not_connected_without_auth_file(self) -> None:
        assert chatgpt_oauth.is_connected() is False

    def test_get_account_email(self) -> None:
        _write_auth_json(chatgpt_oauth._codex_home(), email="person@bank.ca")
        assert chatgpt_oauth.get_account_email() == "person@bank.ca"

    def test_malformed_auth_json_is_not_connected(self) -> None:
        home = chatgpt_oauth._codex_home()
        home.mkdir(parents=True, exist_ok=True)
        (home / "auth.json").write_text("not json{")
        assert chatgpt_oauth.is_connected() is False


class TestDisconnect:
    @patch("src.finance.chatgpt_oauth.subprocess.run")
    @patch("src.finance.chatgpt_oauth.shutil.which", return_value="/usr/bin/codex")
    def test_runs_codex_logout_and_removes_auth_file(self, _which, mock_run) -> None:
        _write_auth_json(chatgpt_oauth._codex_home())
        chatgpt_oauth.disconnect()
        assert mock_run.call_args[0][0][:2] == ["/usr/bin/codex", "logout"]
        assert not chatgpt_oauth.auth_json_path().exists()
        assert chatgpt_oauth.is_connected() is False

    @patch("src.finance.chatgpt_oauth.shutil.which", return_value=None)
    def test_removes_auth_file_even_without_cli(self, _which) -> None:
        _write_auth_json(chatgpt_oauth._codex_home())
        chatgpt_oauth.disconnect()
        assert not chatgpt_oauth.auth_json_path().exists()

    @patch("src.finance.chatgpt_oauth.subprocess.run")
    @patch("src.finance.chatgpt_oauth.subprocess.Popen")
    @patch("src.finance.chatgpt_oauth.shutil.which", return_value="/usr/bin/codex")
    def test_kills_pending_login(self, _which, mock_popen, _run) -> None:
        process = FakeProcess()
        mock_popen.return_value = process
        chatgpt_oauth.start_login()
        chatgpt_oauth.disconnect()
        assert process.killed
        assert chatgpt_oauth.login_status()["pending"] is False

    @patch("src.finance.chatgpt_oauth.subprocess.run", side_effect=subprocess.TimeoutExpired("codex", 10))
    @patch("src.finance.chatgpt_oauth.shutil.which", return_value="/usr/bin/codex")
    def test_logout_failure_still_removes_auth_file(self, _which, _run) -> None:
        _write_auth_json(chatgpt_oauth._codex_home())
        chatgpt_oauth.disconnect()
        assert not chatgpt_oauth.auth_json_path().exists()
