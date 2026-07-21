"""Pydantic models for the agent activity ledger.

``WhoamiResponse`` is the caller-introspection payload for ``GET /api/v1/whoami``.
``ActivityEntry`` / ``ActivityListResponse`` are the read models for the write
journal served by ``GET /api/v1/activity``.
"""

from typing import Any, Literal

from pydantic import BaseModel

__all__ = [
    "ActivityEntry",
    "ActivityListResponse",
    "RevertResponse",
    "WhoamiResponse",
]


PrincipalKind = Literal["token", "session", "tofu", "dev-bypass"]


class WhoamiResponse(BaseModel):
    """The resolved identity of the current caller.

    ``token_id`` / ``label`` / ``scope`` are populated only for token principals
    (``kind == "token"``); they are ``null`` for cookie sessions, TOFU bootstrap,
    and the dev bypass. ``last_used_at`` is read from the token record and may lag
    behind the current request by up to the ``mark_used`` throttle window.
    """

    kind: PrincipalKind
    token_id: str | None
    label: str | None
    scope: str | None
    last_used_at: str | None


class ActivityEntry(BaseModel):
    """One row of the agent activity ledger.

    ``before`` / ``after`` are the staged images (L5) parsed back from the stored
    JSON: ``before`` is the pre-mutation state and ``after`` the value written (a
    delete has ``after == null`` with ``before`` set; a create has ``before ==
    {}``). Both are ``null`` for envelope-only captures. ``reversible`` is true
    only when a before/after image was staged. ``reverted_at`` / ``reverted_by``
    are set once a later entry has undone this one.
    """

    id: str
    ts: str
    principal_kind: str | None
    principal_id: str | None
    principal_label: str | None
    operation_id: str | None
    method: str | None
    path: str | None
    resource_id: str | None
    summary: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reversible: bool
    reverted_at: str | None
    reverted_by: str | None


class ActivityListResponse(BaseModel):
    """A page of ledger entries, newest first. No pagination (L12)."""

    entries: list[ActivityEntry]


class RevertResponse(BaseModel):
    """The outcome of ``POST /api/v1/activity/{id}/revert`` (L8).

    ``reverted_entry_id`` is the id of the original entry that was undone (now
    stamped ``reverted_at`` / ``reverted_by`` off the response path); ``summary``
    is a short human-readable description of what the revert restored. The revert
    is itself journaled as a new entry (kept for transparency, not itself
    reversible — redo is out of scope); that new entry's id is assigned by the
    background write and is not returned here.
    """

    reverted_entry_id: str
    summary: str
