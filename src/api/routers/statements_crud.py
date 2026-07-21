"""Statement CRUD endpoints: list, detail, delete, download, and transaction updates."""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from src.api.dependencies import get_statement_store, run_sync
from src.api.errors import ApiException
from src.api.models import (
    BulkTransactionUpdate,
    BulkTransactionUpdateResponse,
    StatementDeleteResponse,
    StatementDetailResponse,
    StatementListResponse,
    StatementSummaryItem,
    TransactionActionUpdate,
    TransactionActionUpdateResponse,
)
from src.api.routers.statement_helpers import STATEMENTS_RAW_DIR
from src.api.serializers import load_statement_detail
from src.finance.statement_store import StatementStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["statements-crud"])


@router.get(
    "/statements",
    response_model=StatementListResponse,
    operation_id="listStatements",
    summary="List all uploaded statements",
)
async def list_statements(
    store: StatementStore = Depends(get_statement_store),
):
    """List all uploaded statements."""
    rows = await run_sync(store.list_statements)
    return StatementListResponse(
        statements=[StatementSummaryItem(**r) for r in rows],
        count=len(rows),
    )


@router.get(
    "/statements/{statement_id}",
    response_model=StatementDetailResponse,
    operation_id="getStatement",
    summary="Get a statement with all its parsed transactions",
)
async def get_statement(
    statement_id: str,
    store: StatementStore = Depends(get_statement_store),
):
    """Get a statement with all its transactions."""
    return await load_statement_detail(statement_id, store)


@router.delete(
    "/statements/{statement_id}",
    response_model=StatementDeleteResponse,
    operation_id="deleteStatement",
    summary="Delete a statement and its parsed transactions",
)
async def delete_statement(
    statement_id: str,
    store: StatementStore = Depends(get_statement_store),
):
    """Delete a statement and its transactions."""
    deleted = await run_sync(store.delete_statement, statement_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Statement not found")
    return StatementDeleteResponse(ok=True)


@router.get(
    "/statements/{statement_id}/download",
    response_class=FileResponse,
    operation_id="downloadStatementPdf",
    summary="Download the original PDF for a statement",
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "Original statement PDF",
        },
        404: {"description": "Statement or PDF not found"},
    },
)
async def download_statement(
    statement_id: str,
    store: StatementStore = Depends(get_statement_store),
):
    """Download the original PDF for a statement."""
    stmt = await run_sync(store.get_statement, statement_id)
    if not stmt:
        raise HTTPException(status_code=404, detail="Statement not found")

    pdf_path = Path(stmt["pdf_path"])

    # Path traversal guard
    allowed_root = STATEMENTS_RAW_DIR.resolve()
    if not pdf_path.resolve().is_relative_to(allowed_root):
        raise HTTPException(status_code=404, detail="PDF file not found")

    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found")

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=pdf_path.name,
    )


@router.patch(
    "/statements/{statement_id}/transactions/{row_id}",
    response_model=TransactionActionUpdateResponse,
    operation_id="updateStatementTransactionAction",
    summary="Update a single statement transaction's action (auto-save), keyed by row_id",
)
async def update_transaction_action(
    statement_id: str,
    row_id: str,
    body: TransactionActionUpdate,
    store: StatementStore = Depends(get_statement_store),
):
    """Update a single transaction's action (auto-save), keyed by stable row_id.

    Pure-int paths are the legacy positional-index shape; they 410 with a
    machine-readable code so consumers can migrate. There's no safe
    redirect (no mapping from "row 5" to a stable id without the full
    statement payload).
    """
    if row_id.isdigit():
        raise ApiException(
            status_code=410,
            code="STATEMENT_ROW_INDEX_DEPRECATED",
            message="Positional index removed; use row_id from GET /statements/{id}",
            details={"statement_id": statement_id, "received": row_id},
        )

    updated = await run_sync(
        store.update_transaction_action_by_row_id,
        statement_id,
        row_id,
        body.action,
        body.company,
        body.category,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return TransactionActionUpdateResponse(
        ok=True,
        tx_index=updated["tx_index"],
        row_id=row_id,
        action=body.action,
    )


@router.patch(
    "/statements/{statement_id}/transactions",
    response_model=BulkTransactionUpdateResponse,
    operation_id="bulkUpdateStatementTransactions",
    summary="Bulk-update statement transaction actions",
)
async def bulk_update_transactions(
    statement_id: str,
    body: BulkTransactionUpdate,
    store: StatementStore = Depends(get_statement_store),
):
    """Bulk update transaction actions."""
    count = await run_sync(store.bulk_update_actions, statement_id, [u.model_dump() for u in body.updates])
    return BulkTransactionUpdateResponse(ok=True, updated=count)
