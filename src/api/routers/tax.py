"""Tax pack endpoints: per-line claim totals for a year, and a zip export.

``GET /tax-pack`` returns the calendar-year pack; ``GET /tax-pack/export``
streams an in-memory zip (the ``data.py`` export precedent) containing a
summary CSV, one CSV per claim line, the receipt files linked to claimed
transactions, and the source email body for email-evidence rows. The export is
demo-gated: it reads receipt files from the host's disk.

The service is composed per request from the shared spending summary and the
lazily demo-aware attachment store (the ``IncomeStatementService`` wiring
precedent) — a module-level singleton would freeze the attachment store's
demo/non-demo choice at import time.
"""

import csv
import hashlib
import io
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from src.api.dependencies import (
    ensure_not_demo,
    get_attachment_store,
    get_spending_summary,
    get_tax_override_store,
    run_sync,
)
from src.api.models import (
    TaxLineOption,
    TaxLinesResponse,
    TaxOverrideRequest,
    TaxPackResponse,
)
from src.api.utils import sanitize_filename
from src.finance.attachment_store import AttachmentStore
from src.finance.config_loader import get_tax_line_mappings
from src.finance.protocols import ISpendingSummary
from src.finance.tax_override_store import TaxOverrideStore
from src.finance.tax_pack_service import _OTHER_KEY, _OTHER_LINE, TaxPackService
from src.finance.tx_id import composite_from_tx_id

router = APIRouter(tags=["tax"])

# Stored content-type → evidence file extension (the L4 allowlist, inverted).
_CONTENT_TYPE_EXTS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}


def _id8(attachment_id: str) -> str:
    """First 8 chars of the attachment id after the ``att_`` prefix."""
    return attachment_id.removeprefix("att_")[:8]


def _email_id8(forwarded_to: str, date_file_name: str) -> str:
    """Stable 8-char id for an email-evidence file (no attachment exists).

    First 8 hex chars of ``sha256(forwarded_to|date_file_name)`` — deterministic
    per transaction, mirroring the shape of the attachment ``id8``.
    """
    return hashlib.sha256(f"{forwarded_to}|{date_file_name}".encode()).hexdigest()[:8]


@router.get(
    "/tax-pack",
    response_model=TaxPackResponse,
    operation_id="getTaxPack",
    summary="Calendar-year tax pack: claim-line totals with per-transaction evidence",
)
async def get_tax_pack(
    year: int = Query(..., ge=2020, le=2099),
    summary: ISpendingSummary = Depends(get_spending_summary),
    store: AttachmentStore = Depends(get_attachment_store),
    override_store: TaxOverrideStore = Depends(get_tax_override_store),
) -> TaxPackResponse:
    svc = TaxPackService(summary, store, override_store)
    pack = await run_sync(svc.get_tax_pack, year)
    return TaxPackResponse(**pack)


def _valid_line_keys() -> set[str]:
    """The selectable override targets: the seed keys plus the synthetic other line."""
    mapping = get_tax_line_mappings()
    return {line["key"] for line in mapping.get("lines", [])} | {_OTHER_KEY}


@router.get(
    "/tax-pack/lines",
    response_model=TaxLinesResponse,
    operation_id="getTaxLines",
    summary="Selectable claim lines for the include-override picker",
)
async def get_tax_lines() -> TaxLinesResponse:
    """Return the seed lines plus the synthetic other line as ``{key, label}``."""
    mapping = await run_sync(get_tax_line_mappings)
    options = [TaxLineOption(key=line["key"], label=line["label"]) for line in mapping.get("lines", [])]
    options.append(TaxLineOption(key=_OTHER_KEY, label=str(_OTHER_LINE["label"])))
    return TaxLinesResponse(lines=options)


@router.post(
    "/tax-pack/items",
    status_code=204,
    operation_id="setTaxOverride",
    summary="Force a transaction into a claim line, or exclude it from one",
)
async def set_tax_override(
    body: TaxOverrideRequest,
    override_store: TaxOverrideStore = Depends(get_tax_override_store),
) -> Response:
    """Upsert a per-transaction tax override. Disabled in demo mode."""
    ensure_not_demo("Flagging tax items is disabled in the demo.")

    try:
        forwarded_to, date_file_name = composite_from_tx_id(body.tx_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Unknown transaction id.") from exc

    if body.mode == "include" and (body.line_key is None or body.line_key not in await run_sync(_valid_line_keys)):
        raise HTTPException(
            status_code=422,
            detail="An include override requires a valid line_key.",
        )

    await run_sync(
        override_store.set_override,
        forwarded_to,
        date_file_name,
        body.mode,
        body.line_key if body.mode == "include" else None,
    )
    return Response(status_code=204)


@router.delete(
    "/tax-pack/items/{tx_id}",
    status_code=204,
    operation_id="clearTaxOverride",
    summary="Clear a per-transaction tax override",
)
async def clear_tax_override(
    tx_id: str,
    override_store: TaxOverrideStore = Depends(get_tax_override_store),
) -> Response:
    """Delete a per-transaction tax override. Disabled in demo mode."""
    ensure_not_demo("Flagging tax items is disabled in the demo.")

    try:
        forwarded_to, date_file_name = composite_from_tx_id(tx_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Unknown transaction id.") from exc

    await run_sync(override_store.clear_override, forwarded_to, date_file_name)
    return Response(status_code=204)


def _line_csv(transactions: list[dict[str, Any]]) -> str:
    """Render one claim line's transactions as CSV (date, company, amount, category, evidence, tx_id)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["date", "company", "amount", "category", "evidence", "tx_id"])
    for txn in transactions:
        writer.writerow(
            [
                txn["date"],
                txn["company"],
                f"{txn['amount']:.2f}",
                txn["category"],
                txn["evidence"],
                txn["tx_id"],
            ]
        )
    return buffer.getvalue()


def _summary_csv(pack: dict[str, Any]) -> str:
    """Render the per-line rollup as CSV, one row per claim line plus a total row."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["line", "label", "total", "transaction_count", "receipts", "emails", "statements", "note"])
    for line in pack["lines"]:
        counts = line["evidence_counts"]
        writer.writerow(
            [
                line["key"],
                line["label"],
                f"{line['total']:.2f}",
                line["transaction_count"],
                counts["receipt"],
                counts["email"],
                counts["statement"],
                line.get("note") or "",
            ]
        )
    writer.writerow(["total", "", f"{pack['grand_total']:.2f}", "", "", "", "", ""])
    return buffer.getvalue()


def _build_export_zip(
    pack: dict[str, Any],
    store: AttachmentStore,
    bodies_by_composite: dict[tuple[str, str], str],
) -> bytes:
    """Assemble the export zip in memory (the ``data.py`` backup-zip shape).

    ``bodies_by_composite`` carries the source-email ``Body`` for every active
    email-evidence row, already read during the pack build — so the export no
    longer re-fetches each one with a per-row ``db.get_item`` (the old N+1).
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("summary.csv", _summary_csv(pack))
        written: set[str] = set()
        for line in pack["lines"]:
            zf.writestr(f"lines/{line['key']}.csv", _line_csv(line["transactions"]))
            for txn in line["transactions"]:
                forwarded_to, date_file_name = composite_from_tx_id(txn["tx_id"])
                slug = sanitize_filename(txn["company"], fallback="unknown")
                if txn["evidence"] == "receipt":
                    for att in store.list_for_transaction(forwarded_to, date_file_name):
                        if att["kind"] != "receipt":
                            continue
                        path = Path(att["file_path"])
                        if not path.is_file():
                            continue
                        ext = _CONTENT_TYPE_EXTS.get(att["content_type"], path.suffix or ".bin")
                        arcname = f"evidence/{line['key']}/{txn['date']}_{slug}_{_id8(att['id'])}{ext}"
                        if arcname in written:
                            continue
                        written.add(arcname)
                        zf.writestr(arcname, path.read_bytes())
                elif txn["evidence"] == "email":
                    body = bodies_by_composite.get((forwarded_to, date_file_name))
                    if not body:
                        continue
                    email_id = _email_id8(forwarded_to, date_file_name)
                    arcname = f"evidence/{line['key']}/emails/{txn['date']}_{slug}_{email_id}.txt"
                    if arcname in written:
                        continue
                    written.add(arcname)
                    zf.writestr(arcname, str(body))
                # Statement-evidence rows carry no email body and no receipt
                # file — the statement PDF itself lives on the Statements page.
    return buffer.getvalue()


@router.get(
    "/tax-pack/export",
    response_class=StreamingResponse,
    operation_id="exportTaxPack",
    summary="Download the year's tax pack as a zip of CSVs plus evidence files",
)
async def export_tax_pack(
    year: int = Query(..., ge=2020, le=2099),
    summary: ISpendingSummary = Depends(get_spending_summary),
    store: AttachmentStore = Depends(get_attachment_store),
    override_store: TaxOverrideStore = Depends(get_tax_override_store),
) -> StreamingResponse:
    """Stream the tax pack zip. Disabled in demo mode (reads host disk)."""
    ensure_not_demo("The tax pack export is disabled in the demo.")

    svc = TaxPackService(summary, store, override_store)
    pack, bodies = await run_sync(svc.get_tax_pack_with_evidence, year)
    payload = await run_sync(_build_export_zip, pack, store, bodies)

    filename = f"tax-pack-{year}.zip"

    def _iter() -> Any:
        yield payload

    return StreamingResponse(
        _iter(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(payload)),
        },
    )
