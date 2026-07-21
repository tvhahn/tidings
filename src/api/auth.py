"""Bearer-auth middleware + per-scope path allowlist.

Auth contract — three parallel channels:
1. `Authorization: Bearer fin_…` — agents (Phase 1). Token must match a
   record in `agent_tokens` and be scope-permitted for (method, path).
2. `tidings_session` cookie — browsers (Phase 4). Cookie must be HMAC-
   valid against `app_config.session_signing_secret` AND its embedded
   `session_version` must match the current value in app_config.
3. TOFU mode (Phase 4) — when `app_password_hash` is null, the middleware
   allows unauthenticated access to `/api/v1/*` and the SPA shows a
   yellow SetupBanner nagging the operator to set a password.

Plus one explicit dev escape hatch: `auth_bypass_for_dev`. When the
operator flips that config flag (Settings → Password), the middleware
short-circuits the cookie/no-credential branch entirely so an agent
driving a Chromium DevTools session can hit `/api/v1/*` without a
cookie. Bearer-token scope enforcement is unaffected.

Priority (per Phase 4 spec): public paths → bearer → dev-bypass →
cookie → TOFU → 401. Bearer takes priority over cookie so an agent
that mistakenly picks up a stray browser cookie still gets
agent-shaped enforcement.

CORS preflight (OPTIONS) and `PUBLIC_PATHS` (health, docs, openapi.json,
/api/v1/auth/*) always bypass auth. Error responses match the unified
`{error, code, details}` shape from `src/api/errors.py`.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

# Request stays a runtime import: FastAPI resolves the annotation on the
# `require_request_auth` dependency via get_type_hints at include time.
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from src.api.activity import capture_activity, fire_and_forget
from src.finance.agent_tokens import find_token_by_raw, mark_used
from src.finance.app_config import get_config
from src.finance.auth_session import COOKIE_NAME, verify_session

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastapi import Response

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Principal:
    """The resolved caller identity for one request.

    Attached to ``request.state.principal`` by ``bearer_auth_middleware`` after a
    successful auth channel so downstream handlers (whoami, the activity ledger)
    can attribute the request. ``token_id``/``label``/``scope`` are populated only
    for ``kind == "token"``.
    """

    kind: Literal["token", "session", "tofu", "dev-bypass"]
    token_id: str | None = None  # kind == "token" only
    label: str | None = None
    scope: str | None = None


# Endpoints reachable without a token. /health is the liveness probe;
# /docs + /redoc + /openapi.json are the discovery surfaces a fresh
# agent reads to learn the schema before issuing a token.
PUBLIC_PATHS: Final[frozenset[str]] = frozenset(
    {
        "/health",
        "/api/v1/health",
        "/docs",
        "/redoc",
        "/openapi.json",
    }
)

# Endpoints that must remain reachable for auth bootstrap itself —
# /auth/login, /auth/set-password, /auth/logout, /auth/sign-out-all.
# Each handler enforces its own rules (set-password gates on TOFU vs.
# current_password; login verifies the password directly).
_AUTH_ROUTE_PREFIX = "/api/v1/auth/"


# (method, path-regex) per scope. `*` for method matches any method.
# `read` is a strict-read contract: GET-only on the API surface.
# `read+write` is the day-to-day workhorse for headless deployments.
# Future scopes are a one-line addition here.
SCOPE_ALLOWLISTS: Final[dict[str, tuple[tuple[str, re.Pattern[str]], ...]]] = {
    "read": (("GET", re.compile(r"^/api/v1/.*")),),
    "read+write": (("*", re.compile(r"^/api/v1/.*")),),
}


def scope_allows(scope: str, method: str, path: str) -> bool:
    """Whether a token with `scope` may call (method, path)."""
    for allowed_method, pattern in SCOPE_ALLOWLISTS.get(scope, ()):
        if allowed_method != "*" and allowed_method != method:
            continue
        if pattern.match(path):
            return True
    return False


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": message, "code": code, "details": None},
    )


def authenticate_request(
    request: Request,
) -> tuple[tuple[int, str, str] | None, Principal | None]:
    """Run the bearer → dev-bypass → cookie → TOFU channel checks.

    Returns ``(error, principal)``. ``error`` is ``None`` when the request may
    proceed (and ``principal`` is the resolved caller identity), else a
    ``(status_code, code, message)`` triple (and ``principal`` is ``None``).
    Shared by the middleware and by `require_request_auth` for handlers that live
    under the auth-bootstrap prefix but are not bootstrap endpoints themselves
    (e.g. the chatgpt OAuth trio).
    """
    # Channel 1: bearer (highest priority; agent-shaped enforcement).
    auth_header = request.headers.get("authorization", "")
    if auth_header:
        scheme, _, raw = auth_header.partition(" ")
        if scheme.lower() != "bearer" or not raw.strip():
            return ((401, "UNAUTHORIZED", "missing or invalid Authorization header"), None)
        record = find_token_by_raw(raw.strip())
        if record is None:
            return ((401, "UNAUTHORIZED", "invalid token"), None)
        if not scope_allows(record["scope"], request.method, request.url.path):
            return ((403, "FORBIDDEN", "token scope insufficient for this endpoint"), None)
        return (
            None,
            Principal(
                kind="token",
                token_id=record["id"],
                label=record["label"],
                scope=record["scope"],
            ),
        )

    cfg = get_config()

    # Dev escape hatch: operator opt-in to skip cookie auth on this
    # deployment. Lives in `data/config.json`; production deployments
    # leave it off. Bearer enforcement above still runs.
    if cfg.get("auth_bypass_for_dev"):
        return (None, Principal(kind="dev-bypass"))

    # Channel 2: cookie (browser session).
    cookie_value = request.cookies.get(COOKIE_NAME)
    if cookie_value:
        secret = cfg.get("session_signing_secret") or ""
        version = int(cfg.get("session_version", 0) or 0)
        payload = verify_session(cookie_value, secret)
        if payload is None or payload["v"] != version:
            return ((401, "UNAUTHORIZED", "invalid or expired session"), None)
        return (None, Principal(kind="session"))

    # Channel 3: TOFU bootstrap. No password set → allow (banner warns).
    if cfg.get("app_password_hash") is None:
        return (None, Principal(kind="tofu"))

    return ((401, "UNAUTHORIZED", "authentication required"), None)


# `mark_used` rewrites all of `data/config.json` (agent_tokens.py), so stamping
# `last_used_at` on every bearer request is a config-write storm. Throttle to at
# most once per token per window, keyed by token_id on a monotonic clock.
_MARK_USED_THROTTLE_SECONDS: Final[float] = 15 * 60
_mark_used_last: dict[str, float] = {}


def _maybe_mark_used(token_id: str) -> None:
    """Stamp ``last_used_at`` for a token, throttled per token per window.

    The throttle bookkeeping is synchronous (``_mark_used_last`` updated before
    dispatch), but the actual ``mark_used`` — a blocking rewrite of
    ``data/config.json`` — is dispatched fire-and-forget so it never runs on the
    event loop (the ``run_sync`` convention in ``src/api/CLAUDE.md``). Fail-open:
    the off-loop write's failures are logged and swallowed by the ledger task
    done-callback, and the dispatch itself is guarded so a scheduling hiccup can
    never fail the user's request.
    """
    now = time.monotonic()
    last = _mark_used_last.get(token_id)
    if last is not None and now - last < _MARK_USED_THROTTLE_SECONDS:
        return
    _mark_used_last[token_id] = now
    try:
        fire_and_forget(mark_used, token_id)
    except Exception:
        logger.warning("mark_used dispatch failed for token %s", token_id, exc_info=True)


async def require_request_auth(request: Request) -> None:
    """FastAPI dependency: enforce the standard auth channels on a handler.

    For routes under `/api/v1/auth/` that the middleware deliberately
    skips (the prefix exists so login/set-password stay reachable) but
    that are NOT bootstrap endpoints — without this, anything sharing
    the prefix is unauthenticated by accident.
    """
    error, _principal = authenticate_request(request)
    if error is not None:
        status_code, _code, message = error
        raise HTTPException(status_code=status_code, detail=message)


async def bearer_auth_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    path = request.url.path

    if request.method == "OPTIONS":
        return await call_next(request)

    if path in PUBLIC_PATHS or path.startswith(_AUTH_ROUTE_PREFIX):
        return await call_next(request)

    # Static SPA, /docs, /redoc, /openapi.json — anything outside /api/v1/*
    # is not gated. Auth is an API contract, not a UI gate.
    if not path.startswith("/api/v1/"):
        return await call_next(request)

    error, principal = authenticate_request(request)
    if error is not None:
        return _error_response(*error)
    request.state.principal = principal
    # On successful bearer auth, stamp last_used_at (throttled — see L9).
    if principal is not None and principal.kind == "token" and principal.token_id is not None:
        _maybe_mark_used(principal.token_id)
    response = await call_next(request)
    # Journal the write (L1: capture lives inside this middleware, not a second
    # one). Fail-open and fire-and-forget — never touches the response or its
    # latency. Auth semantics above are unchanged.
    capture_activity(request, response)
    return response
