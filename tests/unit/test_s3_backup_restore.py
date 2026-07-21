"""Tests for the S3 backup restore CLI.

moto's ``mock_aws`` wraps the client; stores use tmp db paths and raw trees live
under ``tmp_path``. The round-trip drives ``run_backup`` from a populated source
env, then restores into a fresh env and asserts byte-identical files plus
faithfully rebuilt DB rows.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from src.finance import s3_backup
from src.finance.attachment_store import AttachmentStore
from src.finance.s3_backup_restore import ManifestNotFoundError, main, restore_backup
from src.finance.statement_store import StatementStore

_RECEIPT_BYTES = b"receipt-bytes-here"
_NOTE_BYTES = b"a note"
_STATEMENT_BYTES = b"statement-pdf-bytes"


@pytest.fixture(autouse=True)
def _aws_creds():
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")


@pytest.fixture
def s3():
    import boto3
    from moto import mock_aws

    with mock_aws():
        client = boto3.client("s3", region_name="us-west-2")
        bucket = "tidings-restore-test"
        client.create_bucket(
            Bucket=bucket,
            CreateBucketConfiguration={"LocationConstraint": "us-west-2"},
        )
        yield client, bucket


def _plant(raw_root: Path, rel: str, content: bytes) -> None:
    path = raw_root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _populate_source(raw_root: Path, att: AttachmentStore, stmt: StatementStore) -> str:
    _plant(raw_root, "attachments/2026-01/a.pdf", _RECEIPT_BYTES)
    _plant(raw_root, "attachments/b.txt", _NOTE_BYTES)
    _plant(raw_root, "statements/RBC/jan.pdf", _STATEMENT_BYTES)

    attachment_id = att.save_attachment(
        {
            "original_filename": "a.pdf",
            "content_type": "application/pdf",
            "size_bytes": len(_RECEIPT_BYTES),
            "sha256": "sha-a",
            "file_path": "data/raw/attachments/2026-01/a.pdf",
            "kind": "receipt",
            "forwarded_to": "user@example.com",
            "date_file_name": "2026-01-05_coffee",
        }
    )
    att.set_parse_result(attachment_id, status="success", parse_json='{"total": 12.34}', error=None)

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
    return attachment_id


def _fresh_stores(tmp_path: Path, name: str) -> tuple[AttachmentStore, StatementStore]:
    base = tmp_path / name
    base.mkdir(parents=True, exist_ok=True)
    return AttachmentStore(db_path=base / "attachments.db"), StatementStore(db_path=base / "statements.db")


def _back_up(s3, tmp_path: Path, prefix=None):
    """Populate a source env and mirror it to S3; return (client, bucket, attachment_id)."""
    client, bucket = s3
    raw_a = tmp_path / "raw_a"
    att_a, stmt_a = _fresh_stores(tmp_path, "a")
    attachment_id = _populate_source(raw_a, att_a, stmt_a)
    s3_backup.run_backup(
        bucket, prefix, raw_root=raw_a, attachment_store=att_a, statement_store=stmt_a, s3_client=client
    )
    return client, bucket, attachment_id


def test_full_round_trip_restores_files_and_rows(s3, tmp_path):
    client, bucket, attachment_id = _back_up(s3, tmp_path)

    raw_b = tmp_path / "raw_b"
    att_b, stmt_b = _fresh_stores(tmp_path, "b")

    result = restore_backup(
        bucket, None, raw_root=raw_b, attachment_store=att_b, statement_store=stmt_b, s3_client=client
    )

    assert result.files_downloaded == 3
    assert result.attachments_restored == 1
    assert result.statements_restored == 1

    # Files restored byte-for-byte.
    assert (raw_b / "attachments/2026-01/a.pdf").read_bytes() == _RECEIPT_BYTES
    assert (raw_b / "attachments/b.txt").read_bytes() == _NOTE_BYTES
    assert (raw_b / "statements/RBC/jan.pdf").read_bytes() == _STATEMENT_BYTES

    # Attachment row back, including link + parse fields.
    row = att_b.get_attachment(attachment_id)
    assert row is not None
    assert row["forwarded_to"] == "user@example.com"
    assert row["date_file_name"] == "2026-01-05_coffee"
    assert row["parse_status"] == "success"
    assert row["parse_json"] == '{"total": 12.34}'

    # Statement row + its transactions back.
    statements = stmt_b.list_statements()
    assert [s["id"] for s in statements] == ["stmt1"]
    transactions = stmt_b.get_transactions("stmt1")
    assert len(transactions) == 2
    assert {t["raw_description"] for t in transactions} == {"COFFEE", "GRO"}


def test_round_trip_with_prefix(s3, tmp_path):
    client, bucket, attachment_id = _back_up(s3, tmp_path, prefix="backups")

    raw_b = tmp_path / "raw_b"
    att_b, stmt_b = _fresh_stores(tmp_path, "b")

    result = restore_backup(
        bucket, "backups", raw_root=raw_b, attachment_store=att_b, statement_store=stmt_b, s3_client=client
    )

    assert result.files_downloaded == 3
    assert (raw_b / "attachments/2026-01/a.pdf").read_bytes() == _RECEIPT_BYTES
    assert att_b.get_attachment(attachment_id) is not None


def test_dry_run_writes_nothing(s3, tmp_path):
    client, bucket, _ = _back_up(s3, tmp_path)

    raw_b = tmp_path / "raw_b"
    att_b, stmt_b = _fresh_stores(tmp_path, "b")

    result = restore_backup(
        bucket,
        None,
        raw_root=raw_b,
        attachment_store=att_b,
        statement_store=stmt_b,
        s3_client=client,
        dry_run=True,
    )

    # Counts reported...
    assert result.files_downloaded == 3
    assert result.attachments_restored == 1
    assert result.statements_restored == 1
    # ...but nothing written.
    assert not raw_b.exists() or not any(raw_b.rglob("*"))
    assert att_b.list_attachments() == []
    assert stmt_b.list_statements() == []


def test_existing_same_size_file_is_skipped(s3, tmp_path):
    client, bucket, _ = _back_up(s3, tmp_path)

    raw_b = tmp_path / "raw_b"
    att_b, stmt_b = _fresh_stores(tmp_path, "b")
    # Pre-seed one identical file so it is skipped on restore.
    _plant(raw_b, "attachments/b.txt", _NOTE_BYTES)

    result = restore_backup(
        bucket, None, raw_root=raw_b, attachment_store=att_b, statement_store=stmt_b, s3_client=client
    )

    assert result.files_skipped == 1
    assert result.files_downloaded == 2


def test_missing_manifest_raises_clean_error(s3, tmp_path):
    client, bucket = s3  # bucket exists, but no backup ran → no manifest
    raw_b = tmp_path / "raw_b"
    att_b, stmt_b = _fresh_stores(tmp_path, "b")

    with pytest.raises(ManifestNotFoundError):
        restore_backup(bucket, None, raw_root=raw_b, attachment_store=att_b, statement_store=stmt_b, s3_client=client)


def test_malicious_traversal_key_is_rejected(s3, tmp_path):
    client, bucket, _ = _back_up(s3, tmp_path)
    # Plant an object whose stripped path escapes raw_root.
    client.put_object(Bucket=bucket, Key="attachments/../evil.txt", Body=b"pwned")

    raw_b = tmp_path / "raw_b"
    att_b, stmt_b = _fresh_stores(tmp_path, "b")

    restore_backup(bucket, None, raw_root=raw_b, attachment_store=att_b, statement_store=stmt_b, s3_client=client)

    # The traversal target (raw_b/evil.txt after `attachments/..`) must not exist.
    assert not (raw_b / "evil.txt").exists()
    assert not (tmp_path / "evil.txt").exists()
    # The legitimate files still restored.
    assert (raw_b / "attachments/2026-01/a.pdf").read_bytes() == _RECEIPT_BYTES


def test_main_no_bucket_returns_error(monkeypatch, capsys):
    from src.finance import s3_backup_restore

    monkeypatch.setattr(
        s3_backup_restore,
        "get_config",
        lambda: {"s3_backup_bucket": None, "s3_backup_prefix": None},
    )
    rc = main(["--dry-run"])
    assert rc == 1
    assert "No S3 bucket configured" in capsys.readouterr().out


def test_main_missing_manifest_returns_error(s3, tmp_path, monkeypatch, capsys):
    from src.finance import s3_backup_restore

    client, bucket = s3
    monkeypatch.setattr(
        s3_backup_restore,
        "get_config",
        lambda: {"s3_backup_bucket": bucket, "s3_backup_prefix": None},
    )

    # Route restore_backup's default client to the moto client + tmp raw_root.
    real_restore = s3_backup_restore.restore_backup

    def _restore(bucket_arg, prefix_arg=None, **kwargs):
        kwargs.setdefault("s3_client", client)
        kwargs.setdefault("raw_root", tmp_path / "raw_b")
        return real_restore(bucket_arg, prefix_arg, **kwargs)

    monkeypatch.setattr(s3_backup_restore, "restore_backup", _restore)

    rc = main([])
    assert rc == 1
    assert "No backup manifest" in capsys.readouterr().out


def test_main_success_prints_summary(s3, tmp_path, monkeypatch, capsys):
    from src.finance import s3_backup_restore

    client, bucket, _ = _back_up(s3, tmp_path)
    monkeypatch.setattr(
        s3_backup_restore,
        "get_config",
        lambda: {"s3_backup_bucket": bucket, "s3_backup_prefix": None},
    )

    raw_b = tmp_path / "raw_b"
    att_b, stmt_b = _fresh_stores(tmp_path, "b")
    real_restore = s3_backup_restore.restore_backup

    def _restore(bucket_arg, prefix_arg=None, **kwargs):
        kwargs.setdefault("s3_client", client)
        kwargs.setdefault("raw_root", raw_b)
        kwargs.setdefault("attachment_store", att_b)
        kwargs.setdefault("statement_store", stmt_b)
        return real_restore(bucket_arg, prefix_arg, **kwargs)

    monkeypatch.setattr(s3_backup_restore, "restore_backup", _restore)

    rc = main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Restored" in out
    assert "statement" in out
