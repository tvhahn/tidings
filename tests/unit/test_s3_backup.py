"""Tests for the S3 backup mirror engine.

moto's ``mock_aws`` wraps client creation and every S3 call; the client is
injected into ``run_backup`` so no real AWS is touched. Stores are always
constructed with tmp db paths and the raw tree lives under ``tmp_path``.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from src.finance import s3_backup
from src.finance.attachment_store import AttachmentStore
from src.finance.s3_backup_shared import normalize_prefix
from src.finance.statement_store import StatementStore


@pytest.fixture(autouse=True)
def _aws_creds():
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")


@pytest.fixture
def s3():
    """A moto-backed S3 client + provisioned bucket, live for the whole test."""
    import boto3
    from moto import mock_aws

    with mock_aws():
        client = boto3.client("s3", region_name="us-west-2")
        bucket = "tidings-backup-test"
        client.create_bucket(
            Bucket=bucket,
            CreateBucketConfiguration={"LocationConstraint": "us-west-2"},
        )
        yield client, bucket


@pytest.fixture
def stores(tmp_path: Path):
    att = AttachmentStore(db_path=tmp_path / "attachments.db")
    stmt = StatementStore(db_path=tmp_path / "statements.db")
    return att, stmt


def _plant(raw_root: Path, rel: str, content: bytes = b"content") -> Path:
    path = raw_root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _seed_stores(att: AttachmentStore, stmt: StatementStore) -> None:
    att.save_attachment(
        {
            "original_filename": "receipt.pdf",
            "content_type": "application/pdf",
            "size_bytes": 10,
            "sha256": "sha-receipt",
            "file_path": "data/raw/attachments/2026-01/a.pdf",
            "kind": "receipt",
            "forwarded_to": "user@example.com",
            "date_file_name": "2026-01-05_coffee",
        }
    )
    stmt.save_statement(
        {
            "id": "stmt1",
            "filename": "jan.pdf",
            "institution": "RBC",
            "account_type": "chequing",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "pdf_path": "data/raw/statements/RBC/jan.pdf",
            "total_parsed": 2,
            "matched_count": 1,
            "ambiguous_count": 0,
            "new_count": 1,
            "previously_imported_count": 0,
        },
        [
            {
                "tx_index": 0,
                "reconcile_tier": "new",
                "date": "2026-01-05",
                "amount": 12.34,
                "raw_description": "COFFEE",
            },
            {
                "tx_index": 1,
                "reconcile_tier": "matched",
                "date": "2026-01-06",
                "amount": 56.78,
                "raw_description": "GRO",
            },
        ],
    )


def _list_keys(client, bucket: str) -> set[str]:
    resp = client.list_objects_v2(Bucket=bucket)
    return {obj["Key"] for obj in resp.get("Contents", [])}


def _populate_raw(raw_root: Path) -> None:
    _plant(raw_root, "attachments/2026-01/a.pdf", b"aaaa")
    _plant(raw_root, "attachments/b.txt", b"bb")
    _plant(raw_root, "statements/RBC/jan.pdf", b"pdfbytes")


def test_initial_run_uploads_all_files_and_manifest(s3, stores, tmp_path):
    client, bucket = s3
    att, stmt = stores
    raw_root = tmp_path / "raw"
    _populate_raw(raw_root)
    _seed_stores(att, stmt)

    result = s3_backup.run_backup(
        bucket, None, raw_root=raw_root, attachment_store=att, statement_store=stmt, s3_client=client
    )

    assert result.uploaded == 3
    assert result.skipped == 0
    assert result.deleted == 0
    assert result.objects_total == 3

    keys = _list_keys(client, bucket)
    assert keys == {
        "attachments/2026-01/a.pdf",
        "attachments/b.txt",
        "statements/RBC/jan.pdf",
        "manifest.json",
    }


def test_manifest_carries_nested_statement_transactions(s3, stores, tmp_path):
    client, bucket = s3
    att, stmt = stores
    raw_root = tmp_path / "raw"
    _populate_raw(raw_root)
    _seed_stores(att, stmt)

    s3_backup.run_backup(bucket, None, raw_root=raw_root, attachment_store=att, statement_store=stmt, s3_client=client)

    body = client.get_object(Bucket=bucket, Key="manifest.json")["Body"].read()
    manifest = json.loads(body)

    assert manifest["version"] == 1
    assert "generated_at" in manifest
    assert len(manifest["attachments"]) == 1
    assert manifest["attachments"][0]["forwarded_to"] == "user@example.com"

    assert len(manifest["statements"]) == 1
    statement = manifest["statements"][0]
    assert statement["id"] == "stmt1"
    assert len(statement["transactions"]) == 2
    assert {t["raw_description"] for t in statement["transactions"]} == {"COFFEE", "GRO"}


def test_second_run_no_changes_skips_all_but_refreshes_manifest(s3, stores, tmp_path):
    client, bucket = s3
    att, stmt = stores
    raw_root = tmp_path / "raw"
    _populate_raw(raw_root)
    _seed_stores(att, stmt)

    s3_backup.run_backup(bucket, None, raw_root=raw_root, attachment_store=att, statement_store=stmt, s3_client=client)
    first_manifest = json.loads(client.get_object(Bucket=bucket, Key="manifest.json")["Body"].read())

    result = s3_backup.run_backup(
        bucket, None, raw_root=raw_root, attachment_store=att, statement_store=stmt, s3_client=client
    )

    assert result.uploaded == 0
    assert result.skipped == 3
    assert result.deleted == 0
    assert result.objects_total == 3

    # Manifest is re-uploaded every run (generated_at is regenerated).
    second_manifest = json.loads(client.get_object(Bucket=bucket, Key="manifest.json")["Body"].read())
    assert second_manifest["version"] == first_manifest["version"]
    assert "generated_at" in second_manifest


def test_local_deletion_propagates_to_s3(s3, stores, tmp_path):
    client, bucket = s3
    att, stmt = stores
    raw_root = tmp_path / "raw"
    _populate_raw(raw_root)
    _seed_stores(att, stmt)

    s3_backup.run_backup(bucket, None, raw_root=raw_root, attachment_store=att, statement_store=stmt, s3_client=client)

    (raw_root / "attachments" / "b.txt").unlink()

    result = s3_backup.run_backup(
        bucket, None, raw_root=raw_root, attachment_store=att, statement_store=stmt, s3_client=client
    )

    assert result.deleted == 1
    keys = _list_keys(client, bucket)
    assert "attachments/b.txt" not in keys
    assert "attachments/2026-01/a.pdf" in keys


def test_size_changed_file_is_reuploaded(s3, stores, tmp_path):
    client, bucket = s3
    att, stmt = stores
    raw_root = tmp_path / "raw"
    _populate_raw(raw_root)
    _seed_stores(att, stmt)

    s3_backup.run_backup(bucket, None, raw_root=raw_root, attachment_store=att, statement_store=stmt, s3_client=client)

    _plant(raw_root, "attachments/b.txt", b"a much longer body than before")

    result = s3_backup.run_backup(
        bucket, None, raw_root=raw_root, attachment_store=att, statement_store=stmt, s3_client=client
    )

    assert result.uploaded == 1
    assert result.skipped == 2
    body = client.get_object(Bucket=bucket, Key="attachments/b.txt")["Body"].read()
    assert body == b"a much longer body than before"


def test_foreign_objects_outside_managed_prefixes_survive(s3, stores, tmp_path):
    client, bucket = s3
    att, stmt = stores
    raw_root = tmp_path / "raw"
    _populate_raw(raw_root)
    _seed_stores(att, stmt)

    client.put_object(Bucket=bucket, Key="unrelated/keep.txt", Body=b"keep me")
    client.put_object(Bucket=bucket, Key="root-object.txt", Body=b"root")
    # A stray dotfile the sibling verifier may leave under the prefix root.
    client.put_object(Bucket=bucket, Key=".tidings-write-probe", Body=b"probe")

    s3_backup.run_backup(bucket, None, raw_root=raw_root, attachment_store=att, statement_store=stmt, s3_client=client)

    keys = _list_keys(client, bucket)
    assert "unrelated/keep.txt" in keys
    assert "root-object.txt" in keys
    assert ".tidings-write-probe" in keys


@pytest.mark.parametrize("prefix", ["backups", "/backups/", None])
def test_prefix_normalization(s3, stores, tmp_path, prefix):
    client, bucket = s3
    att, stmt = stores
    raw_root = tmp_path / "raw"
    _populate_raw(raw_root)
    _seed_stores(att, stmt)

    s3_backup.run_backup(
        bucket, prefix, raw_root=raw_root, attachment_store=att, statement_store=stmt, s3_client=client
    )

    norm = normalize_prefix(prefix)
    keys = _list_keys(client, bucket)
    assert f"{norm}attachments/2026-01/a.pdf" in keys
    assert f"{norm}statements/RBC/jan.pdf" in keys
    assert f"{norm}manifest.json" in keys


def test_dotfiles_are_not_uploaded(s3, stores, tmp_path):
    client, bucket = s3
    att, stmt = stores
    raw_root = tmp_path / "raw"
    _populate_raw(raw_root)
    _plant(raw_root, "attachments/.hidden", b"secret")
    _plant(raw_root, "attachments/.cache/nested.pdf", b"cached")
    _seed_stores(att, stmt)

    result = s3_backup.run_backup(
        bucket, None, raw_root=raw_root, attachment_store=att, statement_store=stmt, s3_client=client
    )

    assert result.uploaded == 3  # only the three non-dot files
    keys = _list_keys(client, bucket)
    assert not any(".hidden" in k or ".cache" in k for k in keys)


def test_delete_guard_refuses_keys_outside_managed_prefixes(s3, stores, tmp_path, monkeypatch):
    """The reconcile hard-guard raises if a delete candidate escapes the namespace."""
    client, bucket = s3
    att, stmt = stores
    raw_root = tmp_path / "raw"
    _populate_raw(raw_root)
    _seed_stores(att, stmt)

    class _RogueClient:
        def __init__(self, inner):
            self._inner = inner

        def get_paginator(self, name):
            class _Wrapped:
                def paginate(self, **kwargs):
                    yield {"Contents": [{"Key": "attachments/ghost.pdf", "Size": 1}, {"Key": "evil/x", "Size": 1}]}

            return _Wrapped()

        def __getattr__(self, name):
            return getattr(self._inner, name)

    rogue = _RogueClient(client)
    with pytest.raises(RuntimeError, match="managed prefixes"):
        s3_backup.run_backup(
            bucket, None, raw_root=raw_root, attachment_store=att, statement_store=stmt, s3_client=rogue
        )
