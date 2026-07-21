"""Restore CLI for the S3 attachment/statement backup.

Downloads the mirrored files and rebuilds the attachment/statement database
rows from the manifest, using only the public store APIs. Runnable as::

    uv run python -m src.finance.s3_backup_restore --bucket my-bucket

Bucket/prefix default from ``data/config.json`` when the flags are omitted.
``--dry-run`` reports what would happen without writing any file or DB row.
Restore touches neither the config nor the backup state file.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.finance.app_config import get_config
from src.finance.attachment_store import AttachmentStore
from src.finance.aws_region import get_aws_region
from src.finance.s3_backup_shared import (
    ATTACHMENTS_S3_PREFIX,
    MANIFEST_KEY,
    STATEMENTS_S3_PREFIX,
    normalize_prefix,
)
from src.finance.statement_store import StatementStore

logger = logging.getLogger(__name__)

_MANAGED_S3_PREFIXES: tuple[str, ...] = (ATTACHMENTS_S3_PREFIX, STATEMENTS_S3_PREFIX)

# Columns `StatementStore.save_statement` consumes for the `statements` row.
# `list_statements()` also returns joined outcome-count extras (imported_count,
# etc.) and `completed_at`; those must be filtered out before the insert.
_STATEMENT_COLUMNS: frozenset[str] = frozenset(
    {
        "id",
        "filename",
        "institution",
        "account_type",
        "period_start",
        "period_end",
        "pdf_path",
        "total_parsed",
        "matched_count",
        "ambiguous_count",
        "suspected_duplicate_count",
        "new_count",
        "previously_imported_count",
        "status",
        "parsed_with_ai",
    }
)


class ManifestNotFoundError(RuntimeError):
    """Raised when no backup manifest exists under the configured prefix."""


@dataclass
class RestoreResult:
    files_downloaded: int
    files_skipped: int
    attachments_restored: int
    statements_restored: int


def _is_safe_relpath(relpath: str) -> bool:
    """Reject absolute paths and any ``..`` traversal component."""
    rel = Path(relpath)
    return not rel.is_absolute() and ".." not in rel.parts


def _fetch_manifest(s3_client: Any, bucket: str, norm: str) -> dict[str, Any]:
    from botocore.exceptions import ClientError

    manifest_key = norm + MANIFEST_KEY
    try:
        obj = s3_client.get_object(Bucket=bucket, Key=manifest_key)
    except ClientError as err:
        raise ManifestNotFoundError(f"No backup manifest found at s3://{bucket}/{manifest_key}") from err
    return json.loads(obj["Body"].read())


def _restore_attachment_row(store: AttachmentStore, row: dict[str, Any]) -> None:
    """Recreate one attachment: save file metadata, then reapply link + parse state."""
    meta = {
        "original_filename": row["original_filename"],
        "content_type": row["content_type"],
        "size_bytes": row["size_bytes"],
        "sha256": row["sha256"],
        "file_path": row["file_path"],
        "kind": row.get("kind", "receipt"),
    }
    attachment_id = store.save_attachment(meta)
    # Force the link to match the manifest (save_attachment's COALESCE would not
    # clear an existing link, and skips parse fields on the conflict path).
    store.set_link(attachment_id, row.get("forwarded_to"), row.get("date_file_name"))
    store.set_parse_result(
        attachment_id,
        status=row.get("parse_status") or "none",
        parse_json=row.get("parse_json"),
        error=row.get("parse_error"),
    )


def _restore_statement_row(store: StatementStore, row: dict[str, Any]) -> None:
    """Recreate one statement + its transactions, filtering list_statements extras."""
    statement = {key: row[key] for key in _STATEMENT_COLUMNS if key in row}
    transactions = row.get("transactions") or []
    store.save_statement(statement, transactions)


def restore_backup(
    bucket: str,
    prefix: str | None = None,
    *,
    raw_root: Path = Path("data/raw"),
    attachment_store: AttachmentStore | None = None,
    statement_store: StatementStore | None = None,
    s3_client: Any | None = None,
    dry_run: bool = False,
) -> RestoreResult:
    """Download mirrored files and rebuild DB rows from the manifest.

    Files land under ``raw_root`` at the same relative paths they were mirrored
    from. A same-size local file is left untouched (skipped). DB rows are rebuilt
    via the public store APIs. ``dry_run`` counts what would happen and writes
    nothing (no files, no DB rows).
    """
    client: Any = s3_client
    if client is None:
        import boto3

        client = boto3.client("s3", region_name=get_aws_region())

    norm = normalize_prefix(prefix)
    manifest = _fetch_manifest(client, bucket, norm)

    # Download managed objects (disk mirror), skipping same-size local files.
    files_downloaded = 0
    files_skipped = 0
    paginator = client.get_paginator("list_objects_v2")
    for s3_prefix in _MANAGED_S3_PREFIXES:
        for page in paginator.paginate(Bucket=bucket, Prefix=norm + s3_prefix):
            for obj in page.get("Contents", []):
                full_key = obj["Key"]
                relpath = full_key[len(norm) :]  # strip the user prefix → "attachments/..."
                if not _is_safe_relpath(relpath):
                    logger.warning("Skipping unsafe backup key: %r", full_key)
                    continue
                dest = raw_root / relpath
                if dest.exists() and dest.stat().st_size == obj["Size"]:
                    files_skipped += 1
                    continue
                if not dry_run:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    body = client.get_object(Bucket=bucket, Key=full_key)["Body"].read()
                    dest.write_bytes(body)
                files_downloaded += 1

    attachments = manifest.get("attachments") or []
    statements = manifest.get("statements") or []

    if dry_run:
        return RestoreResult(
            files_downloaded=files_downloaded,
            files_skipped=files_skipped,
            attachments_restored=len(attachments),
            statements_restored=len(statements),
        )

    attachment_store = attachment_store or AttachmentStore()
    statement_store = statement_store or StatementStore()

    attachments_restored = 0
    for row in attachments:
        _restore_attachment_row(attachment_store, row)
        attachments_restored += 1

    statements_restored = 0
    for row in statements:
        _restore_statement_row(statement_store, row)
        statements_restored += 1

    return RestoreResult(
        files_downloaded=files_downloaded,
        files_skipped=files_skipped,
        attachments_restored=attachments_restored,
        statements_restored=statements_restored,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.finance.s3_backup_restore",
        description="Restore attachments and statements from the S3 backup.",
    )
    parser.add_argument("--bucket", help="S3 bucket to restore from (defaults to s3_backup_bucket in config).")
    parser.add_argument("--prefix", help="Key prefix (defaults to s3_backup_prefix in config).")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be restored without writing.")
    args = parser.parse_args(argv)

    cfg = get_config()
    bucket = args.bucket or cfg.get("s3_backup_bucket")
    prefix = args.prefix if args.prefix is not None else cfg.get("s3_backup_prefix")

    if not bucket:
        print("No S3 bucket configured. Pass --bucket or set s3_backup_bucket in data/config.json.")
        return 1

    try:
        result = restore_backup(bucket, prefix, dry_run=args.dry_run)
    except ManifestNotFoundError as err:
        print(str(err))
        return 1

    lead = "Dry run: would restore" if args.dry_run else "Restored"
    print(
        f"{lead} {result.files_downloaded} file(s), {result.attachments_restored} attachment row(s), "
        f"and {result.statements_restored} statement(s). "
        f"{result.files_skipped} file(s) already present were skipped."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
