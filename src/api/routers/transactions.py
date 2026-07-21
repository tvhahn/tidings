"""Transaction endpoints: list, attention queue, update category, mark reviewed.

The mutation endpoints take a `tx_id` surrogate in the URL path — a
URL-safe base64url encoding of `{forwarded_to}|{date_file_name}` (see
`src/finance/tx_id.py`). Legacy URLs of the form
`/transactions/{forwarded_to}/{date_file_name}/...` still work but
return a 308 Permanent Redirect to the surrogate shape with a
`Deprecation: true` header and a `Link: …; rel="successor-version"`
pointer. Consumers can grep their access logs for the Deprecation
header to find call sites that need updating.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from src.api.activity import stage_before
from src.api.dependencies import get_override_service, get_spending_summary, get_transactions_db, run_sync
from src.api.models import (
    AttentionListResponse,
    BulkCategoryUpdateRequest,
    BulkCategoryUpdateResponse,
    BulkCategoryUpdateResult,
    CategoryUpdateRequest,
    CategoryUpdateResponse,
    CombinedTransactionsResponse,
    CommentRequest,
    CommentResponse,
    DeleteRequest,
    DeleteResponse,
    IgnoreRequest,
    IgnoreResponse,
    LatestTimestampResponse,
    PermanentDeleteResponse,
    ReviewResponse,
    TransactionDetailResponse,
    TransactionFieldsOldValues,
    TransactionFieldsUpdateRequest,
    TransactionFieldsUpdateResponse,
    TransactionListResponse,
)
from src.api.serializers import (
    PROJECTION_NAMES,
    TRANSACTION_LIST_PROJECTION,
    is_attention,
    lookup_override_category,
    to_transaction_response,
)
from src.api.utils import MONTH_PATTERN, parse_tx_id
from src.finance.protocols import IOverrideService, ISpendingSummary, ITransactionsDB
from src.finance.tx_id import tx_id_from_composite

router = APIRouter(tags=["transactions"])

# Bulk ledger before/after images are capped at this many rows: a ledger entry is
# a single DynamoDB item under a 400 KB hard limit, so beyond the cap staging is
# withheld and the entry stays reversible: false (L5).
_LEDGER_ROW_CAP = 200


def _split_items(items: Sequence[Mapping[str, Any]], month: str) -> CombinedTransactionsResponse:
    """Split raw DynamoDB items into transactions, attention, and trash lists."""
    active = []
    attention = []
    trash = []
    for item in items:
        if item.get("DeletedAt"):
            trash.append(item)
        else:
            active.append(item)
            if is_attention(item):
                attention.append(item)

    active.sort(key=lambda x: x.get("DateFileName", ""), reverse=True)
    attention.sort(key=lambda x: x.get("DateFileName", ""), reverse=True)
    trash.sort(key=lambda x: x.get("DateFileName", ""), reverse=True)

    return CombinedTransactionsResponse(
        month=month,
        transactions=TransactionListResponse(
            month=month,
            count=len(active),
            transactions=[to_transaction_response(i) for i in active],
        ),
        attention=AttentionListResponse(
            month=month,
            count=len(attention),
            transactions=[to_transaction_response(i) for i in attention],
        ),
        trash=TransactionListResponse(
            month=month,
            count=len(trash),
            transactions=[to_transaction_response(i) for i in trash],
        ),
    )


@router.get(
    "/transactions/all",
    response_model=CombinedTransactionsResponse,
    operation_id="listAllTransactions",
    summary="Combined active + attention + trash buckets for a month",
)
async def list_all_transactions(
    month: str = Query(..., pattern=MONTH_PATTERN),
    summary: ISpendingSummary = Depends(get_spending_summary),
):
    items = await run_sync(summary.query_month, month, TRANSACTION_LIST_PROJECTION, PROJECTION_NAMES)
    return _split_items(items, month)


@router.get(
    "/transactions/bulk",
    response_model=dict[str, CombinedTransactionsResponse],
    operation_id="listBulkTransactions",
    summary="Combined transactions across multiple months (max 12)",
)
async def list_bulk_transactions(
    months: str = Query(..., description="Comma-separated YYYY-MM list, max 12"),
    summary: ISpendingSummary = Depends(get_spending_summary),
):
    month_list = [m.strip() for m in months.split(",") if m.strip()]
    if len(month_list) > 12:
        raise HTTPException(status_code=422, detail="Maximum 12 months allowed")
    for m in month_list:
        if not re.fullmatch(MONTH_PATTERN, m):
            raise HTTPException(status_code=422, detail=f"Invalid month format: {m}")

    # Sequential iteration — bulk preload is background work, so latency is
    # acceptable while avoiding the CPU thundering herd from asyncio.gather
    # firing all months concurrently.
    result: dict[str, CombinedTransactionsResponse] = {}
    for m in month_list:
        items = await run_sync(summary.query_month, m, TRANSACTION_LIST_PROJECTION, PROJECTION_NAMES)
        result[m] = _split_items(items, m)
    return result


@router.patch(
    "/transactions/bulk",
    response_model=BulkCategoryUpdateResponse,
    operation_id="bulkUpdateTransactionCategory",
    summary="Update categories on many transactions in a single request",
)
async def bulk_update_category(
    body: BulkCategoryUpdateRequest,
    request: Request,
    db: ITransactionsDB = Depends(get_transactions_db),
):
    """Update the category on many transactions in a single request.

    Each ``updates`` item carries its own target category (unlike the internal
    ``batch_update_category`` which applies one category to many rows). Rows
    that fail to update are reported in ``results`` with ``ok=False`` and an
    ``error`` message; the rest still apply — this endpoint does **not** roll
    back on partial failure.
    """
    # Ledger before/after images (L5): capped at 200 rows because a ledger entry
    # is a single DynamoDB item under a 400 KB hard limit — beyond the cap we
    # withhold staging entirely so the entry stays reversible: false rather than
    # risk a silently-dropped oversized put.
    stage = len(body.updates) <= _LEDGER_ROW_CAP
    before_rows: list[dict[str, Any]] = []
    after_rows: list[dict[str, Any]] = []

    results: list[BulkCategoryUpdateResult] = []
    succeeded = 0
    failed = 0
    for item in body.updates:
        try:
            # Read the pre-mutation projection first so the before-image is never
            # the already-mutated row.
            before_item = await run_sync(db.get_item, item.forwarded_to, item.date_file_name) if stage else None
            old = await run_sync(
                db.update_category,
                item.forwarded_to,
                item.date_file_name,
                item.category,
                body.source,
            )
            results.append(
                BulkCategoryUpdateResult(
                    tx_id=tx_id_from_composite(item.forwarded_to, item.date_file_name),
                    forwarded_to=item.forwarded_to,
                    date_file_name=item.date_file_name,
                    new_category=item.category,
                    old_category=old,
                    ok=True,
                )
            )
            succeeded += 1
            if stage:
                tx_id = tx_id_from_composite(item.forwarded_to, item.date_file_name)
                old_source = (before_item.get("CategoryAudit") or {}).get("source") if before_item else None
                before_rows.append({"tx_id": tx_id, "category": old, "category_source": old_source})
                after_rows.append({"tx_id": tx_id, "category": item.category.lower(), "category_source": body.source})
        except Exception as exc:
            results.append(
                BulkCategoryUpdateResult(
                    tx_id=tx_id_from_composite(item.forwarded_to, item.date_file_name),
                    forwarded_to=item.forwarded_to,
                    date_file_name=item.date_file_name,
                    new_category=item.category,
                    ok=False,
                    error=str(exc),
                )
            )
            failed += 1

    if stage and before_rows:
        stage_before(
            request,
            resource="transactions",
            before={"rows": before_rows},
            after={"rows": after_rows},
            summary=f"recategorized {succeeded} transactions",
        )

    return BulkCategoryUpdateResponse(
        total=len(body.updates),
        succeeded=succeeded,
        failed=failed,
        results=results,
    )


@router.get(
    "/transactions",
    response_model=TransactionListResponse,
    operation_id="listTransactions",
    summary="List active (non-deleted) transactions for a month",
)
async def list_transactions(
    month: str = Query(..., pattern=MONTH_PATTERN),
    summary: ISpendingSummary = Depends(get_spending_summary),
):
    items = await run_sync(summary.query_month, month)
    items = [item for item in items if not item.get("DeletedAt")]
    items.sort(key=lambda x: x.get("DateFileName", ""), reverse=True)
    transactions = [to_transaction_response(item) for item in items]
    return TransactionListResponse(month=month, count=len(transactions), transactions=transactions)


@router.get(
    "/transactions/latest",
    response_model=LatestTimestampResponse,
    operation_id="getLatestTransactionTimestamp",
    summary="Freshness probe — max DateFileName, optionally scoped to a month",
)
async def latest_transaction_timestamp(
    month: str | None = Query(None, pattern=MONTH_PATTERN),
    db: ITransactionsDB = Depends(get_transactions_db),
):
    """Freshness probe — returns the max DateFileName, optionally scoped to a month.

    Used by the frontend to detect new transactions without refetching full
    month data. `latest` is a lex-sortable DateFileName string (e.g.
    "2026.04.20_14.32_...") or null if no matching rows.
    """
    latest = await run_sync(db.get_latest_date_file_name, month)
    return LatestTimestampResponse(month=month, latest=latest)


@router.get(
    "/transactions/attention",
    response_model=AttentionListResponse,
    operation_id="getAttentionQueue",
    summary="Transactions needing review (uncategorized, not ignored, not deleted)",
)
async def attention_queue(
    month: str = Query(..., pattern=MONTH_PATTERN),
    summary: ISpendingSummary = Depends(get_spending_summary),
):
    items = await run_sync(summary.query_month, month)
    attention = [item for item in items if is_attention(item)]
    attention.sort(key=lambda x: x.get("DateFileName", ""), reverse=True)
    transactions = [to_transaction_response(item) for item in attention]
    return AttentionListResponse(month=month, count=len(transactions), transactions=transactions)


@router.get(
    "/transactions/trash",
    response_model=TransactionListResponse,
    operation_id="listTrashedTransactions",
    summary="Soft-deleted transactions for a month",
)
async def list_trash(
    month: str = Query(..., pattern=MONTH_PATTERN),
    summary: ISpendingSummary = Depends(get_spending_summary),
):
    items = await run_sync(summary.query_month, month)
    items = [item for item in items if item.get("DeletedAt")]
    items.sort(key=lambda x: x.get("DateFileName", ""), reverse=True)
    transactions = [to_transaction_response(item) for item in items]
    return TransactionListResponse(month=month, count=len(transactions), transactions=transactions)


# ---------------------------------------------------------------------------
# tx_id-shaped endpoints (the canonical surface from 2026-05-01 forward)
# ---------------------------------------------------------------------------


@router.get(
    "/transactions/{tx_id}/detail",
    response_model=TransactionDetailResponse,
    operation_id="getTransactionDetail",
    summary="Full transaction record including email body and headers",
)
async def get_transaction_detail(
    composite: tuple[str, str] = Depends(parse_tx_id),
    db: ITransactionsDB = Depends(get_transactions_db),
):
    forwarded_to, date_file_name = composite
    item = await run_sync(db.get_item, forwarded_to, date_file_name)
    if not item:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return TransactionDetailResponse(
        tx_id=tx_id_from_composite(forwarded_to, date_file_name),
        forwarded_to=item["ForwardedTo"],
        date_file_name=item["DateFileName"],
        subject=item.get("Subject"),
        body=item.get("Body"),
        from_name=item.get("FromName"),
        from_email=item.get("FromEmail"),
        to_name=item.get("ToName"),
        to_email=item.get("ToEmail"),
    )


@router.put(
    "/transactions/{tx_id}/fields",
    response_model=TransactionFieldsUpdateResponse,
    operation_id="updateTransactionFields",
    summary="Update editable transaction fields (company, amount, transaction_type)",
)
async def update_fields(
    body: TransactionFieldsUpdateRequest,
    request: Request,
    composite: tuple[str, str] = Depends(parse_tx_id),
    db: ITransactionsDB = Depends(get_transactions_db),
    override_svc: IOverrideService = Depends(get_override_service),
):
    forwarded_to, date_file_name = composite

    # Field-level validation (non-empty company, amount > 0, known
    # transaction_type) is declared on TransactionFieldsUpdateRequest, so by
    # here every provided value is already valid.
    fields: dict[str, Any] = {}
    if body.company is not None:
        fields["company"] = body.company
    if body.amount is not None:
        fields["amount"] = body.amount
    if body.transaction_type is not None:
        fields["transaction_type"] = body.transaction_type

    if not fields:
        raise HTTPException(status_code=422, detail="At least one field must be provided")

    # Check category overrides for auto-suggestion (Tier 0/1/2 via resolver).
    category = None
    if "company" in fields:
        category = await run_sync(lookup_override_category, fields["company"], override_svc)

    old_values = await run_sync(db.update_fields, forwarded_to, date_file_name, fields, category)
    if old_values is None:  # unreachable: the empty-fields 422 guard above
        raise HTTPException(status_code=500, detail="Update failed")

    # Ledger before/after (L5): update_fields returns the pre-mutation values
    # atomically, so they are a correct before-image.
    new_category = category.lower() if category else old_values.get("old_category")
    stage_before(
        request,
        resource="transaction",
        before={
            "company": old_values.get("old_company"),
            "amount": old_values.get("old_amount"),
            "transaction_type": old_values.get("old_transaction_type"),
            "category": old_values.get("old_category"),
        },
        after={
            "company": fields.get("company", old_values.get("old_company")),
            "amount": fields.get("amount", old_values.get("old_amount")),
            "transaction_type": fields.get("transaction_type", old_values.get("old_transaction_type")),
            "category": new_category,
        },
        summary="updated transaction fields",
    )

    return TransactionFieldsUpdateResponse(
        tx_id=tx_id_from_composite(forwarded_to, date_file_name),
        forwarded_to=forwarded_to,
        date_file_name=date_file_name,
        company=fields.get("company", old_values.get("old_company")),
        amount=fields.get("amount", old_values.get("old_amount")),
        transaction_type=fields.get("transaction_type", old_values.get("old_transaction_type")),
        category=category.lower() if category else old_values.get("old_category"),
        old_values=TransactionFieldsOldValues(
            company=old_values.get("old_company"),
            amount=old_values.get("old_amount"),
            transaction_type=old_values.get("old_transaction_type"),
        ),
    )


@router.patch(
    "/transactions/{tx_id}",
    response_model=CategoryUpdateResponse,
    operation_id="patchTransaction",
    summary="Partial update — category, state (active/ignored/trashed), and/or reviewed",
)
async def patch_transaction(
    body: CategoryUpdateRequest,
    request: Request,
    composite: tuple[str, str] = Depends(parse_tx_id),
    db: ITransactionsDB = Depends(get_transactions_db),
):
    """Apply any subset of {category, state, reviewed} to a transaction.

    State semantics — the value provided IS the state after the call:

    - ``active``  → clears both Ignored and DeletedAt.
    - ``ignored`` → sets Ignored. Preserves DeletedAt; if the row is currently
      trashed, the derived state stays trashed (trashed wins). PATCH
      ``state="active"`` first to bring a trashed row back, then
      ``state="ignored"`` to ignore it.
    - ``trashed`` → sets DeletedAt to now.

    Empty body is a no-op (returns all-None response). Missing fields are
    not modified.
    """
    forwarded_to, date_file_name = composite

    # Read the pre-mutation state up front — but only when the patch actually
    # mutates — so the ledger before-image (L5) is the row as it stood before
    # this patch, and an empty/no-op body stays a true no-op (no read, no entry).
    will_mutate = body.category is not None or body.state is not None or bool(body.reviewed)
    before_item = await run_sync(db.get_item, forwarded_to, date_file_name) if will_mutate else None

    old_category: str | None = None
    new_category: str | None = None
    state_out: str | None = None
    reviewed_out: bool | None = None
    deleted_at_out: str | None = None

    if body.category is not None:
        old_category = await run_sync(db.update_category, forwarded_to, date_file_name, body.category, "manual")
        new_category = body.category.lower()

    if body.state == "active":
        await run_sync(db.set_ignored, forwarded_to, date_file_name, False)
        await run_sync(db.set_deleted, forwarded_to, date_file_name, False)
        state_out = "active"
    elif body.state == "ignored":
        await run_sync(db.set_ignored, forwarded_to, date_file_name, True)
        state_out = "ignored"
    elif body.state == "trashed":
        await run_sync(db.set_deleted, forwarded_to, date_file_name, True)
        state_out = "trashed"
        # One re-read to surface the just-stamped DeletedAt timestamp.
        item = await run_sync(db.get_item, forwarded_to, date_file_name)
        deleted_at_out = item.get("DeletedAt") if item else None

    if body.reviewed:
        await run_sync(db.mark_category_reviewed, forwarded_to, date_file_name, "manual")
        reviewed_out = True

    # Ledger before/after (L5): capture the reversible core — category and the
    # active/ignored/trashed state — projected from the pre-mutation row. Skipped
    # for a no-op body (nothing read, nothing staged).
    if will_mutate:
        before_img: dict[str, Any] = {}
        if before_item is not None:
            before_img = {
                "Category": before_item.get("Category"),
                "Ignored": before_item.get("Ignored"),
                "DeletedAt": before_item.get("DeletedAt"),
            }
        after_img = dict(before_img)
        if new_category is not None:
            after_img["Category"] = new_category
        if state_out == "active":
            after_img["Ignored"] = False
            after_img["DeletedAt"] = None
        elif state_out == "ignored":
            after_img["Ignored"] = True
        elif state_out == "trashed":
            after_img["DeletedAt"] = deleted_at_out
        stage_before(
            request,
            resource="transaction",
            before=before_img,
            after=after_img,
            summary="updated transaction",
        )

    return CategoryUpdateResponse(
        tx_id=tx_id_from_composite(forwarded_to, date_file_name),
        forwarded_to=forwarded_to,
        date_file_name=date_file_name,
        old_category=old_category,
        new_category=new_category,
        state=state_out,
        reviewed=reviewed_out,
        deleted_at=deleted_at_out,
    )


@router.post(
    "/transactions/{tx_id}/review",
    response_model=ReviewResponse,
    operation_id="markTransactionReviewed",
    summary="Mark a transaction's category as manually reviewed",
    deprecated=True,
    description="Deprecated — use `PATCH /transactions/{tx_id}` with `{reviewed: true}` instead.",
)
async def mark_reviewed(
    composite: tuple[str, str] = Depends(parse_tx_id),
    db: ITransactionsDB = Depends(get_transactions_db),
):
    forwarded_to, date_file_name = composite
    await run_sync(db.mark_category_reviewed, forwarded_to, date_file_name, "manual")
    return ReviewResponse(
        tx_id=tx_id_from_composite(forwarded_to, date_file_name),
        forwarded_to=forwarded_to,
        date_file_name=date_file_name,
        source="manual",
    )


@router.post(
    "/transactions/{tx_id}/ignore",
    response_model=IgnoreResponse,
    operation_id="setTransactionIgnored",
    summary="Toggle the ignored flag on a transaction",
    deprecated=True,
    description=(
        "Deprecated — use `PATCH /transactions/{tx_id}` with `{state: 'ignored'}` or `{state: 'active'}` instead."
    ),
)
async def set_ignored(
    body: IgnoreRequest,
    composite: tuple[str, str] = Depends(parse_tx_id),
    db: ITransactionsDB = Depends(get_transactions_db),
):
    forwarded_to, date_file_name = composite
    await run_sync(db.set_ignored, forwarded_to, date_file_name, body.ignored)
    return IgnoreResponse(
        tx_id=tx_id_from_composite(forwarded_to, date_file_name),
        forwarded_to=forwarded_to,
        date_file_name=date_file_name,
        ignored=body.ignored,
    )


@router.put(
    "/transactions/{tx_id}/comment",
    response_model=CommentResponse,
    operation_id="setTransactionComment",
    summary="Set or update the user comment on a transaction",
)
async def set_comment(
    body: CommentRequest,
    request: Request,
    composite: tuple[str, str] = Depends(parse_tx_id),
    db: ITransactionsDB = Depends(get_transactions_db),
):
    forwarded_to, date_file_name = composite
    # set_comment returns the previous comment — a correct atomic before-image (L5).
    old_comment = await run_sync(db.set_comment, forwarded_to, date_file_name, body.comment)
    stage_before(
        request,
        resource="transaction",
        before={"comment": old_comment},
        after={"comment": body.comment},
        summary="updated transaction comment",
    )
    return CommentResponse(
        tx_id=tx_id_from_composite(forwarded_to, date_file_name),
        forwarded_to=forwarded_to,
        date_file_name=date_file_name,
        comment=body.comment,
    )


@router.post(
    "/transactions/{tx_id}/delete",
    response_model=DeleteResponse,
    operation_id="softDeleteTransaction",
    summary="Toggle the soft-delete flag (move to trash / restore)",
    deprecated=True,
    description=(
        "Deprecated — use `PATCH /transactions/{tx_id}` with `{state: 'trashed'}` or `{state: 'active'}` instead."
    ),
)
async def soft_delete(
    body: DeleteRequest,
    composite: tuple[str, str] = Depends(parse_tx_id),
    db: ITransactionsDB = Depends(get_transactions_db),
):
    forwarded_to, date_file_name = composite
    await run_sync(db.set_deleted, forwarded_to, date_file_name, body.deleted)
    if body.deleted:
        item = await run_sync(db.get_item, forwarded_to, date_file_name)
        deleted_at = item.get("DeletedAt") if item else None
    else:
        deleted_at = None
    return DeleteResponse(
        tx_id=tx_id_from_composite(forwarded_to, date_file_name),
        forwarded_to=forwarded_to,
        date_file_name=date_file_name,
        deleted_at=deleted_at,
    )


@router.delete(
    "/transactions/{tx_id}",
    response_model=PermanentDeleteResponse,
    operation_id="permanentlyDeleteTransaction",
    summary="Hard-delete a transaction (irreversible)",
)
async def permanent_delete(
    composite: tuple[str, str] = Depends(parse_tx_id),
    db: ITransactionsDB = Depends(get_transactions_db),
):
    forwarded_to, date_file_name = composite
    old = await run_sync(db.permanently_delete, forwarded_to, date_file_name)
    if not old:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return PermanentDeleteResponse(
        tx_id=tx_id_from_composite(forwarded_to, date_file_name),
        forwarded_to=forwarded_to,
        date_file_name=date_file_name,
    )


# ---------------------------------------------------------------------------
# Legacy composite-key shape — 308 redirect to the new tx_id surface.
#
# These handlers are intentionally `include_in_schema=False` so the
# committed openapi.json reflects only the canonical surface. Consumers
# can grep the `Deprecation: true` response header to find call sites
# that still hit the old shape. Will be removed after one release.
# ---------------------------------------------------------------------------


def _legacy_redirect(request: Request, *, forwarded_to: str, date_file_name: str, suffix: str = "") -> RedirectResponse:
    """Redirect a legacy composite-key request to the canonical tx_id URL.

    Status 308 preserves the request method and body — the browser/client
    re-issues against the new URL with the same verb and payload. The
    `Deprecation` + `Link rel=successor-version` headers signal that the
    legacy shape is on its way out.
    """
    tx_id = tx_id_from_composite(forwarded_to, date_file_name)
    new_path = f"/api/v1/transactions/{tx_id}{suffix}"
    if request.url.query:
        new_path = f"{new_path}?{request.url.query}"
    return RedirectResponse(
        url=new_path,
        status_code=308,
        headers={
            "Deprecation": "true",
            "Link": f'<{new_path}>; rel="successor-version"',
        },
    )


@router.get("/transactions/{forwarded_to}/{date_file_name}/detail", include_in_schema=False)
async def legacy_get_detail(forwarded_to: str, date_file_name: str, request: Request) -> RedirectResponse:
    return _legacy_redirect(request, forwarded_to=forwarded_to, date_file_name=date_file_name, suffix="/detail")


@router.put("/transactions/{forwarded_to}/{date_file_name}/fields", include_in_schema=False)
async def legacy_put_fields(forwarded_to: str, date_file_name: str, request: Request) -> RedirectResponse:
    return _legacy_redirect(request, forwarded_to=forwarded_to, date_file_name=date_file_name, suffix="/fields")


@router.patch("/transactions/{forwarded_to}/{date_file_name}", include_in_schema=False)
async def legacy_patch_category(forwarded_to: str, date_file_name: str, request: Request) -> RedirectResponse:
    return _legacy_redirect(request, forwarded_to=forwarded_to, date_file_name=date_file_name)


@router.post("/transactions/{forwarded_to}/{date_file_name}/review", include_in_schema=False)
async def legacy_post_review(forwarded_to: str, date_file_name: str, request: Request) -> RedirectResponse:
    return _legacy_redirect(request, forwarded_to=forwarded_to, date_file_name=date_file_name, suffix="/review")


@router.post("/transactions/{forwarded_to}/{date_file_name}/ignore", include_in_schema=False)
async def legacy_post_ignore(forwarded_to: str, date_file_name: str, request: Request) -> RedirectResponse:
    return _legacy_redirect(request, forwarded_to=forwarded_to, date_file_name=date_file_name, suffix="/ignore")


@router.put("/transactions/{forwarded_to}/{date_file_name}/comment", include_in_schema=False)
async def legacy_put_comment(forwarded_to: str, date_file_name: str, request: Request) -> RedirectResponse:
    return _legacy_redirect(request, forwarded_to=forwarded_to, date_file_name=date_file_name, suffix="/comment")


@router.post("/transactions/{forwarded_to}/{date_file_name}/delete", include_in_schema=False)
async def legacy_post_delete(forwarded_to: str, date_file_name: str, request: Request) -> RedirectResponse:
    return _legacy_redirect(request, forwarded_to=forwarded_to, date_file_name=date_file_name, suffix="/delete")


@router.delete("/transactions/{forwarded_to}/{date_file_name}", include_in_schema=False)
async def legacy_delete(forwarded_to: str, date_file_name: str, request: Request) -> RedirectResponse:
    return _legacy_redirect(request, forwarded_to=forwarded_to, date_file_name=date_file_name)
