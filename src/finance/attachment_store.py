"""SQLite persistence for per-transaction attachments (receipts and documents).

Attachment *files* live on the server's disk under ``data/raw/attachments/``
regardless of the transaction backend — exactly like statement PDFs, whose
``StatementStore`` is SQLite-only even when transactions are in DynamoDB. This
store follows that precedent: a single SQLite database (``data/attachments.db``),
never a dual-backend pair. Building a DynamoDB attachment table would strand file
paths that only exist on one machine.

Rows reference transactions by the persisted composite (``forwarded_to``,
``date_file_name``) — never the ``tx_id`` surrogate, which exists only at the API
boundary. Both columns NULL means the attachment is unlinked ("a receipt to
file"). The deterministic ``id`` (``att_`` + 16 hex of
``sha256(file_sha256|original_filename)``) makes re-uploading the identical file
upsert instead of duplicating.
"""

import contextlib
import hashlib
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.finance.local_db import get_connection

__all__ = [
    "ATTACHMENTS_RAW_DIR",
    "AttachmentStore",
    "attachment_id_for",
]

# Attachment files land at
# ``data/raw/attachments/<YYYY-MM>/<attachment_id>_<sanitized original name>``
# beside the statements raw dir (``STATEMENTS_RAW_DIR`` in statement_helpers).
ATTACHMENTS_RAW_DIR = Path("data/raw/attachments")

_ID_PREFIX = "att_"


def attachment_id_for(file_sha256: str, original_filename: str) -> str:
    """Deterministic attachment id derived from file content + original name.

    ``att_`` + the first 16 hex chars of ``sha256(f"{file_sha256}|{name}")``.
    Re-uploading the identical bytes under the same filename yields the same id,
    so ``save_attachment`` upserts rather than accumulating duplicate rows. A
    changed filename (same bytes) is intentionally a distinct attachment.
    """
    key = f"{file_sha256}|{original_filename}"
    return _ID_PREFIX + hashlib.sha256(key.encode()).hexdigest()[:16]


class AttachmentStore:
    """SQLite-backed storage for attachment metadata and transaction links."""

    DB_PATH = Path("data/attachments.db")
    SCHEMA_VERSION = 1

    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or self.DB_PATH
        if os.environ.get("PYTEST_CURRENT_TEST") and self._db_path == self.DB_PATH:
            raise RuntimeError(
                "AttachmentStore must use a tmp db_path under pytest; "
                "the tests/unit/conftest.py isolation fixture should have redirected this."
            )
        self._ensure_db()

    def _connect(self) -> sqlite3.Connection:
        # Shared connection factory (row_factory, WAL, busy_timeout, foreign_keys).
        return get_connection(self._db_path)

    def _ensure_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(_SCHEMA_SQL)
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (id, version) VALUES (1, ?)",
                (self.SCHEMA_VERSION,),
            )
            # Forward-compatible column migrations — suppress "duplicate column"
            # so re-running against an existing db is a no-op (StatementStore shape).
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute("ALTER TABLE attachments ADD COLUMN parse_json TEXT")
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute("ALTER TABLE attachments ADD COLUMN parse_error TEXT")
            conn.commit()
        finally:
            conn.close()

    def save_attachment(self, meta: dict[str, Any]) -> str:
        """Upsert an attachment row keyed by its deterministic id; returns the id.

        ``meta`` must carry ``original_filename``, ``content_type``, ``size_bytes``,
        ``sha256`` and ``file_path``; ``kind`` defaults to ``receipt`` and the
        link/parse columns default to unlinked/unparsed.

        A fresh id inserts with those defaults. Re-uploading the identical file
        (same id) is a metadata refresh, not a reset: the file columns
        (``original_filename``, ``content_type``, ``size_bytes``, ``sha256``,
        ``file_path``, ``kind``) and ``updated_at`` are overwritten, but the
        existing ``parse_status``/``parse_json``/``parse_error`` and the existing
        link (``forwarded_to``/``date_file_name``) are **preserved** — the link
        is only overwritten when the caller passes a non-None value (so an upload
        that carries a ``tx_id`` still links/relinks). ``created_at`` is always
        preserved. This mirrors the COALESCE precedent from
        ``StatementStore.save_statement`` while keeping AI-parse state and the
        receipt→transaction link intact across re-uploads.
        """
        attachment_id = attachment_id_for(meta["sha256"], meta["original_filename"])
        now = datetime.now(UTC).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO attachments (
                    id, original_filename, content_type, size_bytes, sha256,
                    file_path, kind, forwarded_to, date_file_name,
                    parse_status, parse_json, parse_error,
                    created_at, updated_at
                ) VALUES (
                    :id, :original_filename, :content_type, :size_bytes, :sha256,
                    :file_path, :kind, :forwarded_to, :date_file_name,
                    :parse_status, :parse_json, :parse_error,
                    :now, :now
                )
                ON CONFLICT(id) DO UPDATE SET
                    original_filename = excluded.original_filename,
                    content_type = excluded.content_type,
                    size_bytes = excluded.size_bytes,
                    sha256 = excluded.sha256,
                    file_path = excluded.file_path,
                    kind = excluded.kind,
                    forwarded_to = COALESCE(excluded.forwarded_to, attachments.forwarded_to),
                    date_file_name = COALESCE(excluded.date_file_name, attachments.date_file_name),
                    updated_at = excluded.updated_at""",
                {
                    "id": attachment_id,
                    "original_filename": meta["original_filename"],
                    "content_type": meta["content_type"],
                    "size_bytes": meta["size_bytes"],
                    "sha256": meta["sha256"],
                    "file_path": meta["file_path"],
                    "kind": meta.get("kind", "receipt"),
                    "forwarded_to": meta.get("forwarded_to"),
                    "date_file_name": meta.get("date_file_name"),
                    "parse_status": meta.get("parse_status", "none"),
                    "parse_json": meta.get("parse_json"),
                    "parse_error": meta.get("parse_error"),
                    "now": now,
                },
            )
            conn.commit()
        finally:
            conn.close()
        return attachment_id

    def get_attachment(self, attachment_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM attachments WHERE id = ?",
                (attachment_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_attachments(
        self,
        *,
        unlinked: bool | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if unlinked is True:
            clauses.append("forwarded_to IS NULL AND date_file_name IS NULL")
        elif unlinked is False:
            clauses.append("forwarded_to IS NOT NULL AND date_file_name IS NOT NULL")
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM attachments {where}ORDER BY created_at DESC",  # noqa: S608 — WHERE clauses are hardcoded fragments; kind bound via ?
                params,
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def list_for_transaction(self, forwarded_to: str, date_file_name: str) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM attachments WHERE forwarded_to = ? AND date_file_name = ? ORDER BY created_at DESC",
                (forwarded_to, date_file_name),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def set_link(
        self,
        attachment_id: str,
        forwarded_to: str | None,
        date_file_name: str | None,
    ) -> bool:
        """Link (or, with both args None, unlink) an attachment. False if unknown."""
        now = datetime.now(UTC).isoformat()
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE attachments SET forwarded_to = ?, date_file_name = ?, updated_at = ? WHERE id = ?",
                (forwarded_to, date_file_name, now, attachment_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def set_parse_result(
        self,
        attachment_id: str,
        *,
        status: str,
        parse_json: str | None,
        error: str | None,
    ) -> bool:
        """Persist a receipt-parse outcome. False if the id is unknown."""
        now = datetime.now(UTC).isoformat()
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE attachments SET parse_status = ?, parse_json = ?, parse_error = ?, updated_at = ? WHERE id = ?",
                (status, parse_json, error, now, attachment_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_attachment(self, attachment_id: str) -> dict[str, Any] | None:
        """Delete a row, returning it so the caller can unlink the file on disk.

        Returns None when the id is unknown (e.g. a second delete of the same id).
        """
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM attachments WHERE id = ?",
                (attachment_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
            conn.commit()
            return dict(row)
        finally:
            conn.close()

    def has_receipt(self, keys: set[tuple[str, str]]) -> set[tuple[str, str]]:
        """Bulk evidence probe: which of ``keys`` have a linked receipt-kind row.

        Used by the tax service to classify per-transaction evidence without an
        N+1 of ``list_for_transaction`` calls. Returns the subset of ``keys`` that
        carry at least one ``receipt``-kind attachment.
        """
        if not keys:
            return set()
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT DISTINCT forwarded_to, date_file_name FROM attachments "
                "WHERE kind = 'receipt' AND forwarded_to IS NOT NULL AND date_file_name IS NOT NULL"
            ).fetchall()
        finally:
            conn.close()
        present = {(r["forwarded_to"], r["date_file_name"]) for r in rows}
        return keys & present


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    id INTEGER PRIMARY KEY,
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    original_filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    file_path TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'receipt',
    forwarded_to TEXT,
    date_file_name TEXT,
    parse_status TEXT NOT NULL DEFAULT 'none',
    parse_json TEXT,
    parse_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attachments_link
    ON attachments(forwarded_to, date_file_name);
"""
