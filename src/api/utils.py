"""Shared API utilities — error handling and validation helpers for routers."""

import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from src.finance.exceptions import VersionConflictError
from src.finance.tx_id import composite_from_tx_id

# Canonical YYYY-MM month-key pattern. Shared by every router that validates a
# month Query/path param (as `pattern=MONTH_PATTERN`) and by the month-range
# helper below, so the literal lives in exactly one place.
# Calendar-valid months only — the old `^\d{4}-\d{2}$` accepted 2026-99.
MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
MONTH_RE = re.compile(MONTH_PATTERN)


def parse_tx_id(tx_id: str) -> tuple[str, str]:
    """FastAPI dep that decodes a tx_id path param to (forwarded_to, date_file_name).

    Bad encodings → 404 (an unparseable id is a not-found, not a server error).
    """
    try:
        return composite_from_tx_id(tx_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"Transaction not found: {exc}") from exc


def generate_month_keys(from_month: str, to_month: str, *, max_months: int | None = None) -> list[str]:
    """Validate an inclusive [from_month, to_month] range and return YYYY-MM keys.

    Both bounds must match ``MONTH_PATTERN`` and ``to_month`` must be >=
    ``from_month`` (raises HTTP 422 otherwise). When ``max_months`` is given,
    a range longer than that many months is rejected with HTTP 422; callers
    that build guaranteed-valid, unbounded single-year ranges (e.g. budget YTD)
    pass ``max_months=None`` and never hit the validation branches.
    """
    if not MONTH_RE.match(from_month):
        raise HTTPException(status_code=422, detail=f"Invalid from format: {from_month}")
    if not MONTH_RE.match(to_month):
        raise HTTPException(status_code=422, detail=f"Invalid to format: {to_month}")
    if to_month < from_month:
        raise HTTPException(status_code=422, detail="'to' must be >= 'from'")

    fy, fm = map(int, from_month.split("-"))
    ty, tm = map(int, to_month.split("-"))

    keys: list[str] = []
    y, m = fy, fm
    while (y, m) <= (ty, tm):
        keys.append(f"{y}-{str(m).zfill(2)}")
        m += 1
        if m > 12:
            m = 1
            y += 1

    if max_months is not None and len(keys) > max_months:
        raise HTTPException(status_code=422, detail=f"Range exceeds {max_months} months")

    return keys


_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]")


def sanitize_filename(name: str, *, max_len: int = 80, fallback: str = "file") -> str:
    """Collapse a filename to ``[A-Za-z0-9._-]``, capped at ``max_len`` chars (L4 rule).

    Takes the final path component first (multipart filenames arrive verbatim,
    including ``../`` sequences), substitutes disallowed runs with ``_``, strips
    leading/trailing dots and underscores, truncates to ``max_len``, and falls
    back to ``fallback`` if nothing survives. The statement pipeline has its own
    variant with a wider charset — see ``statement_helpers._safe_filename_component``.
    """
    base = Path(name).name
    cleaned = _SANITIZE_RE.sub("_", base).strip("._")[:max_len].strip("._")
    return cleaned or fallback


async def run_with_conflict_handling[T](
    run_sync_fn: Callable[..., Awaitable[T]],
    func: Callable[..., T],
    *args: Any,
    detail: str = "Version conflict",
) -> T:
    """Run a sync function via the thread pool, catching version conflicts as HTTP 409.

    Parameters
    ----------
    run_sync_fn : callable
        The async run_sync helper (passed explicitly for testability).
    func : callable
        The synchronous service method to call.
    *args : positional arguments forwarded to func.
    detail : str
        HTTP 409 error message.

    Catches VersionConflictError (raised by both DynamoDB and SQLite backends)
    and converts it to an HTTPException with status 409.
    """
    try:
        return await run_sync_fn(func, *args)
    except VersionConflictError as e:
        raise HTTPException(status_code=409, detail=detail) from e
