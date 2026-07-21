"""Full-data backup: export everything as a zip, import with duplicate preview.

The Settings tab ships both sides of the flow:

- ``POST /data/export`` — streams ``finance-backup-{date}.zip`` containing
  ``transactions.csv`` (backup flavor — every authoritative field),
  ``config/*.json`` for categories/overrides/merchant-aliases/budgets, and a
  ``manifest.json``.
- ``POST /data/import/preview`` — multipart file upload; stages the parsed
  payload and returns dedup counts plus a token.
- ``POST /data/import/commit`` — applies the staged payload using the
  chosen duplicate strategy (``skip`` / ``overwrite`` / ``keep_both``).

Demo mode is intentionally blocked on all three endpoints; the gate covers
import/export only. There are no separate statement/EML upload gates —
demo-mode uploads already write to the demo DBs.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from src.api.dependencies import (
    ensure_not_demo,
    get_budget_service,
    get_category_service,
    get_merchant_alias_service,
    get_override_service,
    get_parse_failure_store,
    get_transactions_db,
    run_sync,
)
from src.api.models import (
    ConfigPreview,
    ImportCommitRequest,
    ImportPreviewCounts,
    ImportPreviewResponse,
    ImportPreviewSample,
    ImportResult,
    S3BackupStatusResponse,
)
from src.finance import app_config, backup_export, backup_import, s3_backup_shared, staging_store
from src.finance.decimal_utils import decimal_to_float
from src.finance.demo_clock import app_today
from src.finance.exceptions import VersionConflictError
from src.finance.transaction_hash import generate_transaction_hash
from src.finance.versioned_update import Update, versioned_update

if TYPE_CHECKING:
    from src.finance.protocols import (
        IBudgetService,
        ICategoryService,
        IMerchantAliasService,
        IOverrideService,
        IParseFailureStore,
        ITransactionsDB,
    )

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data", tags=["data"])

_SAMPLE_LIMIT = 10
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB — backups with bodies can grow


def _require_non_demo() -> None:
    """Reject the request in demo mode — the import/export demo gate."""
    ensure_not_demo("Import/export is disabled in demo mode")


def _default_forwarded_to() -> str:
    """Fallback ForwardedTo for plain-CSV rows that lack the column."""
    user_id = app_config.get_config().get("user_id", "default")
    return f"{user_id}{backup_import.DEFAULT_LOCAL_FORWARDED_TO_SUFFIX}"


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _gather_config(
    category_svc: ICategoryService,
    override_svc: IOverrideService,
    alias_svc: IMerchantAliasService,
    budget_svc: IBudgetService,
    parse_failure_store: IParseFailureStore,
) -> dict[str, Any]:
    """Read every config blob. Missing blobs are returned as None, not {}."""
    cat_item = category_svc.get_categories()
    categories = cat_item.get("Data") if cat_item else None

    ov_item = override_svc.get_overrides()
    overrides = ov_item.get("Data") if ov_item else None

    alias_item = alias_svc.get_aliases()
    aliases = alias_item.get("Data") if alias_item else None

    # Budgets are per-year. Only export years that actually have data.
    current_year = app_today().year
    budgets: dict[str, Any] = {}
    for year in range(current_year - 3, current_year + 1):
        targets = budget_svc.get_targets(year)
        groups = budget_svc.get_groups(year)
        if targets or groups:
            budgets[str(year)] = {
                "targets": targets.get("Data") if targets else None,
                "groups": groups.get("Data") if groups else None,
            }

    # Parse failures. Export is the one place the email body travels, so fetch
    # the full row (with email_json) for each summary rather than the list view.
    summaries = parse_failure_store.list_failures(limit=10_000)
    parse_failures: list[dict[str, Any]] = []
    for summary in summaries:
        full = parse_failure_store.get_failure(summary["id"])
        parse_failures.append(full if full is not None else summary)

    return {
        "categories": categories,
        "overrides": overrides,
        "merchant_aliases": aliases,
        "budgets": budgets or None,
        "parse_failures": parse_failures or None,
    }


@router.post(
    "/export",
    response_class=StreamingResponse,
    operation_id="exportFullBackup",
    summary="Stream a full-data backup zip (transactions + config)",
)
async def export_backup(
    db: ITransactionsDB = Depends(get_transactions_db),
    category_svc: ICategoryService = Depends(get_category_service),
    override_svc: IOverrideService = Depends(get_override_service),
    alias_svc: IMerchantAliasService = Depends(get_merchant_alias_service),
    budget_svc: IBudgetService = Depends(get_budget_service),
    parse_failure_store: IParseFailureStore = Depends(get_parse_failure_store),
):
    """Stream a full-data backup zip. Disabled in demo mode."""
    _require_non_demo()

    transactions = await run_sync(db.scan_all_transactions)
    cfg = await run_sync(_gather_config, category_svc, override_svc, alias_svc, budget_svc, parse_failure_store)

    storage = app_config.get_config().get("storage", "sqlite")
    payload = await run_sync(
        backup_export.build_backup_zip,
        transactions=transactions,
        categories=cfg["categories"],
        overrides=cfg["overrides"],
        merchant_aliases=cfg["merchant_aliases"],
        budgets=cfg["budgets"],
        parse_failures=cfg["parse_failures"],
        storage_backend=storage,
    )

    filename = f"finance-backup-{app_today().isoformat()}.zip"

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


# ---------------------------------------------------------------------------
# Import preview
# ---------------------------------------------------------------------------


def _to_sample(row: dict[str, Any]) -> ImportPreviewSample:
    amt = row.get("amount")
    return ImportPreviewSample(
        date=row.get("date"),
        amount=float(amt) if amt is not None else None,
        company=row.get("company"),
        category=row.get("category"),
    )


def _to_invalid_sample(entry: dict[str, Any]) -> ImportPreviewSample:
    raw = entry.get("raw") or {}
    amt_str = (raw.get("Amount") or "").strip()
    try:
        amt = float(amt_str) if amt_str else None
    except ValueError:
        amt = None
    return ImportPreviewSample(
        date=raw.get("Date"),
        amount=amt,
        company=raw.get("Company"),
        category=raw.get("Category"),
        reason=entry.get("reason"),
    )


def _build_preview_samples(
    parsed: backup_import.ParsedUpload,
) -> tuple[list[ImportPreviewSample], list[ImportPreviewSample], list[ImportPreviewSample]]:
    """Build the new / duplicate / invalid preview sample lists.

    Duplicates bucket uses the set of duplicate hashes; new bucket is
    everything else. Each bucket is capped at ``_SAMPLE_LIMIT``. Blocking
    (per-row hashing) — call via ``run_sync`` from the async handler.
    """
    dup_set = set(parsed.duplicate_hashes)
    sample_new: list[ImportPreviewSample] = []
    sample_dup: list[ImportPreviewSample] = []
    for row in parsed.transactions:
        bucket = sample_dup if generate_transaction_hash(row) in dup_set else sample_new
        if len(bucket) < _SAMPLE_LIMIT:
            bucket.append(_to_sample(row))
        if len(sample_new) >= _SAMPLE_LIMIT and len(sample_dup) >= _SAMPLE_LIMIT:
            break
    sample_invalid = [_to_invalid_sample(e) for e in parsed.invalid_rows[:_SAMPLE_LIMIT]]
    return sample_new, sample_dup, sample_invalid


def _config_preview(parsed: backup_import.ParsedUpload) -> ConfigPreview | None:
    if parsed.config is None:
        return None
    cat = parsed.config.categories
    ov = parsed.config.overrides
    al = parsed.config.merchant_aliases
    bg = parsed.config.budgets
    return ConfigPreview(
        categories_count=len(cat) if cat else None,
        overrides_count=len(ov) if ov else None,
        merchant_aliases_count=len(al) if al else None,
        budget_years_count=len(bg) if bg else None,
    )


@router.post(
    "/import/preview",
    response_model=ImportPreviewResponse,
    operation_id="previewBackupImport",
    summary="Stage a backup upload and return a dry-run dedup summary",
)
async def preview_import(
    file: UploadFile = File(...),
    db: ITransactionsDB = Depends(get_transactions_db),
):
    """Upload a backup zip or CSV, stage it, and return a dry-run summary."""
    _require_non_demo()

    if not file.filename:
        raise HTTPException(status_code=422, detail="Missing filename")

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=422, detail="Empty upload")
    if len(payload) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 50 MB upload limit")

    try:
        parsed = await run_sync(
            backup_import.parse_upload,
            file.filename,
            payload,
            default_forwarded_to=_default_forwarded_to(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    # Classify duplicates against the live DB. This is read-only — safe before staging.
    parsed.duplicate_hashes = await run_sync(backup_import.classify_duplicates, db, parsed.transactions)

    token = staging_store.stage(parsed)
    counts = parsed.counts()

    sample_new, sample_dup, sample_invalid = await run_sync(_build_preview_samples, parsed)

    return ImportPreviewResponse(
        token=token,
        filename=parsed.filename,
        source_kind=parsed.source_kind,
        counts=ImportPreviewCounts(
            total=counts.total,
            new=counts.new,
            duplicates=counts.duplicates,
            invalid=counts.invalid,
        ),
        sample_new=sample_new,
        sample_duplicates=sample_dup,
        sample_invalid=sample_invalid,
        config=_config_preview(parsed),
    )


# ---------------------------------------------------------------------------
# Import commit
# ---------------------------------------------------------------------------


def _apply_config(
    config: backup_import.ParsedConfig,
    category_svc: ICategoryService,
    override_svc: IOverrideService,
    alias_svc: IMerchantAliasService,
    budget_svc: IBudgetService,
) -> dict[str, Any]:
    """Replace each config blob in turn. Failures are collected per-section.

    Overrides/categories/aliases/budgets use optimistic locking — we pass the
    current version so a concurrent edit raises VersionConflictError. Import
    is treated as authoritative: on conflict we re-read and retry once before
    surfacing the failure in the result payload.
    """
    details: dict[str, Any] = {}

    if config.categories is not None:
        categories_payload: list[str] = list(config.categories)
        details["categories"] = _retrying_put(
            lambda v: category_svc.put_all_categories(categories_payload, v),
            lambda: (category_svc.get_categories() or {}).get("Version"),
        )

    if config.overrides is not None:
        overrides_payload: dict[str, Any] = dict(config.overrides)
        details["overrides"] = _retrying_put(
            lambda v: override_svc.put_all_overrides(overrides_payload, v),
            lambda: (override_svc.get_overrides() or {}).get("Version"),
        )

    if config.merchant_aliases is not None:
        aliases_payload: dict[str, Any] = dict(config.merchant_aliases)
        details["merchant_aliases"] = _retrying_put(
            lambda v: alias_svc.put_all_aliases(aliases_payload, v),
            lambda: (alias_svc.get_aliases() or {}).get("Version"),
        )

    if config.budgets is not None:
        budget_details: dict[str, Any] = {}
        for year_str, year_data in config.budgets.items():
            try:
                year = int(year_str)
            except ValueError:
                budget_details[year_str] = {"error": f"invalid year key {year_str!r}"}
                continue
            targets = year_data.get("targets") if isinstance(year_data, dict) else None
            groups = year_data.get("groups") if isinstance(year_data, dict) else None
            year_result: dict[str, Any] = {}
            if targets is not None:
                year_result["targets"] = _retrying_put(
                    lambda v, y=year, t=targets: budget_svc.put_targets(y, t, v),
                    lambda y=year: (budget_svc.get_targets(y) or {}).get("Version"),
                )
            if groups is not None:
                year_result["groups"] = _retrying_put(
                    lambda v, y=year, g=groups: budget_svc.put_groups(y, g, v),
                    lambda y=year: (budget_svc.get_groups(y) or {}).get("Version"),
                )
            if year_result:
                budget_details[year_str] = year_result
        if budget_details:
            details["budgets"] = budget_details

    return details


def _retrying_put(write_fn: Any, read_version_fn: Any) -> dict[str, Any]:
    """Optimistic-lock retry: read-modify-write up to twice.

    Thin wrapper over :func:`versioned_update` in retry mode. The plan re-reads
    the current version each attempt; the put ignores the (unused) payload and
    calls ``write_fn(version)``. A second conflict is surfaced as a conflict
    dict rather than propagating.
    """
    try:
        new_version = versioned_update(
            lambda: Update(data=None, version=read_version_fn()),
            lambda _data, version: write_fn(version),
            retry_on_conflict=True,
        )
        return {"status": "applied", "version": new_version}
    except VersionConflictError as e:
        return {"status": "conflict", "error": str(e)}


@router.post(
    "/import/commit",
    response_model=ImportResult,
    operation_id="commitBackupImport",
    summary="Apply a previously-previewed import using the chosen strategy",
)
async def commit_import(
    body: ImportCommitRequest,
    db: ITransactionsDB = Depends(get_transactions_db),
    category_svc: ICategoryService = Depends(get_category_service),
    override_svc: IOverrideService = Depends(get_override_service),
    alias_svc: IMerchantAliasService = Depends(get_merchant_alias_service),
    budget_svc: IBudgetService = Depends(get_budget_service),
):
    """Apply a previously previewed import using the chosen strategy."""
    _require_non_demo()

    parsed = staging_store.load(body.token)
    if parsed is None:
        raise HTTPException(status_code=410, detail="Import token missing or expired")

    try:
        counts = await run_sync(db.bulk_add_transactions, parsed.transactions, body.strategy)
        # Normalize Decimal → float for any audit confidence values that survived JSON roundtrip
        for k, v in list(counts.items()):
            counts[k] = int(decimal_to_float(v) or 0)
    finally:
        # Either way, discard the staged file so it can't be re-applied.
        staging_store.delete(body.token)

    config_applied = False
    config_details: dict[str, Any] = {}
    if body.apply_config and parsed.config is not None:
        config_details = await run_sync(
            _apply_config,
            parsed.config,
            category_svc,
            override_svc,
            alias_svc,
            budget_svc,
        )
        config_applied = bool(config_details)

    return ImportResult(
        inserted=counts.get("inserted", 0),
        updated=counts.get("updated", 0),
        skipped=counts.get("skipped", 0),
        invalid=counts.get("invalid", 0),
        errors=counts.get("errors", 0),
        config_applied=config_applied,
        config_details=config_details,
    )


# ---------------------------------------------------------------------------
# S3 attachment backup — status
# ---------------------------------------------------------------------------


@router.get(
    "/s3-backup-status",
    response_model=S3BackupStatusResponse,
    operation_id="getS3BackupStatus",
    summary="Read the S3 attachment-backup config and last-run state",
)
async def get_s3_backup_status() -> S3BackupStatusResponse:
    """Merge the S3-backup config keys with the sync engine's state file.

    ``enabled``/``bucket``/``prefix`` come from config; the run metadata comes
    from the state file (zeroed defaults when it's absent or corrupt). Disabled
    in demo mode, matching the rest of this router.
    """
    _require_non_demo()

    cfg = app_config.get_config()
    state = s3_backup_shared.read_state()
    return S3BackupStatusResponse(
        enabled=bool(cfg.get("s3_backup_enabled", False)),
        bucket=cfg.get("s3_backup_bucket"),
        prefix=cfg.get("s3_backup_prefix"),
        last_attempt_at=state["last_attempt_at"],
        last_success_at=state["last_success_at"],
        last_error=state["last_error"],
        consecutive_failures=state["consecutive_failures"],
        uploaded_count=state["uploaded_count"],
        deleted_count=state["deleted_count"],
        objects_total=state["objects_total"],
    )
