"""Mirror engine for the opt-in S3 attachment/statement backup.

Walks the local raw trees (disk is the source of truth for which files exist),
uploads new or size-changed objects to the user-owned bucket, reconciles remote
deletions for files removed locally, and writes a metadata manifest on every
run. Only the two managed sub-prefixes (``attachments/`` and ``statements/``)
plus the manifest are ever touched — foreign keys under the prefix are left
alone.

The engine never reads or writes the state file and never notifies — the
scheduler owns operational state and user-facing signals. Manifest timestamps
are ISO-8601 UTC (operational metadata, not financial data, so the app timezone
rules do not apply).
"""

from __future__ import annotations

import json
import mimetypes
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.finance.attachment_store import AttachmentStore
from src.finance.aws_region import get_aws_region
from src.finance.s3_backup_shared import (
    ATTACHMENTS_S3_PREFIX,
    MANIFEST_KEY,
    STATEMENTS_S3_PREFIX,
    normalize_prefix,
)
from src.finance.statement_store import StatementStore

# The two local subtrees and the S3 sub-prefix each mirrors to. Reconcile
# deletions are confined to these namespaces; nothing else under the user's
# prefix is ever touched.
_MANAGED: tuple[tuple[str, str], ...] = (
    ("attachments", ATTACHMENTS_S3_PREFIX),
    ("statements", STATEMENTS_S3_PREFIX),
)

_DELETE_BATCH_SIZE = 1000


@dataclass
class BackupRunResult:
    uploaded: int
    deleted: int
    skipped: int
    objects_total: int  # = uploaded + skipped (files currently mirrored; manifest excluded)


def _iter_local_files(subdir_root: Path):
    """Yield ``(relative_path, absolute_path)`` for regular files under a subtree.

    Skips any path with a dotfile/dot-directory component (a component starting
    with ``.``) so editor swap files and hidden state never reach the bucket.
    """
    if not subdir_root.is_dir():
        return
    for path in sorted(subdir_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(subdir_root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        yield rel, path


def run_backup(
    bucket: str,
    prefix: str | None = None,
    *,
    raw_root: Path = Path("data/raw"),
    attachment_store: AttachmentStore | None = None,
    statement_store: StatementStore | None = None,
    s3_client: Any | None = None,
) -> BackupRunResult:
    """Mirror the local raw attachment/statement trees to ``bucket`` under ``prefix``.

    Disk is the source of truth for the file set: every regular file under
    ``raw_root/attachments`` and ``raw_root/statements`` is mirrored, and any
    managed remote object with no local counterpart is deleted. A metadata
    manifest (attachment rows + statements with their transactions) is uploaded
    on every successful run.
    """
    client: Any = s3_client
    if client is None:
        import boto3

        client = boto3.client("s3", region_name=get_aws_region())
    attachment_store = attachment_store or AttachmentStore()
    statement_store = statement_store or StatementStore()

    norm = normalize_prefix(prefix)
    managed_full_prefixes = tuple(norm + s3_prefix for _subdir, s3_prefix in _MANAGED)

    # Local file set (disk is truth), keyed by full S3 key.
    local: dict[str, tuple[Path, int]] = {}
    for subdir, s3_prefix in _MANAGED:
        for rel, path in _iter_local_files(raw_root / subdir):
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                continue  # vanished between walk and stat — skip silently
            local[norm + s3_prefix + rel.as_posix()] = (path, size)

    # Existing remote objects under the two managed sub-prefixes, keyed by full key.
    remote: dict[str, int] = {}
    paginator = client.get_paginator("list_objects_v2")
    for full_prefix in managed_full_prefixes:
        for page in paginator.paginate(Bucket=bucket, Prefix=full_prefix):
            for obj in page.get("Contents", []):
                remote[obj["Key"]] = obj["Size"]

    # Upload new or size-changed files.
    uploaded = 0
    skipped = 0
    for full_key, (path, size) in local.items():
        existing = remote.get(full_key)
        if existing is not None and existing == size:
            skipped += 1
            continue
        try:
            body = path.read_bytes()
        except FileNotFoundError:
            continue  # vanished mid-run — skip silently, do not count
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        client.put_object(Bucket=bucket, Key=full_key, Body=body, ContentType=content_type)
        uploaded += 1

    # Reconcile deletions: managed remote keys with no local counterpart.
    to_delete = [key for key in remote if key not in local]
    for key in to_delete:
        if not any(key.startswith(p) for p in managed_full_prefixes):
            # Hard guard: never delete outside the two managed namespaces.
            raise RuntimeError(f"Refusing to delete key outside managed prefixes: {key!r}")

    deleted = 0
    for start in range(0, len(to_delete), _DELETE_BATCH_SIZE):
        batch = to_delete[start : start + _DELETE_BATCH_SIZE]
        response = client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
        )
        errors = response.get("Errors") or []
        if errors:
            raise RuntimeError(f"S3 delete reported {len(errors)} error(s): {errors[:3]}")
        deleted += len(batch)

    # Metadata manifest — uploaded on every successful run.
    manifest = {
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "attachments": attachment_store.list_attachments(),
        "statements": [
            dict(row, transactions=statement_store.get_transactions(row["id"]))
            for row in statement_store.list_statements()
        ],
    }
    client.put_object(
        Bucket=bucket,
        Key=norm + MANIFEST_KEY,
        Body=json.dumps(manifest, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

    return BackupRunResult(uploaded=uploaded, deleted=deleted, skipped=skipped, objects_total=uploaded + skipped)
