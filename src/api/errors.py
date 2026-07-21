"""Unified error response schema for the Finance Dashboard API.

Every 4xx/5xx response emitted by the API follows the shape:

    {
      "error": "<human-readable message>",
      "code": "<MACHINE_READABLE_CODE>",
      "details": <dict or null>
    }

Routers can keep raising plain ``HTTPException(status_code=..., detail="...")`` —
the registered exception handlers (see ``src/api/main.py``) wrap those into the
unified shape automatically using ``code_from_status()``. Use ``ApiException``
directly when you need to attach a more specific ``code`` or structured
``details`` payload.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

_STATUS_TO_CODE: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    502: "UPSTREAM_ERROR",
    503: "UNAVAILABLE",
    504: "UPSTREAM_TIMEOUT",
}


def code_from_status(status_code: int) -> str:
    """Map an HTTP status code to a stable machine code.

    Falls back to ``"HTTP_<status>"`` for codes without an explicit mapping.
    """
    return _STATUS_TO_CODE.get(status_code, f"HTTP_{status_code}")


class ApiError(BaseModel):
    """Unified error response body."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"error": "Transaction not found", "code": "NOT_FOUND", "details": None},
                {"error": "invalid token", "code": "UNAUTHORIZED", "details": None},
                {
                    "error": "Validation failed",
                    "code": "VALIDATION_ERROR",
                    "details": {"field": "amount", "reason": "must be > 0"},
                },
            ]
        }
    )
    error: str
    code: str
    details: dict[str, Any] | None = None


class ApiException(HTTPException):
    """HTTPException that carries a machine-readable ``code`` and ``details``.

    The ``main.py`` exception handler unpacks ``detail`` when it finds this
    structured shape; plain ``HTTPException(detail="...")`` also works — it just
    gets the default status→code mapping.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code,
            detail={"__api_error__": True, "code": code, "message": message, "details": details},
        )
        self.code = code
        self.message = message
        self.details = details
