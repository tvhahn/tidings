"""Connect ChatGPT via the Codex CLI's device-code login.

Earlier versions reimplemented OAuth+PKCE against the Codex public client
(`app_EMoamEEZ73f0CkXaXp7hrann`). That never worked end-to-end: the
authorize server rejects every redirect_uri except the CLI's own
localhost:1455 callback, and the subscription backend only serves the
Responses API. Rather than chase OpenAI's private protocol, this module
delegates to the official CLI:

- `codex login --device-auth` — the user opens a URL and types a one-time
  code; the CLI polls and writes `$CODEX_HOME/auth.json` on success.
- `codex logout` — removes the stored credentials.
- `$CODEX_HOME/auth.json` (default `~/.codex/auth.json`) — source of truth
  for connection state; its `tokens.id_token` JWT carries the account email.

The same login powers the codex summaries provider and `codex exec`
categorization (`src/finance/ai_client.py`).
"""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import threading
from pathlib import Path
from typing import IO, TypedDict

logger = logging.getLogger(__name__)

# Legacy token file from the abandoned in-app OAuth flow — removed on disconnect.
_LEGACY_TOKEN_PATH = Path("data/chatgpt_oauth.json")

_LOGIN_START_TIMEOUT_SECONDS = 20.0
_LOGOUT_TIMEOUT_SECONDS = 10.0

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_URL_RE = re.compile(r"https://\S+")
_USER_CODE_RE = re.compile(r"\b[A-Z0-9]{3,8}-[A-Z0-9]{3,8}\b")


class LoginStart(TypedDict):
    verification_url: str
    user_code: str


class LoginStatus(TypedDict):
    connected: bool
    pending: bool
    email: str | None
    error: str | None
    verification_url: str | None
    user_code: str | None


class _LoginSession:
    """One in-flight `codex login --device-auth` subprocess and its parsed output."""

    def __init__(self, process: subprocess.Popen[str]) -> None:
        self.process = process
        self.lines: list[str] = []
        self.verification_url: str | None = None
        self.user_code: str | None = None
        self.ready = threading.Event()

    def is_pending(self) -> bool:
        return self.process.poll() is None

    def output_tail(self, n: int = 5) -> str:
        return " / ".join(line for line in self.lines[-n:] if line)


_session: _LoginSession | None = None
_lock = threading.Lock()


def _codex_home() -> Path:
    home = os.environ.get("CODEX_HOME")
    return Path(home) if home else Path.home() / ".codex"


def auth_json_path() -> Path:
    """Where the Codex CLI persists credentials."""
    return _codex_home() / "auth.json"


def _kill_login(process: subprocess.Popen[str]) -> None:
    """Kill the login and its children.

    The npm `codex` entry point is a Node shim that *spawns* the Rust binary —
    killing only the shim orphans the real process, which keeps polling OpenAI
    until the code expires. The login runs in its own session (process group),
    so killing the group reaches both.
    """
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (AttributeError, ProcessLookupError, PermissionError, OSError):
        process.kill()
    process.wait()


def _read_reader(session: _LoginSession, stdout: IO[str]) -> None:
    """Background thread: scan CLI output for the verification URL and code."""
    try:
        for raw in stdout:
            line = _ANSI_RE.sub("", raw).strip()
            session.lines.append(line)
            if session.verification_url is None:
                url = _URL_RE.search(line)
                if url:
                    session.verification_url = url.group(0)
            if session.user_code is None:
                code = _USER_CODE_RE.search(line)
                if code:
                    session.user_code = code.group(0)
            if session.verification_url and session.user_code:
                session.ready.set()
    except Exception:
        logger.exception("Error reading codex login output")
    finally:
        # EOF — the process finished (success, expiry, or failure). Unblock
        # any waiter so start_login can report instead of timing out.
        session.process.wait()
        session.ready.set()


def start_login() -> LoginStart:
    """Spawn `codex login --device-auth` and return the URL + one-time code.

    The subprocess keeps polling OpenAI in the background; completion shows
    up via `login_status()` once the CLI writes auth.json. Starting a new
    login cancels any previous pending one (each attempt gets a fresh code).
    """
    global _session
    codex_bin = shutil.which("codex")
    if codex_bin is None:
        raise RuntimeError("OpenAI Codex CLI not found — install it with `npm install -g @openai/codex`")

    with _lock:
        if _session is not None and _session.is_pending():
            _kill_login(_session.process)

        process = subprocess.Popen(  # noqa: S603 — static list argv, no shell; codex_bin via shutil.which
            [codex_bin, "login", "--device-auth"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        session = _LoginSession(process)
        assert process.stdout is not None  # noqa: S101 — type-narrowing; Popen(stdout=PIPE) guarantees .stdout
        threading.Thread(target=_read_reader, args=(session, process.stdout), daemon=True).start()
        _session = session

    session.ready.wait(timeout=_LOGIN_START_TIMEOUT_SECONDS)
    if session.verification_url and session.user_code:
        return {"verification_url": session.verification_url, "user_code": session.user_code}

    _kill_login(process)
    detail = session.output_tail() or "no output from codex login"
    raise RuntimeError(f"Could not start the ChatGPT sign-in: {detail}")


def login_status() -> LoginStatus:
    """Report the connection state plus any in-flight device login."""
    connected = is_connected()
    session = _session
    pending = bool(session and session.is_pending()) and not connected
    error: str | None = None
    if session is not None and not session.is_pending() and not connected and session.process.returncode != 0:
        error = session.output_tail() or "codex login failed"
    return {
        "connected": connected,
        "pending": pending,
        "email": get_account_email() if connected else None,
        "error": error,
        "verification_url": session.verification_url if pending and session else None,
        "user_code": session.user_code if pending and session else None,
    }


def disconnect() -> None:
    """Cancel any pending login and remove stored Codex credentials."""
    global _session
    with _lock:
        if _session is not None and _session.is_pending():
            _kill_login(_session.process)
        _session = None

    codex_bin = shutil.which("codex")
    if codex_bin is not None:
        try:
            subprocess.run(  # noqa: S603 — static list argv, no shell; codex_bin via shutil.which
                [codex_bin, "logout"],
                capture_output=True,
                timeout=_LOGOUT_TIMEOUT_SECONDS,
                check=False,
            )
        except Exception:
            logger.exception("codex logout failed; removing auth file directly")
    # Belt-and-suspenders: make sure the credentials are actually gone.
    with contextlib.suppress(FileNotFoundError):
        auth_json_path().unlink()
    with contextlib.suppress(FileNotFoundError):
        _LEGACY_TOKEN_PATH.unlink()


def is_connected() -> bool:
    """True when the Codex CLI holds a ChatGPT login (not an API-key login)."""
    return _read_id_token() is not None


def get_account_email() -> str | None:
    """Decode the auth.json id_token JWT payload to extract the user's email.

    No signature check — the file was written by the Codex CLI's own
    token exchange on this machine.
    """
    id_token = _read_id_token()
    if not id_token:
        return None
    try:
        _, payload_b64, _ = id_token.split(".")
        # base64url with no padding — re-pad before decoding.
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        email = payload.get("email")
        return email if isinstance(email, str) else None
    except Exception:
        logger.exception("Failed to decode id_token for email")
        return None


def _read_id_token() -> str | None:
    path = auth_json_path()
    if not path.exists():
        return None
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        logger.exception("Failed to read Codex auth file")
        return None
    tokens = data.get("tokens") or {}
    id_token = tokens.get("id_token")
    return id_token if isinstance(id_token, str) and id_token else None


def _reset_for_tests() -> None:  # pyright: ignore[reportUnusedFunction] — test-only hook (tests/unit/test_chatgpt_oauth.py); pyright can't see tests/
    """Test-only: wipe in-memory state."""
    global _session
    _session = None
