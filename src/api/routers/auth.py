"""Cookie-session auth endpoints (Phase 4).

Four endpoints, all under `/api/v1/auth/*`. Public for middleware
purposes (each handler enforces its own rules).

- `POST /set-password` — TOFU mode (no current password set): omitted
  `current_password` is fine. Authenticated mode: requires correct
  `current_password`. Sets the new hash, bumps `session_version`,
  issues a fresh `tidings_session` cookie on the caller in the same
  response.
- `POST /login` — verifies the password; sets a cookie on success.
- `POST /logout` — clears the caller's cookie. Does NOT bump
  `session_version` (other devices stay signed in).
- `POST /sign-out-all` — bumps `session_version`, invalidating every
  existing cookie. The caller's cookie is rotated in the same response
  so they stay signed in here.

Cookie attributes: `httpOnly`, `SameSite=Strict`, `path=/`, `Max-Age=30d`.
`Secure` is conditional — auto-detected from the request scheme so
`http://localhost` dev stays usable while TLS-fronted production gets
`Secure=True`. Override via `AUTH_COOKIE_SECURE=true|false|auto`.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Final

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from src.api import dependencies
from src.api.errors import ApiException
from src.finance.app_config import get_config, get_session_signing_secret, update_config
from src.finance.auth_session import (
    COOKIE_MAX_AGE_SECONDS,
    COOKIE_NAME,
    hash_password,
    issue_session,
    verify_password,
    verify_session,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

router = APIRouter(prefix="/auth", tags=["webapp-auth"])


_COOKIE_SECURE_MODE: Final[str] = os.environ.get("AUTH_COOKIE_SECURE", "auto").strip().lower()


class _SetPasswordIn(BaseModel):
    password: str = Field(min_length=8)
    current_password: str | None = None


class _LoginIn(BaseModel):
    password: str = Field(min_length=1)


class _SignOutAllIn(BaseModel):
    current_password: str | None = None


class _AuthResponse(BaseModel):
    status: str


def _has_valid_session(request: Request, cfg: Mapping[str, Any]) -> bool:
    """True when the caller presents an HMAC-valid, current-version cookie."""
    cookie_value = request.cookies.get(COOKIE_NAME)
    if not cookie_value:
        return False
    secret = cfg.get("session_signing_secret") or ""
    version = int(cfg.get("session_version", 0) or 0)
    payload = verify_session(cookie_value, secret)
    return payload is not None and payload["v"] == version


def _is_secure_request(request: Request) -> bool:
    """Decide the `Secure` cookie flag.

    `AUTH_COOKIE_SECURE=true|false` forces; `auto` (default) trusts the
    request scheme, falling back to `X-Forwarded-Proto` when behind a
    reverse proxy.
    """
    if _COOKIE_SECURE_MODE == "true":
        return True
    if _COOKIE_SECURE_MODE == "false":
        return False
    forwarded = request.headers.get("x-forwarded-proto", "").lower()
    if forwarded:
        return forwarded == "https"
    return request.url.scheme == "https"


def _set_session_cookie(request: Request, response: Response, *, version: int) -> None:
    secret = get_session_signing_secret()
    token = issue_session(version=version, secret=secret)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=_is_secure_request(request),
        samesite="strict",
        path="/",
        max_age=COOKIE_MAX_AGE_SECONDS,
    )


@router.post(
    "/set-password",
    response_model=_AuthResponse,
    operation_id="setAppPassword",
    summary="Set or change the webapp password (TOFU on first set)",
)
async def set_password(body: _SetPasswordIn, request: Request, response: Response) -> _AuthResponse:
    cfg = get_config()
    current_hash = cfg.get("app_password_hash")

    # Authenticated mode (current_hash present): the caller MUST prove
    # they know the existing password. /auth/* is middleware-public for
    # TOFU bootstrap, so the handler does the auth check itself.
    if current_hash is not None and (
        not body.current_password
        or not await dependencies.run_sync(verify_password, current_hash, body.current_password)
    ):
        raise ApiException(401, "UNAUTHORIZED", "current password is required and must match")

    new_hash = await dependencies.run_sync(hash_password, body.password)
    new_version = int(cfg.get("session_version", 0) or 0) + 1
    try:
        update_config({"app_password_hash": new_hash, "session_version": new_version})
    except OSError as e:
        raise ApiException(500, "CONFIG_WRITE_FAILED", "could not write data/config.json") from e
    _set_session_cookie(request, response, version=new_version)
    return _AuthResponse(status="ok")


@router.post(
    "/login",
    response_model=_AuthResponse,
    operation_id="webappLogin",
    summary="Issue a webapp session cookie",
)
async def login(body: _LoginIn, request: Request, response: Response) -> _AuthResponse:
    cfg = get_config()
    stored_hash = cfg.get("app_password_hash")
    if stored_hash is None:
        raise ApiException(401, "UNAUTHORIZED", "invalid password")
    if not await dependencies.run_sync(verify_password, stored_hash, body.password):
        raise ApiException(401, "UNAUTHORIZED", "invalid password")
    version = int(cfg.get("session_version", 0) or 0)
    _set_session_cookie(request, response, version=version)
    return _AuthResponse(status="ok")


@router.post(
    "/logout",
    response_model=_AuthResponse,
    operation_id="webappLogout",
    summary="Clear the caller's webapp session cookie",
)
async def logout(response: Response) -> _AuthResponse:
    response.delete_cookie(COOKIE_NAME, path="/")
    return _AuthResponse(status="ok")


@router.post(
    "/sign-out-all",
    response_model=_AuthResponse,
    operation_id="webappSignOutAll",
    summary="Bump session_version, invalidating all existing cookies",
)
async def sign_out_all(
    request: Request,
    response: Response,
    body: _SignOutAllIn | None = None,
) -> _AuthResponse:
    cfg = get_config()
    current_hash = cfg.get("app_password_hash")

    # Self-enforced auth (the /auth/* prefix bypasses the middleware): a
    # valid session cookie or the current password proves the caller is the
    # operator. TOFU mode (no password yet) allows through, matching
    # set-password above.
    if current_hash is not None and not _has_valid_session(request, cfg):
        provided = body.current_password if body else None
        if not provided or not await dependencies.run_sync(verify_password, current_hash, provided):
            raise ApiException(401, "UNAUTHORIZED", "a valid session or the current password is required")

    new_version = int(cfg.get("session_version", 0) or 0) + 1
    try:
        update_config({"session_version": new_version})
    except OSError as e:
        raise ApiException(500, "CONFIG_WRITE_FAILED", "could not write data/config.json") from e
    _set_session_cookie(request, response, version=new_version)
    return _AuthResponse(status="ok")
