"""Local data ingestion endpoints: manual transaction entry and .eml upload."""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from src.api.dependencies import (
    get_override_service,
    get_parse_failure_store,
    get_transactions_db,
    run_sync,
)
from src.api.errors import ApiException
from src.api.models.ingestion import (
    ManualTransactionRequest,
    ManualTransactionResponse,
    UploadEmlResponse,
)
from src.api.serializers import build_manual_transaction_data, lookup_override_category
from src.finance.category_audit import build_audit
from src.finance.parse_recovery import downgrade_to_quarantined, mark_recovered, recover_or_quarantine
from src.finance.protocols import IOverrideService, IParseFailureStore, ITransactionsDB

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ingestion"])

# Cap .eml uploads to bound memory use (mirrors the import endpoint in data.py).
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


@router.post(
    "/transactions",
    response_model=ManualTransactionResponse,
    operation_id="addManualTransaction",
    summary="Add a transaction manually (bypasses email pipeline)",
)
async def add_manual_transaction(
    body: ManualTransactionRequest,
    db: ITransactionsDB = Depends(get_transactions_db),
    override_svc: IOverrideService = Depends(get_override_service),
):
    """Add a transaction manually (no email pipeline)."""
    transaction_data = await run_sync(
        lambda: build_manual_transaction_data(
            date=body.date,
            amount=body.amount,
            company=body.company,
            transaction_type=body.transaction_type,
            category=body.category,
            institution=body.institution,
            name=body.name,
            override_svc=override_svc,
        )
    )

    result = await run_sync(db.add_transaction, transaction_data, build_audit("manual"))

    if result is None:
        raise HTTPException(status_code=422, detail="Missing required fields")
    if result is False:
        raise HTTPException(status_code=409, detail="Duplicate transaction")
    assert isinstance(result, str)  # noqa: S101 — type-narrowing; False case handled above

    return ManualTransactionResponse(
        forwarded_to=str(transaction_data["forwarded_to"]),
        date_file_name=result,
        category=str(transaction_data["category"]).lower(),
        status="created",
    )


@router.post(
    "/transactions/upload-eml",
    response_model=UploadEmlResponse,
    operation_id="uploadEml",
    summary="Upload a raw .eml file and parse via the email pipeline",
)
async def upload_eml(
    file: UploadFile = File(...),
    db: ITransactionsDB = Depends(get_transactions_db),
    override_svc: IOverrideService = Depends(get_override_service),
    parse_failure_store: IParseFailureStore = Depends(get_parse_failure_store),
):
    """Upload a raw .eml file and parse it through the email pipeline."""
    if not file.filename or not file.filename.endswith(".eml"):
        raise HTTPException(status_code=422, detail="File must be a .eml file")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="Empty file")
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 50 MB upload limit")

    from src.finance.ai_client import get_ai_client
    from src.finance.email_pipeline import parse_email

    # Mirror the email pipeline: pass the AI client so a successful deterministic
    # parse still gets AI categorization. The recovery branch reuses it below.
    api_client = get_ai_client()
    try:
        result = await run_sync(parse_email, content, None, api_client)
    except Exception as e:
        logger.exception("Failed to parse .eml file")
        raise HTTPException(status_code=422, detail="Failed to parse email") from e

    recovered_failure_id: str | None = None
    if not result or not result.get("company"):
        # The parsers couldn't read it. Hand it to the recovery gate: relevant
        # emails are quarantined (so the caller learns it was kept), irrelevant
        # ones get the existing 422.
        outcome = await run_sync(recover_or_quarantine, result or {}, parse_failure_store, api_client)
        if outcome.status == "quarantined":
            raise ApiException(
                422,
                "PARSE_FAILED_QUARANTINED",
                "couldn't parse this email — saved for review",
                details={"failure_id": outcome.failure_id},
            )
        if outcome.status == "recovered" and outcome.result is not None:
            result = outcome.result
            recovered_failure_id = outcome.failure_id
        else:
            raise HTTPException(status_code=422, detail="Could not extract transaction from email")

    # Categorize
    category = result.get("category", "miscellaneous")
    if not category or category == "miscellaneous":
        override_cat = await run_sync(lookup_override_category, result.get("company", ""), override_svc)
        if override_cat:
            category = override_cat

    result["category"] = category

    # Write to DB — propagate the audit stamped by categorize_transactions
    # (either an override match, or an ai/ai_fallback audit from the AI path).
    # Pop BOTH provenance keys — neither may reach the DB as a literal field.
    extraction_audit = result.pop("_extraction_audit", None)
    category_audit = result.pop("_category_audit", None)
    db_result = await run_sync(db.add_transaction, result, category_audit, extraction_audit)

    if db_result is None:
        if recovered_failure_id is not None:
            # Extraction recovered a transaction but the DB rejected it — downgrade
            # the pre-marked "recovered" row rather than lose the capture.
            await run_sync(downgrade_to_quarantined, parse_failure_store, recovered_failure_id)
        raise HTTPException(status_code=422, detail="Could not store transaction — missing required fields")
    if db_result is False:
        return UploadEmlResponse(status="duplicate", detail="Transaction already exists")
    assert isinstance(db_result, str)  # noqa: S101 — type-narrowing; False case handled above

    # A recovered transaction landed — flip its quarantine row to "recovered".
    if recovered_failure_id is not None:
        await run_sync(mark_recovered, parse_failure_store, recovered_failure_id, db_result)

    return UploadEmlResponse(
        status="created",
        date_file_name=db_result,
        company=result.get("company"),
        amount=result.get("amount"),
        category=category,
    )
