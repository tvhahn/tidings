"""Pure password-hashing + session-cookie helpers.

No FastAPI imports — also called from CLI (scripts/reset_password.py),
tests, and the auth router. The middleware in `src/api/auth.py` uses
`verify_session`; the auth router in `src/api/routers/auth.py` uses
`hash_password`/`verify_password`/`issue_session`.

Cookie format: `<base64url(payload)>.<base64url(hmac_sha256(payload, secret))>`
where `payload` is JSON `{v: int, iat: int, nonce: str}`. `v` is the
`app_config.session_version` at issue time — bumping it on
`/auth/sign-out-all` invalidates every existing cookie on the next
request without needing a server-side session table.
"""

from __future__ import annotations

import base64
import hmac
import json
import secrets
import time
from hashlib import sha256
from typing import TypedDict

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()
COOKIE_NAME = "tidings_session"
# 30 days. Sessions auto-renew with each /auth/login or /auth/set-password;
# the absolute lifetime here is the worst-case before a fresh login.
COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30


class SessionPayload(TypedDict):
    v: int  # session_version at issue time
    iat: int  # issued_at (unix seconds)
    nonce: str


def hash_password(plain: str) -> str:
    """Argon2id hash for storage. Returns the encoded string from argon2-cffi."""
    return _hasher.hash(plain)


def verify_password(hashed: str, plain: str) -> bool:
    """Constant-time argon2 verify. Returns False for mismatch or malformed hash."""
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _b64u_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64u_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def sign_session(payload: SessionPayload, secret: str) -> str:
    """Sign a session payload with HMAC-SHA256. Returns `<b64payload>.<b64sig>`."""
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64u_encode(payload_json)
    sig = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), sha256).digest()
    return f"{payload_b64}.{_b64u_encode(sig)}"


def verify_session(token: str, secret: str) -> SessionPayload | None:
    """Constant-time HMAC verify. Returns the payload or None if invalid or expired.

    Expiry is enforced server-side against ``iat`` — the cookie's Max-Age alone
    is browser-advisory, so a stolen token must not stay valid forever.
    """
    if not token or "." not in token:
        return None
    payload_b64, sig_b64 = token.split(".", 1)
    expected = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), sha256).digest()
    try:
        actual = _b64u_decode(sig_b64)
    except Exception:
        return None
    if not hmac.compare_digest(expected, actual):
        return None
    try:
        payload_json = _b64u_decode(payload_b64)
        payload_obj = json.loads(payload_json)
    except Exception:
        return None
    if not isinstance(payload_obj, dict):
        return None
    if {"v", "iat", "nonce"} - payload_obj.keys():
        return None
    if not isinstance(payload_obj["v"], int) or not isinstance(payload_obj["iat"], int):
        return None
    if not isinstance(payload_obj["nonce"], str):
        return None
    if payload_obj["iat"] + COOKIE_MAX_AGE_SECONDS < int(time.time()):
        return None
    return SessionPayload(v=payload_obj["v"], iat=payload_obj["iat"], nonce=payload_obj["nonce"])


def issue_session(*, version: int, secret: str) -> str:
    """Mint a fresh session token bound to `version`."""
    return sign_session(
        SessionPayload(v=version, iat=int(time.time()), nonce=secrets.token_hex(8)),
        secret,
    )
