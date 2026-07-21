"""Shared response-assertion helpers for API tests.

Why these exist
---------------
A bare ``assert resp.status_code == 200`` produces an opaque ``assert 500 == 200``
on failure with no body context — forcing the next iteration to add a print
statement just to discover what went wrong. ``assert_ok`` and friends bake
the response body into the failure message so the diagnostic is one round-trip
shorter.

These also encode the project's unified error schema (``{error, code, details}``
— see ``src/api/errors.py``) so a single ``assert_problem(resp, 404, "NOT_FOUND")``
replaces 4 separate assertion lines.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from httpx import Response


def _try_json(resp: Any) -> Any:
    """Best-effort JSON decode for httpx.Response *or* starlette JSONResponse.

    httpx exposes ``.json()``; a raw JSONResponse only has ``.body`` (bytes).
    Returns ``None`` when the body isn't JSON (CSV/PDF/empty), so callers can
    branch on type rather than catch decode errors.
    """
    if hasattr(resp, "json") and callable(resp.json):
        try:
            return resp.json()
        except Exception:
            pass
    if hasattr(resp, "body"):
        try:
            return json.loads(bytes(resp.body))
        except Exception:
            pass
    return None


def _safe_body(resp: Response) -> str:
    parsed = _try_json(resp)
    if parsed is not None:
        return repr(parsed)
    return getattr(resp, "text", str(getattr(resp, "body", "")))[:500]


def assert_ok(resp: Response) -> Any:
    """Assert ``resp`` is 2xx; on failure, dump the body.

    Returns the parsed JSON body when the response is JSON, else ``None`` —
    works the same for CSV/PDF endpoints where the caller asserts on
    ``resp.headers`` instead of ``resp.json()``.
    """
    if not (200 <= resp.status_code < 300):
        raise AssertionError(f"expected 2xx, got {resp.status_code}: {_safe_body(resp)}")
    return _try_json(resp)


def assert_status(resp: Response, status: int) -> Any:
    """Assert ``resp.status_code == status``; on failure, dump the body."""
    if resp.status_code != status:
        raise AssertionError(f"expected {status}, got {resp.status_code}: {_safe_body(resp)}")
    return _try_json(resp)


def assert_problem(resp: Response, status: int, code: str | None = None) -> dict[str, Any]:
    """Assert ``resp`` matches the unified error envelope.

    Checks ``status_code``, that the body has exactly ``{error, code, details}``,
    and (if ``code`` is given) that ``body["code"] == code``. Returns the body.

    Accepts both httpx.Response and a raw starlette ``JSONResponse`` (e.g.
    when calling an exception handler directly in a unit test).
    """
    if resp.status_code != status:
        raise AssertionError(f"expected {status}, got {resp.status_code}: {_safe_body(resp)}")
    body = _try_json(resp)
    if not isinstance(body, dict):
        raise AssertionError(f"expected JSON error envelope, got {type(body).__name__}: {_safe_body(resp)}")
    expected_keys = {"error", "code", "details"}
    if set(body.keys()) != expected_keys:
        raise AssertionError(f"expected error envelope keys {expected_keys}, got {set(body.keys())}: {body!r}")
    if code is not None and body["code"] != code:
        raise AssertionError(f"expected code={code!r}, got code={body['code']!r}: {body!r}")
    return body
