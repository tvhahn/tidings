"""Attachment endpoints: upload, list, download, link, and delete receipts/documents.

Files are validated against a small allowlist (image types + PDF), HEIC/HEIF are
converted to JPEG at upload, and the canonical content-type we store — never the
client's raw header — is what we serve back. Rows reference transactions by the
persisted composite; the ``tx_id`` surrogate is decoded at this boundary only.

The parse + candidate endpoints (L5) run the receipt AI inline: parse persists the
structured result, candidates rank the transactions a receipt might explain and
auto-link the sole tier-1 match of an unlinked receipt.
"""

import calendar
import hashlib
import io
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pillow_heif
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image

from src.api.dependencies import (
    ensure_not_demo,
    get_attachment_store,
    get_merchant_alias_service,
    get_openai_client,
    get_spending_summary,
    run_sync,
)
from src.api.models import (
    AttachmentDeleteResponse,
    AttachmentListResponse,
    AttachmentResponse,
    LinkAttachmentRequest,
    ReceiptCandidate,
    ReceiptCandidatesResponse,
)
from src.api.utils import parse_tx_id, sanitize_filename
from src.finance import app_config
from src.finance.app_timezone import get_app_timezone
from src.finance.attachment_store import ATTACHMENTS_RAW_DIR, AttachmentStore, attachment_id_for
from src.finance.openai_client import OpenAIClient
from src.finance.protocols import IMerchantAliasService, ISpendingSummary, TransactionItem
from src.finance.receipt_matcher import RECEIPT_DATE_WINDOW_DAYS, find_candidates
from src.finance.receipt_parser_ai import ReceiptAIError, parse_receipt
from src.finance.statement_parser_base import MAX_PDF_SIZE
from src.finance.tx_id import tx_id_from_composite

logger = logging.getLogger(__name__)

# Pillow needs the HEIF opener registered before it can decode .heic/.heif bytes.
pillow_heif.register_heif_opener()

router = APIRouter(tags=["attachments"])

# L4 allowlist: file extension → the canonical content-type we store and serve.
# HEIC/HEIF are accepted for upload but stored as JPEG (see _validate_and_read).
_EXT_CONTENT_TYPES: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".pdf": "application/pdf",
}
_HEIF_EXTS = {".heic", ".heif"}
_VALID_KINDS = {"receipt", "document"}


def _convert_heif_to_jpeg(data: bytes) -> bytes:
    """Decode HEIC/HEIF bytes and re-encode as JPEG."""
    with Image.open(io.BytesIO(data)) as image:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=90)
        return buffer.getvalue()


def _validate_and_read(file: UploadFile, raw: bytes) -> tuple[bytes, str]:
    """Validate the upload against the L4 allowlist; return (stored_bytes, content_type).

    HEIC/HEIF are converted to JPEG here, so the returned bytes/type are always
    what lands on disk and in the row.
    """
    filename = file.filename or ""
    ext = Path(filename).suffix.lower()
    expected_type = _EXT_CONTENT_TYPES.get(ext)
    if expected_type is None:
        raise HTTPException(
            status_code=400,
            detail="Only image receipts (JPEG, PNG, WebP, HEIC) or PDF files can be attached.",
        )
    # The declared content-type must line up with the extension; we never trust
    # the client's raw header for what we store or later serve.
    declared = (file.content_type or "").split(";")[0].strip().lower()
    if declared and declared != expected_type:
        raise HTTPException(
            status_code=400,
            detail="The file's type does not match its extension.",
        )
    if len(raw) > MAX_PDF_SIZE:
        raise HTTPException(
            status_code=400,
            detail="The file is larger than the 10 MB limit.",
        )
    if ext in _HEIF_EXTS:
        try:
            stored = _convert_heif_to_jpeg(raw)
        except Exception as exc:  # pragma: no cover - defensive; codec issues
            logger.warning("HEIC/HEIF conversion failed: %s", exc)
            raise HTTPException(status_code=400, detail="That HEIC image could not be read.") from exc
        return stored, "image/jpeg"
    return raw, expected_type


def _to_response(row: dict[str, Any]) -> AttachmentResponse:
    """Build the API view of a stored row, computing tx_id from the composite."""
    forwarded_to = row.get("forwarded_to")
    date_file_name = row.get("date_file_name")
    tx_id = tx_id_from_composite(forwarded_to, date_file_name) if forwarded_to and date_file_name else None
    parse_json = row.get("parse_json")
    parsed: dict[str, Any] | None = None
    if parse_json:
        try:
            decoded = json.loads(parse_json)
            parsed = decoded if isinstance(decoded, dict) else None
        except (ValueError, TypeError):
            parsed = None
    return AttachmentResponse(
        id=row["id"],
        original_filename=row["original_filename"],
        content_type=row["content_type"],
        size_bytes=row["size_bytes"],
        sha256=row["sha256"],
        kind=row["kind"],
        tx_id=tx_id,
        parse_status=row["parse_status"],
        parse_json=parsed,
        parse_error=row.get("parse_error"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.post(
    "/attachments",
    response_model=AttachmentResponse,
    operation_id="uploadAttachment",
    summary="Upload a receipt or document, optionally linked to a transaction",
)
async def upload_attachment(
    file: UploadFile = File(...),
    tx_id: str | None = Form(None),
    kind: str = Form("receipt"),
    store: AttachmentStore = Depends(get_attachment_store),
) -> AttachmentResponse:
    """Store an uploaded receipt/document; link it immediately when ``tx_id`` is given."""
    ensure_not_demo("Attachments are read-only in the demo.")
    if kind not in _VALID_KINDS:
        raise HTTPException(status_code=400, detail="Attachment kind must be 'receipt' or 'document'.")

    forwarded_to: str | None = None
    date_file_name: str | None = None
    if tx_id:
        forwarded_to, date_file_name = parse_tx_id(tx_id)

    raw = await file.read()
    stored_bytes, content_type = _validate_and_read(file, raw)

    original_filename = file.filename or "receipt"
    sha256 = hashlib.sha256(stored_bytes).hexdigest()
    attachment_id = attachment_id_for(sha256, original_filename)

    month = datetime.now(get_app_timezone()).strftime("%Y-%m")
    dest_dir = ATTACHMENTS_RAW_DIR / month
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{attachment_id}_{sanitize_filename(original_filename)}"
    await run_sync(dest_path.write_bytes, stored_bytes)

    store.save_attachment(
        {
            "original_filename": original_filename,
            "content_type": content_type,
            "size_bytes": len(stored_bytes),
            "sha256": sha256,
            "file_path": str(dest_path),
            "kind": kind,
            "forwarded_to": forwarded_to,
            "date_file_name": date_file_name,
        }
    )
    row = store.get_attachment(attachment_id)
    assert row is not None  # noqa: S101 — type-narrowing; None case handled above (just written)
    return _to_response(row)


@router.get(
    "/attachments",
    response_model=AttachmentListResponse,
    operation_id="listAttachments",
    summary="List attachments, optionally filtered by link status and kind",
)
async def list_attachments(
    unlinked: bool | None = None,
    kind: str | None = None,
    store: AttachmentStore = Depends(get_attachment_store),
) -> AttachmentListResponse:
    rows = await run_sync(store.list_attachments, unlinked=unlinked, kind=kind)
    items = [_to_response(r) for r in rows]
    return AttachmentListResponse(count=len(items), attachments=items)


@router.get(
    "/transactions/{tx_id}/attachments",
    response_model=AttachmentListResponse,
    operation_id="listTransactionAttachments",
    summary="List attachments linked to a transaction",
)
async def list_transaction_attachments(
    composite: tuple[str, str] = Depends(parse_tx_id),
    store: AttachmentStore = Depends(get_attachment_store),
) -> AttachmentListResponse:
    forwarded_to, date_file_name = composite
    rows = await run_sync(store.list_for_transaction, forwarded_to, date_file_name)
    items = [_to_response(r) for r in rows]
    return AttachmentListResponse(count=len(items), attachments=items)


@router.get(
    "/attachments/{attachment_id}/file",
    operation_id="downloadAttachmentFile",
    summary="Download the attachment file, served inline with our stored content-type",
)
async def download_attachment_file(
    attachment_id: str,
    store: AttachmentStore = Depends(get_attachment_store),
) -> FileResponse:
    row = await run_sync(store.get_attachment, attachment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    path = Path(row["file_path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Attachment file not found on disk.")
    return FileResponse(
        str(path),
        media_type=row["content_type"],
        filename=row["original_filename"],
        content_disposition_type="inline",
    )


@router.post(
    "/attachments/{attachment_id}/link",
    response_model=AttachmentResponse,
    operation_id="linkAttachment",
    summary="Link an attachment to a transaction, or unlink it",
)
async def link_attachment(
    attachment_id: str,
    body: LinkAttachmentRequest,
    store: AttachmentStore = Depends(get_attachment_store),
) -> AttachmentResponse:
    ensure_not_demo("Attachments are read-only in the demo.")
    forwarded_to: str | None = None
    date_file_name: str | None = None
    if body.tx_id:
        forwarded_to, date_file_name = parse_tx_id(body.tx_id)
    updated = await run_sync(store.set_link, attachment_id, forwarded_to, date_file_name)
    if not updated:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    row = await run_sync(store.get_attachment, attachment_id)
    assert row is not None  # noqa: S101 — type-narrowing; None case handled above (set_link confirmed it exists)
    return _to_response(row)


@router.delete(
    "/attachments/{attachment_id}",
    response_model=AttachmentDeleteResponse,
    operation_id="deleteAttachment",
    summary="Delete an attachment and its file from disk",
)
async def delete_attachment(
    attachment_id: str,
    store: AttachmentStore = Depends(get_attachment_store),
) -> AttachmentDeleteResponse:
    ensure_not_demo("Attachments are read-only in the demo.")
    row = await run_sync(store.delete_attachment, attachment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    path = Path(row["file_path"])
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:  # pragma: no cover - defensive
        logger.warning("Failed to remove attachment file %s: %s", path, exc)
    return AttachmentDeleteResponse(id=attachment_id, status="deleted")


@router.post(
    "/attachments/{attachment_id}/parse",
    response_model=AttachmentResponse,
    operation_id="parseReceipt",
    summary="Parse a receipt attachment with the configured AI provider",
)
async def parse_receipt_attachment(
    attachment_id: str,
    store: AttachmentStore = Depends(get_attachment_store),
    openai_client: OpenAIClient | None = Depends(get_openai_client),
) -> AttachmentResponse:
    """Send the receipt to the user's AI provider and persist the parsed result.

    Synchronous (the statement-upload precedent runs AI inline). Requires the
    ``ai_receipt_parsing_enabled`` consent; failures persist ``parse_status=failed``
    with the error and return 422.
    """
    ensure_not_demo("Attachments are read-only in the demo.")
    if not app_config.get_config().get("ai_receipt_parsing_enabled", False):
        raise HTTPException(
            status_code=422,
            detail=(
                'Receipt parsing is off. Turn on "Parse receipts with AI" in '
                "Settings → Intelligence to read this receipt with your AI provider."
            ),
        )
    row = await run_sync(store.get_attachment, attachment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Attachment not found.")

    try:
        parsed = await parse_receipt(row["file_path"], row["content_type"], openai_client)
    except ReceiptAIError as exc:
        await run_sync(
            store.set_parse_result,
            attachment_id,
            status="failed",
            parse_json=None,
            error=str(exc),
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await run_sync(
        store.set_parse_result,
        attachment_id,
        status="parsed",
        parse_json=json.dumps(parsed),
        error=None,
    )
    updated = await run_sync(store.get_attachment, attachment_id)
    assert updated is not None  # noqa: S101 — type-narrowing; None case handled above (just written)
    return _to_response(updated)


def _candidate_months(receipt_date: date) -> list[str]:
    """Months to query for candidates: the receipt month plus an adjacent month
    when the receipt date is within the matcher's window of a boundary (L8)."""
    months = {receipt_date.strftime("%Y-%m")}
    if receipt_date.day <= RECEIPT_DATE_WINDOW_DAYS:
        prev = receipt_date.replace(day=1) - timedelta(days=1)
        months.add(prev.strftime("%Y-%m"))
    last_day = calendar.monthrange(receipt_date.year, receipt_date.month)[1]
    if last_day - receipt_date.day < RECEIPT_DATE_WINDOW_DAYS:
        nxt = receipt_date.replace(day=last_day) + timedelta(days=1)
        months.add(nxt.strftime("%Y-%m"))
    return sorted(months)


@router.get(
    "/attachments/{attachment_id}/candidates",
    response_model=ReceiptCandidatesResponse,
    operation_id="listReceiptMatchCandidates",
    summary="Rank the transactions a parsed receipt might explain",
)
async def list_receipt_match_candidates(
    attachment_id: str,
    store: AttachmentStore = Depends(get_attachment_store),
    summary: ISpendingSummary = Depends(get_spending_summary),
    alias_svc: IMerchantAliasService = Depends(get_merchant_alias_service),
) -> ReceiptCandidatesResponse:
    """Return ranked match candidates for a parsed receipt.

    409 when the receipt has not been parsed. Read-only: when exactly one tier-1
    candidate exists and the attachment arrived unlinked, ``auto_link_candidate``
    is true to signal the client should link the first candidate via
    ``POST /attachments/{id}/link``; this handler performs no write, so the
    ``read`` scope's GET-only contract holds and the demo dataset is untouched.
    """
    row = await run_sync(store.get_attachment, attachment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    if row["parse_status"] != "parsed":
        raise HTTPException(
            status_code=409,
            detail="This receipt has not been parsed yet, so it has no match candidates.",
        )

    parse = json.loads(row["parse_json"]) if row.get("parse_json") else {}
    try:
        receipt_date = datetime.strptime(parse["date"], "%Y-%m-%d").date()  # noqa: DTZ007 — date-only string, immediately reduced to .date()
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=409, detail="The parsed receipt has no usable date.") from exc

    items_by_month: dict[str, list[TransactionItem]] = {}
    for month in _candidate_months(receipt_date):
        items_by_month[month] = await run_sync(summary.query_month, month)

    aliases = await run_sync(alias_svc.get_aliases_map)
    all_keys = {
        (item["ForwardedTo"], item["DateFileName"])
        for items in items_by_month.values()
        for item in items
        if item.get("ForwardedTo") and item.get("DateFileName")
    }
    linked_keys = await run_sync(store.has_receipt, all_keys)

    candidates = find_candidates(parse, items_by_month, aliases, linked_keys)

    unlinked = row.get("forwarded_to") is None and row.get("date_file_name") is None
    tier_one = [c for c in candidates if c.tier == 1]
    # Pure read: signal the single-strong-match case (L8) but do not persist the
    # link. The client fires POST /attachments/{id}/link when this is true, so a
    # read-scope token cannot mutate state via this GET and the demo dataset is
    # untouched.
    auto_link_candidate = unlinked and len(tier_one) == 1

    return ReceiptCandidatesResponse(
        attachment_id=attachment_id,
        auto_link_candidate=auto_link_candidate,
        candidates=[
            ReceiptCandidate(
                tx_id=tx_id_from_composite(c.forwarded_to, c.date_file_name),
                tier=c.tier,
                day_distance=c.day_distance,
                amount_distance=c.amount_distance,
                company=c.company,
                amount=c.amount,
                date=c.date,
                category=c.category,
                already_has_receipt=c.already_has_receipt,
            )
            for c in candidates
        ],
    )
