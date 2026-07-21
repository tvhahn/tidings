"""Statement orchestration endpoints: upload PDF, reparse, and import."""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from src.api.dependencies import (
    get_embedding_cache,
    get_openai_client,
    get_spending_summary,
    get_statement_store,
    get_transactions_db,
    run_sync,
)
from src.api.models import (
    AmbiguousItem,
    ImportRequest,
    ImportResponse,
    MatchedItem,
    NewItem,
    PreviouslyImportedItem,
    ReconcileSummary,
    StatementDetailResponse,
    StatementMetadata,
    StatementTransaction,
    StatementUploadResponse,
    SuspectedDuplicateItem,
)
from src.api.routers.statement_helpers import (
    STATEMENTS_RAW_DIR,
    _safe_filename_component,
)
from src.api.routers.statement_helpers import (
    append_import_history as _append_import_history,
)
from src.api.routers.statement_helpers import (
    build_transaction_rows as _build_transaction_rows,
)
from src.api.routers.statement_helpers import (
    get_forwarded_to as _get_forwarded_to,
)
from src.api.routers.statement_helpers import (
    get_user_id as _get_user_id,
)
from src.api.routers.statement_helpers import (
    parse_and_reconcile as _parse_and_reconcile,
)
from src.api.routers.statement_helpers import (
    standardized_pdf_name as _standardized_pdf_name,
)
from src.api.routers.statement_helpers import (
    was_category_edited as _was_category_edited,
)
from src.api.serializers import load_statement_detail
from src.finance.embedding_cache import EmbeddingCache
from src.finance.openai_client import OpenAIClient
from src.finance.protocols import ISpendingSummary, ITransactionsDB
from src.finance.statement_parser import validate_pdf
from src.finance.statement_store import StatementStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["statements"])


@router.post(
    "/statements/upload",
    response_model=StatementUploadResponse,
    operation_id="uploadStatement",
    summary="Upload a PDF statement, parse, and reconcile against transactions",
)
async def upload_statement(
    file: UploadFile = File(...),
    summary: ISpendingSummary = Depends(get_spending_summary),
    store: StatementStore = Depends(get_statement_store),
    openai_client: OpenAIClient | None = Depends(get_openai_client),
    embedding_cache: EmbeddingCache = Depends(get_embedding_cache),
):
    """Upload a PDF statement, parse it, and reconcile against DynamoDB."""
    # Validate file extension
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="Only PDF files are accepted")

    # Read file bytes
    pdf_bytes = await file.read()

    # Validate PDF
    error = validate_pdf(pdf_bytes)
    if error:
        raise HTTPException(status_code=422, detail=error)

    # Shared middle: parse (AI fallback), reconcile, build reconciliation items
    result, _reconcile_result, (matched_d, ambiguous_d, new_d, prev_d, dup_d) = await _parse_and_reconcile(
        pdf_bytes,
        run_sync=run_sync,
        summary=summary,
        openai_client=openai_client,
        embedding_cache=embedding_cache,
    )

    # Save PDF to data/raw/statements/<institution>/
    save_dir = STATEMENTS_RAW_DIR / _safe_filename_component(result.metadata["institution"])
    save_dir.mkdir(parents=True, exist_ok=True)
    pdf_name = _standardized_pdf_name(
        result.metadata["institution"],
        result.metadata["account_type"],
        result.metadata.get("period_start"),
        result.metadata.get("period_end"),
        file.filename,
    )
    save_path = save_dir / pdf_name
    # Mirror the download-side traversal guard (statements_crud.py) on the
    # write side: nothing may land outside the statements tree.
    if not save_path.resolve().is_relative_to(STATEMENTS_RAW_DIR.resolve()):
        raise HTTPException(status_code=422, detail="Unsafe filename")
    save_path.write_bytes(pdf_bytes)

    # Build response
    stmt_transactions = []
    for i, txn in enumerate(result.transactions):
        stmt_transactions.append(
            StatementTransaction(
                date=txn["date"],
                description=txn["description"],
                cleaned_description=result.cleaned_descriptions[i],
                amount=txn["amount"],
                type=txn["type"],
                balance=txn.get("balance"),
            )
        )

    matched = [MatchedItem(**d) for d in matched_d]
    ambiguous = [AmbiguousItem(**d) for d in ambiguous_d]
    new = [NewItem(**d) for d in new_d]
    previously_imported = [PreviouslyImportedItem(**d) for d in prev_d]
    suspected_duplicates = [SuspectedDuplicateItem(**d) for d in dup_d]

    summary_counts = ReconcileSummary(
        total_parsed=len(result.transactions),
        matched_count=len(matched),
        ambiguous_count=len(ambiguous),
        suspected_duplicate_count=len(suspected_duplicates),
        new_count=len(new),
        previously_imported_count=len(previously_imported),
    )

    metadata = StatementMetadata(**result.metadata)

    # Persist to SQLite
    statement_id = StatementStore.generate_statement_id(
        metadata.institution,
        metadata.account_type,
        metadata.period_start,
        metadata.period_end,
        file.filename,
    )
    statement_dict = {
        "id": statement_id,
        "filename": pdf_name,
        "institution": metadata.institution,
        "account_type": metadata.account_type,
        "period_start": metadata.period_start,
        "period_end": metadata.period_end,
        "pdf_path": str(save_path),
        "total_parsed": summary_counts.total_parsed,
        "matched_count": summary_counts.matched_count,
        "ambiguous_count": summary_counts.ambiguous_count,
        "suspected_duplicate_count": summary_counts.suspected_duplicate_count,
        "new_count": summary_counts.new_count,
        "previously_imported_count": summary_counts.previously_imported_count,
        "parsed_with_ai": metadata.parsed_with_ai,
    }
    tx_rows = _build_transaction_rows(
        [m.model_dump() for m in matched],
        [a.model_dump() for a in ambiguous],
        [n.model_dump() for n in new],
        [p.model_dump() for p in previously_imported],
        [sd.model_dump() for sd in suspected_duplicates],
    )
    await run_sync(store.save_statement, statement_dict, tx_rows)

    return StatementUploadResponse(
        statement_id=statement_id,
        transactions=stmt_transactions,
        metadata=metadata,
        matched=matched,
        ambiguous=ambiguous,
        suspected_duplicates=suspected_duplicates,
        new=new,
        previously_imported=previously_imported,
        summary=summary_counts,
    )


@router.post(
    "/statements/{statement_id}/reparse",
    response_model=StatementDetailResponse,
    operation_id="reparseStatement",
    summary="Re-parse a statement PDF, preserving prior user edits",
)
async def reparse_statement(
    statement_id: str,
    store: StatementStore = Depends(get_statement_store),
    summary: ISpendingSummary = Depends(get_spending_summary),
    openai_client: OpenAIClient | None = Depends(get_openai_client),
    embedding_cache: EmbeddingCache = Depends(get_embedding_cache),
):
    """Re-parse a statement PDF and reconcile, preserving user edits."""
    stmt = await run_sync(store.get_statement, statement_id)
    if not stmt:
        raise HTTPException(status_code=404, detail="Statement not found")

    pdf_path = Path(stmt["pdf_path"])
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found")

    # Preserve user edits before re-parsing
    old_txns = await run_sync(store.get_transactions, statement_id)
    edit_lookup: dict[tuple[Any, ...], dict[str, Any]] = {}
    for t in old_txns:
        key = (t["date"], t["amount"], t["raw_description"])
        edit_lookup[key] = {
            "edited_company": t.get("edited_company"),
            "edited_category": t.get("edited_category"),
            "action": t.get("action"),
        }

    # Re-parse + re-reconcile — the shared middle upload also runs.
    pdf_bytes = pdf_path.read_bytes()
    (
        result,
        _reconcile_result,
        (
            matched_items,
            ambiguous_items,
            new_items,
            prev_imported_items,
            suspected_dup_items,
        ),
    ) = await _parse_and_reconcile(
        pdf_bytes,
        run_sync=run_sync,
        summary=summary,
        openai_client=openai_client,
        embedding_cache=embedding_cache,
    )

    # Build transaction rows and carry over user edits
    tx_rows = _build_transaction_rows(
        matched_items,
        ambiguous_items,
        new_items,
        prev_imported_items,
        suspected_dup_items,
    )
    for row in tx_rows:
        key = (row["date"], row["amount"], row.get("raw_description", ""))
        edits = edit_lookup.get(key)
        if edits:
            if edits.get("edited_company"):
                row["edited_company"] = edits["edited_company"]
            if edits.get("edited_category"):
                row["edited_category"] = edits["edited_category"]
            if edits.get("action"):
                row["action"] = edits["action"]

    metadata = result.metadata
    statement_dict = {
        "id": statement_id,
        "filename": _standardized_pdf_name(
            metadata["institution"],
            metadata["account_type"],
            metadata.get("period_start"),
            metadata.get("period_end"),
            stmt["filename"],
        ),
        "institution": metadata["institution"],
        "account_type": metadata["account_type"],
        "period_start": metadata.get("period_start"),
        "period_end": metadata.get("period_end"),
        "pdf_path": str(pdf_path),
        "total_parsed": len(result.transactions),
        "matched_count": len(matched_items),
        "ambiguous_count": len(ambiguous_items),
        "suspected_duplicate_count": len(suspected_dup_items),
        "new_count": len(new_items),
        "previously_imported_count": len(prev_imported_items),
        "parsed_with_ai": bool(metadata.get("parsed_with_ai", False)),
    }
    await run_sync(store.save_statement, statement_dict, tx_rows)

    return await load_statement_detail(statement_id, store)


@router.post(
    "/statements/import",
    response_model=ImportResponse,
    operation_id="importStatementTransactions",
    summary="Execute import/enrich/update actions for statement transactions",
)
async def import_transactions(
    body: ImportRequest,
    db: ITransactionsDB = Depends(get_transactions_db),
    store: StatementStore = Depends(get_statement_store),
):
    """Execute import actions for statement transactions."""
    imported = 0
    skipped = 0
    duplicates = 0
    enriched = 0
    updated = 0

    forwarded_to = _get_forwarded_to()
    user_id = _get_user_id(forwarded_to)

    # Build statement source string
    period_start = body.metadata.period_start or ""
    # Extract YYYY-MM from period_end for source identifier
    period_month = period_start[:7] if period_start else ""
    statement_source = f"{body.metadata.institution}_{body.metadata.account_type.title()}_{period_month}"

    import_results: list[dict[str, Any]] = []

    # Load SQLite rows for category-edit detection
    tx_lookup: dict[int, dict[str, Any]] = {}
    if body.statement_id:
        try:
            tx_rows = await run_sync(store.get_transactions, body.statement_id)
            tx_lookup = {r["tx_index"]: r for r in tx_rows}
        except Exception:
            # Fail-open: if lookup fails, use default sources
            logger.warning(
                "category-edit lookup failed for statement %s; using default statement sources",
                body.statement_id,
            )

    # Track occurrences of identical transactions for dedup disambiguation
    import_hash_counter: dict[tuple[Any, ...], int] = {}

    for action in body.actions:
        if action.action == "update":
            # Update an existing previously-imported DB record
            if not action.forwarded_to or not action.date_file_name:
                skipped += 1
                import_results.append({"tx_index": action.index, "action_result": "skipped"})
                continue
            company = action.company or ""
            category = action.category or "miscellaneous"
            audit_src = "manual" if _was_category_edited(tx_lookup, action.index) else "statement_reimport"
            await run_sync(
                db.enrich_transaction,
                action.forwarded_to,
                action.date_file_name,
                company,
                category,
                source=audit_src,
                statement_source=statement_source,
            )
            updated += 1
            import_results.append({"tx_index": action.index, "action_result": "updated"})
            continue

        if action.action == "enrich":
            # Enrich an existing DB record with statement description data
            if not action.forwarded_to or not action.date_file_name:
                skipped += 1
                import_results.append({"tx_index": action.index, "action_result": "skipped"})
                continue
            company = action.company or ""
            category = action.category or "miscellaneous"
            audit_src = "manual" if _was_category_edited(tx_lookup, action.index) else "statement_enrich"
            await run_sync(
                db.enrich_transaction,
                action.forwarded_to,
                action.date_file_name,
                company,
                category,
                source=audit_src,
                statement_source=statement_source,
            )
            enriched += 1
            import_results.append({"tx_index": action.index, "action_result": "enriched"})
            continue

        if action.action != "import":
            skipped += 1
            import_results.append({"tx_index": action.index, "action_result": "skipped"})
            continue

        if action.index < 0 or action.index >= len(body.transactions):
            skipped += 1
            import_results.append({"tx_index": action.index, "action_result": "skipped"})
            continue

        txn = body.transactions[action.index]
        company = action.company or txn.cleaned_description or txn.description
        category = action.category or "miscellaneous"

        # Compute occurrence index for identical same-day transactions
        raw_desc = txn.description or company
        hash_key = (txn.date, txn.amount, raw_desc, txn.type)
        occurrence = import_hash_counter.get(hash_key, 0)
        import_hash_counter[hash_key] = occurrence + 1

        txn_data = {
            "forwarded_to": forwarded_to,
            "date": txn.date,
            "amount": txn.amount,
            "company": company,
            "institution": body.metadata.institution,
            "transaction_type": txn.type,
            "category": category,
            "statement_source": statement_source,
            "raw_description": raw_desc,
            "occurrence": occurrence,
        }
        if user_id:
            txn_data["user_id"] = user_id

        audit_src = "manual" if _was_category_edited(tx_lookup, action.index) else "statement_import"
        result = await run_sync(db.add_statement_transaction, txn_data, audit_src)
        if result is False:
            duplicates += 1
            import_results.append({"tx_index": action.index, "action_result": "duplicate"})
        elif result is None:
            skipped += 1
            import_results.append({"tx_index": action.index, "action_result": "skipped"})
        else:
            imported += 1
            import_results.append({"tx_index": action.index, "action_result": "imported"})

    # Record import results in SQLite if statement_id available
    statement_id = body.statement_id
    if statement_id and import_results:
        try:
            await run_sync(store.record_import_results, statement_id, import_results)
        except Exception:
            logger.warning("Failed to record import results for %s", statement_id, exc_info=True)

    # Append to import history
    _append_import_history(
        body.filename,
        body.metadata,
        len(body.transactions),
        imported,
        skipped,
        duplicates,
    )

    return ImportResponse(imported=imported, skipped=skipped, duplicates=duplicates, enriched=enriched, updated=updated)
