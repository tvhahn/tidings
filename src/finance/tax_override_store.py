"""SQLite persistence for per-transaction tax-pack overrides.

Tax-pack membership is normally derived: a spending row belongs to a claim line
when its category maps to that line. Overrides let a user correct that derivation
per transaction — force a row *into* a chosen line (``include``) or drop a
derived row *out* of its line (``exclude``). Like ``AttachmentStore``, this is a
single SQLite database (``data/tax_overrides.db``), never a dual-backend pair —
overrides are a local correction layer, not transaction state, so they never
touch DynamoDB.

Rows reference transactions by the persisted composite (``forwarded_to``,
``date_file_name``) — never the ``tx_id`` surrogate, which exists only at the API
boundary. ``line_key`` is non-null only for ``include`` rows (the target line);
``exclude`` rows leave it NULL.
"""

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from src.finance.local_db import get_connection

__all__ = ["TaxOverrideStore"]


class TaxOverrideStore:
    """SQLite-backed storage for per-transaction tax-pack overrides."""

    DB_PATH = Path("data/tax_overrides.db")
    SCHEMA_VERSION = 1

    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or self.DB_PATH
        if os.environ.get("PYTEST_CURRENT_TEST") and self._db_path == self.DB_PATH:
            raise RuntimeError(
                "TaxOverrideStore must use a tmp db_path under pytest; "
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
            conn.commit()
        finally:
            conn.close()

    def list_all(self) -> dict[tuple[str, str], dict[str, str | None]]:
        """Return every override keyed by (forwarded_to, date_file_name).

        Values carry ``{"mode": ..., "line_key": ...}`` — ``line_key`` is None
        for ``exclude`` rows. Read once per tax-pack build (the has_receipt bulk
        precedent), never per row.
        """
        conn = self._connect()
        try:
            rows = conn.execute("SELECT forwarded_to, date_file_name, mode, line_key FROM tax_overrides").fetchall()
        finally:
            conn.close()
        return {(r["forwarded_to"], r["date_file_name"]): {"mode": r["mode"], "line_key": r["line_key"]} for r in rows}

    def set_override(
        self,
        forwarded_to: str,
        date_file_name: str,
        mode: str,
        line_key: str | None,
    ) -> None:
        """Upsert a single override keyed by the composite (INSERT OR REPLACE)."""
        now = datetime.now(UTC).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO tax_overrides (
                    forwarded_to, date_file_name, mode, line_key, created_at
                ) VALUES (?, ?, ?, ?, ?)""",
                (forwarded_to, date_file_name, mode, line_key, now),
            )
            conn.commit()
        finally:
            conn.close()

    def clear_override(self, forwarded_to: str, date_file_name: str) -> None:
        """Delete an override; a no-op (no error) when none exists."""
        conn = self._connect()
        try:
            conn.execute(
                "DELETE FROM tax_overrides WHERE forwarded_to = ? AND date_file_name = ?",
                (forwarded_to, date_file_name),
            )
            conn.commit()
        finally:
            conn.close()


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    id INTEGER PRIMARY KEY,
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tax_overrides (
    forwarded_to   TEXT NOT NULL,
    date_file_name TEXT NOT NULL,
    mode           TEXT NOT NULL,
    line_key       TEXT,
    created_at     TEXT NOT NULL,
    PRIMARY KEY (forwarded_to, date_file_name)
);
"""
