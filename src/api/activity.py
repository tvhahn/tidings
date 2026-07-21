"""Activity-ledger capture seam (Phase 3).

This module owns the write-capture half of the agent activity ledger: the pure
predicate that decides whether a request should be journaled (:func:`should_capture`),
the handler-side before/after staging helper (:func:`stage_before`), the
envelope assembly that turns a finished request/response pair into a ledger row,
and the fire-and-forget dispatch that hands the row to the store off the response
path.

Design constraints (locked decisions L3/L4/L7):

- **Never reads request or response bodies.** The envelope is built entirely from
  the request scope (method, path, route, path_params) and the ``Principal`` the
  auth middleware stashed — so multipart uploads and streaming responses pass
  through untouched.
- **Fire-and-forget.** The store write is dispatched as a background task and the
  response returns immediately; a slow DynamoDB put adds zero latency to the
  caller's request. The module-level strong ref in :data:`_LEDGER_TASKS` keeps the
  bare task from being garbage-collected mid-flight.
- **Fail-open.** Capture is wrapped so a ledger failure can never fail the user's
  request.

This module deliberately does not import from :mod:`src.api.auth` (which imports
*this* module) nor eagerly from :mod:`src.api.dependencies`; the store getter is
imported lazily inside :func:`capture_activity` to keep module load acyclic.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi import Request, Response

    from src.finance.protocols import IActivityStore

logger = logging.getLogger(__name__)

# Methods that never mutate — a GET/HEAD/OPTIONS is a read (L4).
_SKIP_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})

# Write-verbed reads and dry-run/preview endpoints that mutate no user data, so
# they never earn a ledger receipt (L4, revised 2026-07-17 — four members).
_LEDGER_EXEMPT: frozenset[str] = frozenset(
    {
        "testOpenAIKey",
        "searchTransactionsByFilter",
        "exportFullBackup",
        "previewBackupImport",
    }
)

# The ten instrumented operations whose entries can be reverted (L5/L8). This is
# the single source of truth: build_entry marks an entry reversible only when its
# operation is in this set AND the handler staged images, and the revert dispatch
# table asserts it covers exactly this set. The revert endpoint's own entries
# (operation_id "revertActivity") are deliberately NOT here — their images are
# kept for transparency, but redo (revert-of-revert) is out of scope, and a
# reversible flag the endpoint would 409 on would put a dead button in the feed.
REVERTIBLE_OPERATIONS: frozenset[str] = frozenset(
    {
        "patchTransaction",
        "setTransactionComment",
        "updateTransactionFields",
        "bulkUpdateTransactionCategory",
        "putOverride",
        "deleteOverride",
        "putMerchantAlias",
        "deleteMerchantAlias",
        "putBudgetConfig",
        "putGroups",
    }
)

# Strong references to in-flight ledger writes. Bare fire-and-forget tasks can be
# garbage-collected mid-flight, so we hold each until its done-callback discards it.
_LEDGER_TASKS: set[asyncio.Task[Any]] = set()


def should_capture(request: Request, response: Response) -> bool:
    """Whether this finished request/response should be journaled (pure, L4).

    Captured iff: the method mutates (not GET/HEAD/OPTIONS); the path is under
    ``/api/v1/`` but not under ``/api/v1/auth/``; the response is 2xx (a failed
    write changed nothing, and 3xx skips the legacy 308-redirect double-fire);
    and the route's ``operation_id`` is not in :data:`_LEDGER_EXEMPT`.
    """
    if request.method in _SKIP_METHODS:
        return False
    path = request.url.path
    if not path.startswith("/api/v1/"):
        return False
    if path.startswith("/api/v1/auth/"):
        return False
    if not (200 <= response.status_code < 300):
        return False
    operation_id = getattr(request.scope.get("route"), "operation_id", None)
    return operation_id not in _LEDGER_EXEMPT


def stage_before(
    request: Request,
    *,
    resource: str,
    before: dict[str, Any],
    after: dict[str, Any] | None = None,
    summary: str | None = None,
) -> None:
    """Stash a before/after image for the middleware to merge into the entry (L5).

    Called by an instrumented handler after it has read the current state of the
    resource it is about to mutate. ``after`` is the value being written (a delete
    passes ``after=None`` with ``before`` set; a create passes ``before={}``); the
    presence of any staged payload is what makes the resulting entry reversible.
    """
    request.state.activity_before = {
        "resource": resource,
        "before": before,
        "after": after,
        "summary": summary,
    }


def build_entry(request: Request, response: Response) -> dict[str, Any]:
    """Assemble a ledger envelope from a finished request/response pair (L3).

    Reads only the request scope and the stashed ``Principal`` / staged before —
    never the request or response body. May raise; the caller wraps it fail-open.
    """
    principal = getattr(request.state, "principal", None)
    method = request.method
    path = request.url.path

    # Resolve the route only after ``call_next`` — it is attached during routing.
    operation_id = getattr(request.scope.get("route"), "operation_id", None) or f"{method} {path}"

    path_params: dict[str, Any] = request.scope.get("path_params", {}) or {}
    resource_id = "/".join(str(v) for v in path_params.values()) or None

    staged: dict[str, Any] | None = getattr(request.state, "activity_before", None)
    summary: str | None = None
    before_json: str | None = None
    after_json: str | None = None
    reversible = False
    if staged is not None:
        # A staged payload — even an empty-dict before — makes the entry
        # reversible, but only for operations the revert dispatch actually
        # covers: a reversible flag the endpoint would 409 on is a dead button.
        reversible = operation_id in REVERTIBLE_OPERATIONS
        summary = staged.get("summary")
        before = staged.get("before")
        after = staged.get("after")
        if before is not None:
            before_json = json.dumps(before, default=str)
        if after is not None:
            after_json = json.dumps(after, default=str)

    entry: dict[str, Any] = {
        "principal_kind": getattr(principal, "kind", None),
        "principal_id": getattr(principal, "token_id", None),
        "principal_label": getattr(principal, "label", None),
        "operation_id": operation_id,
        "method": method,
        "path": path,
        "resource_id": resource_id,
        "summary": summary,
        "before_json": before_json,
        "after_json": after_json,
        "reversible": reversible,
    }

    # A revert handler pre-generates its receipt's id and stashes it on
    # ``request.state`` so this fire-and-forget receipt carries that exact id —
    # the id the handler's synchronous ``store.mark_reverted`` already linked the
    # original entry to (L8). Both stores honor a caller-provided id
    # (``entry.get("id") or uuid...``).
    entry_id = getattr(request.state, "activity_entry_id", None)
    if entry_id is not None:
        entry["id"] = entry_id

    return entry


def _on_ledger_task_done(task: asyncio.Task[Any]) -> None:
    """Discard a finished ledger task and log any exception it swallowed."""
    _LEDGER_TASKS.discard(task)
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is not None:
        logger.warning("activity ledger write failed", exc_info=exc)


def fire_and_forget(fn: Callable[..., Any], *args: Any) -> None:
    """Run a blocking callable off the event loop, fire-and-forget (L7).

    Schedules ``fn(*args)`` on a worker thread (``asyncio.to_thread``) so the
    blocking work never runs on the event loop; the task is held in
    :data:`_LEDGER_TASKS` (strong ref) until its done-callback discards it and
    logs any exception it raised. The caller never awaits. Shared by the ledger
    write dispatch and the auth middleware's throttled ``mark_used`` stamp, so a
    single :func:`drain_ledger_tasks` covers both in tests/shutdown.
    """
    loop = asyncio.get_running_loop()
    task = loop.create_task(asyncio.to_thread(fn, *args))
    _LEDGER_TASKS.add(task)
    task.add_done_callback(_on_ledger_task_done)


def _dispatch_record(store: IActivityStore, entry: dict[str, Any]) -> None:
    """Fire-and-forget the store write off the response path (L7).

    The blocking ``store.record`` runs in a thread so it never blocks the event
    loop. Revert→original linkage is no longer done here — the revert handler
    stamps ``reverted_at`` synchronously before returning (see
    :func:`src.api.routers.activity.revert_activity`), so this is a plain record.
    """
    fire_and_forget(store.record, entry)


def capture_activity(request: Request, response: Response) -> None:
    """Journal a finished request if it qualifies — fail-open, fire-and-forget.

    Called from the auth middleware after ``call_next``. Any failure (envelope
    assembly, store lookup, dispatch) is logged and swallowed so the user's
    response is never affected.
    """
    try:
        if not should_capture(request, response):
            return
        entry = build_entry(request, response)
        # Lazy import to keep module load acyclic (auth → activity → dependencies).
        from src.api.dependencies import get_activity_store

        _dispatch_record(get_activity_store(), entry)
    except Exception:
        logger.warning("activity capture failed", exc_info=True)


async def drain_ledger_tasks() -> None:
    """Await all in-flight ledger writes (test/shutdown determinism seam, L7)."""
    if not _LEDGER_TASKS:
        return
    await asyncio.gather(*list(_LEDGER_TASKS), return_exceptions=True)
