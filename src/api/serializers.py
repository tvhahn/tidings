"""Shared, router-free helpers for transaction-shaped payloads.

Router modules import these instead of importing one another: the
transaction-list rendering primitives (projection constants, the item→response
mapper, the attention predicate), the manual-transaction builder, the
override-category lookup, and the statement-detail loader all live in one
router-free place. **This module must never import a router module** — that is
the whole point of extracting it (see audit T-24 / A10).
"""

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from src.api.dependencies import run_sync
from src.api.models import (
    CategoryAudit,
    ExtractionAudit,
    StatementDetailResponse,
    StatementTransactionItem,
    TransactionContext,
    TransactionResponse,
)
from src.finance.app_timezone import get_app_timezone
from src.finance.category_audit import MANUAL_SOURCES, normalize_audit
from src.finance.config_loader import get_override_context
from src.finance.decimal_utils import decimal_to_float
from src.finance.protocols import IOverrideService
from src.finance.statement_store import StatementStore
from src.finance.tx_id import tx_id_from_composite

# Projection for the combined/bulk endpoints — only fetch the attributes
# needed by to_transaction_response and _split_items, skipping large fields like
# Body, Subject, FileName, and email header fields.
TRANSACTION_LIST_PROJECTION = (
    "ForwardedTo, DateFileName, #d, Amount, Company, Category, Institution, "
    "TransactionType, #n, CategoryAudit, ExtractionAudit, Ignored, #c, DeletedAt, "
    "TransactionContext, StatementSource"
)
PROJECTION_NAMES = {"#d": "Date", "#n": "Name", "#c": "Comment"}


def is_attention(item: Mapping[str, Any]) -> bool:
    """Attention bucket: rows that need human review.

    Two independent reasons land a row here:

    1. **AI-extracted rows** (``ExtractionAudit`` present): a transaction the
       parsers couldn't read but the AI extraction fallback recovered. It
       needs a human glance until the user touches it. The existing reviewed
       flow (``PATCH /transactions/{tx_id}`` with ``{reviewed: true}`` →
       ``mark_category_reviewed(..., "manual")``) clears it with zero changes,
       so any manual ``CategoryAudit`` source — ``manual``, ``manual_edit``,
       ``manual_bulk``, ``audit`` — drops it from the queue.
    2. **Miscellaneous rows**: category is miscellaneous AND either no audit
       has been written yet OR the audit shows the AI categorizer fell back to
       Miscellaneous (any ``source == "ai_fallback"``). Manually-set
       miscellaneous rows and override-matched ones are excluded — the user
       has already touched them.

    Ignored and trashed rows are never in attention.
    """
    if item.get("Ignored") or item.get("DeletedAt"):
        return False
    extraction = item.get("ExtractionAudit")
    if extraction:
        audit = item.get("CategoryAudit") or {}
        if audit.get("source") not in MANUAL_SOURCES:
            return True
    if (item.get("Category") or "").lower() != "miscellaneous":
        return False
    audit = item.get("CategoryAudit")
    if not audit:
        return True
    return audit.get("source") == "ai_fallback"


def to_transaction_response(item: Mapping[str, Any]) -> TransactionResponse:
    """Convert a raw DynamoDB item to a TransactionResponse."""
    amount = decimal_to_float(item.get("Amount"))

    raw_audit = item.get("CategoryAudit")
    normalized = normalize_audit(dict(raw_audit)) if raw_audit else None
    audit = CategoryAudit(**normalized) if normalized else None

    raw_extraction = item.get("ExtractionAudit")
    extraction_audit = ExtractionAudit(**dict(raw_extraction)) if raw_extraction else None

    # Map TransactionContext from DynamoDB (Decimal → float)
    raw_ctx = item.get("TransactionContext")
    context = None
    if raw_ctx:
        context = TransactionContext(
            category_month_total=float(raw_ctx.get("category_month_total", 0)),
            merchant_month_count=int(raw_ctx.get("merchant_month_count", 0)),
            category_budget_target=float(raw_ctx["category_budget_target"])
            if raw_ctx.get("category_budget_target") is not None
            else None,
            category_budget_pct=float(raw_ctx["category_budget_pct"])
            if raw_ctx.get("category_budget_pct") is not None
            else None,
        )

    forwarded_to = item["ForwardedTo"]
    date_file_name = item["DateFileName"]
    return TransactionResponse(
        tx_id=tx_id_from_composite(forwarded_to, date_file_name),
        forwarded_to=forwarded_to,
        date_file_name=date_file_name,
        date=item.get("Date"),
        amount=amount,
        company=item.get("Company"),
        category=item.get("Category"),
        institution=item.get("Institution"),
        transaction_type=item.get("TransactionType"),
        name=item.get("Name"),
        category_audit=audit,
        extraction_audit=extraction_audit,
        ignored=bool(item.get("Ignored", False)),
        comment=item.get("Comment"),
        deleted_at=item.get("DeletedAt"),
        context=context,
        statement_source=item.get("StatementSource"),
    )


def lookup_override_category(company: str, override_svc: IOverrideService) -> str | None:
    """Resolve a company to an override category (Tier 0/1/2) off the event loop.

    Bundles the two blocking storage reads (``get_override_context`` + the
    override-service lookup) so the caller can offload both in a single
    ``run_sync`` hop. Shared by the manual-fields update (transactions) and the
    ``.eml`` upload (ingestion) paths.
    """
    _, aliases = get_override_context()
    return override_svc.lookup_category(company, aliases=aliases)


def build_manual_transaction_data(
    *,
    date: str,
    amount: float,
    company: str,
    transaction_type: str,
    category: str | None,
    institution: str | None,
    name: str | None,
    override_svc: IOverrideService,
) -> dict[str, object]:
    """Build the storage dict ``add_transaction`` expects from hand-entered fields.

    Shared by the manual-add endpoint (``POST /transactions``) and the
    parse-failure manual-resolve endpoint. Both record a transaction the user
    typed by hand; only the surrounding flow differs (resolve also flips the
    quarantine row). Keeping the dict-build in one place stops the synthesized
    keys, the override-based category fallback, and the timezone-aware date
    conversion from drifting apart.

    Auto-categorizes via overrides when ``category`` is omitted, falling back to
    ``"miscellaneous"``. Raises ``HTTPException(422)`` when ``date`` is not
    ``YYYY-MM-DD``.
    """
    from src.finance.app_config import get_config
    from src.finance.user_mapping import local_forwarded_to

    config = get_config()
    forwarded_to = local_forwarded_to()

    # Auto-categorize via overrides if category not provided.
    resolved_category = category
    if not resolved_category:
        _, aliases = get_override_context()
        resolved_category = override_svc.lookup_category(company, aliases=aliases)
        if not resolved_category:
            resolved_category = "miscellaneous"

    # Generate synthetic DateFileName seed.
    hash_input = f"{forwarded_to}|manual|{amount:.2f}|{company}|{date}|{transaction_type}"
    hash8 = hashlib.sha256(hash_input.encode()).hexdigest()[:8]

    # Parse date (YYYY-MM-DD format).
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")  # noqa: DTZ007 — naive parse localized on the next line via .replace(tzinfo=get_app_timezone())
    except ValueError as e:
        raise HTTPException(status_code=422, detail="Date must be YYYY-MM-DD format") from e

    synthetic_date = dt.replace(tzinfo=get_app_timezone()).strftime("%m/%d/%Y %H:%M %z")

    return {
        "forwarded_to": forwarded_to,
        "file_name": f"manual_{hash8}.eml",
        "date": synthetic_date,
        "amount": amount,
        "company": company,
        "category": resolved_category,
        "transaction_type": transaction_type,
        "institution": institution or "Manual",
        "name": name or config.get("user_id", "default"),
    }


async def load_statement_detail(statement_id: str, store: StatementStore) -> StatementDetailResponse:
    """Load a statement plus its parsed transactions as a StatementDetailResponse.

    Extracted from the ``GET /statements/{id}`` endpoint so the reparse endpoint
    can return the identical detail payload without importing the CRUD router.
    Keeps the 404 raises with it (statement missing → 404).
    """
    stmt = await run_sync(store.get_statement, statement_id)
    if not stmt:
        raise HTTPException(status_code=404, detail="Statement not found")

    txn_rows = await run_sync(store.get_transactions, statement_id)
    transactions = []
    for row in txn_rows:
        candidates = None
        if row.get("candidates_json"):
            try:
                candidates = json.loads(row["candidates_json"])
            except (json.JSONDecodeError, TypeError):
                candidates = None
        transactions.append(
            StatementTransactionItem(
                tx_index=row["tx_index"],
                row_id=row["row_id"],
                reconcile_tier=row["reconcile_tier"],
                date=row["date"],
                raw_description=row["raw_description"],
                cleaned_description=row["cleaned_description"],
                amount=row["amount"],
                type=row["type"],
                balance=row.get("balance"),
                db_forwarded_to=row.get("db_forwarded_to"),
                db_date_file_name=row.get("db_date_file_name"),
                db_company=row.get("db_company"),
                db_amount=row.get("db_amount"),
                db_category=row.get("db_category"),
                db_transaction_type=row.get("db_transaction_type"),
                company_differs=bool(row.get("company_differs")),
                enrichable=bool(row.get("enrichable")),
                reason=row.get("reason"),
                candidates=candidates,
                suggested_category=row.get("suggested_category", "miscellaneous"),
                action=row.get("action", "skip"),
                edited_company=row.get("edited_company"),
                edited_category=row.get("edited_category"),
                action_result=row.get("action_result"),
                acted_at=row.get("acted_at"),
            )
        )

    return StatementDetailResponse(
        **stmt,
        transactions=transactions,
    )
