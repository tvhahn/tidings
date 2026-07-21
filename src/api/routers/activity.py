"""Agent activity ledger endpoints.

``GET /api/v1/whoami`` is caller introspection — it reads the ``Principal`` the
auth middleware stashed on ``request.state`` and, for token principals, resolves
the current ``last_used_at`` from the token record. ``GET /api/v1/activity`` is
the write journal: a newest-first, unpaginated feed of ledger entries with
``limit`` / ``since`` / ``principal`` / ``operation`` filters. The revert
endpoint lands in a later phase.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.api.activity import stage_before
from src.api.activity_revert import REVERT_DISPATCH, RevertServices
from src.api.dependencies import (
    get_activity_store,
    get_budget_service,
    get_merchant_alias_service,
    get_override_service,
    get_transactions_db,
)
from src.api.models import ActivityEntry, ActivityListResponse, RevertResponse, WhoamiResponse
from src.finance import agent_tokens

if TYPE_CHECKING:
    from src.api.auth import Principal
    from src.finance.protocols import (
        IActivityStore,
        IBudgetService,
        IMerchantAliasService,
        IOverrideService,
        ITransactionsDB,
    )

router = APIRouter(tags=["activity"])


def _entry_from_row(row: dict[str, Any]) -> ActivityEntry:
    """Map a stored ledger row to the API model, parsing the JSON images back."""
    before_json = row.get("before_json")
    after_json = row.get("after_json")
    return ActivityEntry(
        id=row["id"],
        ts=row["ts"],
        principal_kind=row.get("principal_kind"),
        principal_id=row.get("principal_id"),
        principal_label=row.get("principal_label"),
        operation_id=row.get("operation_id"),
        method=row.get("method"),
        path=row.get("path"),
        resource_id=row.get("resource_id"),
        summary=row.get("summary"),
        before=json.loads(before_json) if before_json else None,
        after=json.loads(after_json) if after_json else None,
        reversible=bool(row.get("reversible")),
        reverted_at=row.get("reverted_at"),
        reverted_by=row.get("reverted_by"),
    )


@router.get(
    "/whoami",
    response_model=WhoamiResponse,
    operation_id="getWhoami",
    summary="Resolve the current caller's identity (token, session, TOFU, or dev-bypass)",
)
async def get_whoami(request: Request) -> WhoamiResponse:
    """Return the resolved identity of the current caller.

    For token principals the response carries the token id, label, scope, and the
    stored ``last_used_at`` (which may lag the current request by up to the
    ``mark_used`` throttle window). Non-token principals report ``null`` for all
    token fields.
    """
    principal: Principal | None = getattr(request.state, "principal", None)
    if principal is None:
        # Defensive: the middleware always stashes a principal on any request
        # that reaches a handler under /api/v1/*.
        raise HTTPException(status_code=401, detail="authentication required")

    last_used_at: str | None = None
    if principal.kind == "token" and principal.token_id is not None:
        for record in agent_tokens.list_tokens():
            if record["id"] == principal.token_id:
                last_used_at = record["last_used_at"]
                break

    return WhoamiResponse(
        kind=principal.kind,
        token_id=principal.token_id,
        label=principal.label,
        scope=principal.scope,
        last_used_at=last_used_at,
    )


@router.get(
    "/activity",
    response_model=ActivityListResponse,
    operation_id="listActivity",
    summary="List agent activity ledger entries, newest first",
)
async def list_activity(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    since: str | None = Query(None, description="Inclusive ISO-8601 lower bound on entry timestamp"),
    principal: str | None = Query(
        None,
        description="Filter by principal id (token id), or the literal 'me' for the current caller",
    ),
    operation: str | None = Query(None, description="Filter by operation_id (exact match)"),
    store: IActivityStore = Depends(get_activity_store),
) -> ActivityListResponse:
    """Return ledger entries newest-first, filtered by the query params (L12).

    ``principal`` accepts a raw token id or ``me``. For ``me`` on a token
    principal it resolves to that token's id and uses the store's principal
    filter; for a non-token principal (session/tofu/dev-bypass) there is no
    stable id, so the store narrows by ``principal_kind`` — applied before the
    limit, so the caller's own feed is never crowded out by token entries that
    would otherwise consume the page. No pagination.
    """
    principal_filter = principal
    kind_filter: str | None = None
    if principal == "me":
        caller: Principal | None = getattr(request.state, "principal", None)
        if caller is not None and caller.kind == "token" and caller.token_id is not None:
            principal_filter = caller.token_id
        else:
            # Non-token callers have no principal_id — narrow by kind in the store.
            principal_filter = None
            kind_filter = getattr(caller, "kind", None)

    # Called synchronously (like the whoami handler's token lookup): the ledger
    # read is a cheap, single-user introspection query and this router does not
    # import ``run_sync`` (keeps it out of the mock_run_sync allowlist). The
    # principal_kind filter is pushed into the store so it applies before the
    # limit.
    rows = store.list_entries(principal_filter, since, operation, limit, principal_kind=kind_filter)

    return ActivityListResponse(entries=[_entry_from_row(r) for r in rows])


@router.post(
    "/activity/{entry_id}/revert",
    response_model=RevertResponse,
    operation_id="revertActivity",
    summary="Revert a single ledger entry, restoring the resource's prior state",
)
async def revert_activity(
    entry_id: str,
    request: Request,
    force: bool = Query(False, description="Override the stale-revert guard and apply the revert anyway"),
    store: IActivityStore = Depends(get_activity_store),
    transactions_db: ITransactionsDB = Depends(get_transactions_db),
    override_service: IOverrideService = Depends(get_override_service),
    merchant_alias_service: IMerchantAliasService = Depends(get_merchant_alias_service),
    budget_service: IBudgetService = Depends(get_budget_service),
) -> RevertResponse:
    """Undo one ledger entry by re-applying its recorded ``before`` image (L8).

    404 for an unknown id; 409 when the entry was already reverted, is not
    reversible, or its operation has no revert function. When the resource changed
    since the entry was written the revert returns ``409 stale_revert`` (with the
    stale ``tx_id`` list for bulk) unless ``force=true``.

    Double-revert safety is in-process: the handler stamps the original entry's
    ``reverted_at`` / ``reverted_by`` synchronously (``store.mark_reverted``)
    before returning, and there is no ``await`` between ``get_entry`` and that
    stamp, so two concurrent reverts serialize on the event loop — the second
    reads ``reverted_at`` already set and 409s. The link points at a pre-generated
    id so it holds regardless of when the receipt is written.

    The revert itself flows through the normal capture path, so it is journaled as
    a new entry with its images kept for transparency (``summary = "revert of
    <id>"``) but marked ``reversible: false`` — redo is out of scope. Accepted
    trade-off: that revert receipt is still written fire-and-forget, so a process
    death between the synchronous ``mark_reverted`` and the receipt write would
    leave ``reverted_by`` pointing at a receipt that never landed; the ledger is
    fail-open and the UI renders the reverted state from ``reverted_at`` alone.
    """
    entry = store.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="activity entry not found")
    if entry.get("reverted_at"):
        raise HTTPException(status_code=409, detail="entry has already been reverted")

    operation_id = entry.get("operation_id")
    revert_fn = REVERT_DISPATCH.get(operation_id) if operation_id else None
    if not entry.get("reversible") or revert_fn is None:
        raise HTTPException(status_code=409, detail="entry is not reversible")

    services = RevertServices(
        transactions_db=transactions_db,
        override_service=override_service,
        merchant_alias_service=merchant_alias_service,
        budget_service=budget_service,
    )
    # Applied synchronously — like this router's list/whoami reads, the revert is
    # a low-frequency single-user operation and the module deliberately keeps
    # run_sync out (see list_activity). A stale-revert 409 raised inside the
    # dispatch function propagates unchanged. mark_reverted (below) runs only when
    # this succeeds, so a failed revert never marks the entry.
    result_summary = revert_fn(entry, services, force)

    # Pre-generate the revert receipt's id and stash it: build_entry stamps the
    # fire-and-forget receipt with this exact id, so the reverted_by link set
    # synchronously below is valid the moment it lands, not whenever the receipt
    # eventually does.
    new_id = uuid.uuid4().hex
    request.state.activity_entry_id = new_id

    # Stage the revert's own before/after images. They are kept purely for
    # transparency in the feed — the revert entry lands ``reversible: false``
    # (revertActivity is outside REVERTIBLE_OPERATIONS; redo is out of scope), so
    # these images are never replayed. The revert's before is the state we moved
    # away from (the original's ``after``); its after is what we restored (the
    # original's ``before``) — re-shaped so a delete's inverse is a create and
    # vice versa.
    orig_before = json.loads(entry["before_json"]) if entry.get("before_json") else None
    orig_after = json.loads(entry["after_json"]) if entry.get("after_json") else None
    if orig_after is None:
        revert_before: dict[str, Any] = {}
        revert_after: dict[str, Any] | None = orig_before
    elif not orig_before:
        revert_before = orig_after
        revert_after = None
    else:
        revert_before = orig_after
        revert_after = orig_before
    stage_before(
        request,
        resource="activity_revert",
        before=revert_before,
        after=revert_after,
        summary=f"revert of {entry_id}",
    )

    # Link the original to its revert synchronously, before returning. Passing the
    # original's ``ts`` lets the DynamoDB backend reconstruct the item key with no
    # partition scan. Because nothing between get_entry and here awaits, concurrent
    # reverts serialize on the loop and the second 409s on ``reverted_at``.
    store.mark_reverted(entry_id, new_id, ts=entry["ts"])

    return RevertResponse(reverted_entry_id=entry_id, summary=result_summary)
