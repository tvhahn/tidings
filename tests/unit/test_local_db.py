"""Tests for src/finance/local_db.py — connection setup and schema initialization."""

import sqlite3
from pathlib import Path

from src.finance.local_db import ensure_schema, get_connection


class TestGetConnection:
    def test_wal_mode_set_on_fresh_db(self, tmp_path: Path) -> None:
        """get_connection() sets WAL on a brand-new file (defense-in-depth for imap-poller race)."""
        conn = get_connection(tmp_path / "test.db")
        try:
            row = conn.execute("PRAGMA journal_mode").fetchone()
            assert row[0] == "wal"
        finally:
            conn.close()

    def test_busy_timeout_set(self, tmp_path: Path) -> None:
        """get_connection() must set busy_timeout for multi-process safety."""
        conn = get_connection(tmp_path / "test.db")
        try:
            row = conn.execute("PRAGMA busy_timeout").fetchone()
            assert row[0] == 5000
        finally:
            conn.close()

    def test_foreign_keys_enabled(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "test.db")
        try:
            row = conn.execute("PRAGMA foreign_keys").fetchone()
            assert row[0] == 1
        finally:
            conn.close()

    def test_row_factory(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "test.db")
        try:
            assert conn.row_factory is sqlite3.Row
        finally:
            conn.close()


class TestEnsureSchema:
    def test_wal_mode_persists_to_new_connection(self, tmp_path: Path) -> None:
        """After ensure_schema(), a subsequent connection (e.g. imap-poller) is in WAL mode."""
        db = tmp_path / "finance.db"
        ensure_schema(db)
        conn = get_connection(db)
        try:
            row = conn.execute("PRAGMA journal_mode").fetchone()
            assert row[0] == "wal"
        finally:
            conn.close()

    def test_creates_expected_tables(self, tmp_path: Path) -> None:
        db = tmp_path / "finance.db"
        ensure_schema(db)
        conn = get_connection(db)
        try:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            assert "transactions" in tables
            assert "config_store" in tables
        finally:
            conn.close()

    def test_idempotent(self, tmp_path: Path) -> None:
        db = tmp_path / "finance.db"
        ensure_schema(db)
        ensure_schema(db)  # Must not raise

    def test_creates_date_file_name_index(self, tmp_path: Path) -> None:
        """The month-range index backing spending_summary_local.query_month exists."""
        db = tmp_path / "finance.db"
        ensure_schema(db)
        conn = get_connection(db)
        try:
            indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
            assert "idx_transactions_date_file_name" in indexes
        finally:
            conn.close()


class TestCategoryAuditMigration:
    """ensure_schema() backfills category_audit_matched_rule + _confidence on pre-existing DBs."""

    _LEGACY_SCHEMA = """
        CREATE TABLE transactions (
            forwarded_to TEXT NOT NULL,
            date_file_name TEXT NOT NULL,
            transaction_hash TEXT,
            category TEXT,
            category_audit_reviewed_at TEXT,
            category_audit_source TEXT,
            PRIMARY KEY (forwarded_to, date_file_name)
        )
    """

    def test_migration_adds_missing_columns(self, tmp_path: Path) -> None:
        db = tmp_path / "legacy.db"
        legacy = get_connection(db)
        try:
            legacy.executescript(self._LEGACY_SCHEMA)
            legacy.commit()
        finally:
            legacy.close()

        ensure_schema(db)

        conn = get_connection(db)
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(transactions)")}
            assert "category_audit_matched_rule" in cols
            assert "category_audit_confidence" in cols
        finally:
            conn.close()

    def test_migration_preserves_existing_rows(self, tmp_path: Path) -> None:
        db = tmp_path / "legacy.db"
        legacy = get_connection(db)
        try:
            legacy.executescript(self._LEGACY_SCHEMA)
            legacy.execute(
                "INSERT INTO transactions (forwarded_to, date_file_name, category) VALUES (?, ?, ?)",
                ("user@example.com", "2026.01.15_10.00_test.eml", "groceries"),
            )
            legacy.commit()
        finally:
            legacy.close()

        ensure_schema(db)

        conn = get_connection(db)
        try:
            row = conn.execute(
                "SELECT category, category_audit_matched_rule, category_audit_confidence"
                " FROM transactions WHERE forwarded_to = 'user@example.com'"
            ).fetchone()
            assert row["category"] == "groceries"
            assert row["category_audit_matched_rule"] is None
            assert row["category_audit_confidence"] is None
        finally:
            conn.close()

    def test_migration_is_idempotent(self, tmp_path: Path) -> None:
        """Re-running ensure_schema on an already-migrated DB must not raise (ALTER TABLE would duplicate)."""
        db = tmp_path / "migrated.db"
        ensure_schema(db)
        ensure_schema(db)
        ensure_schema(db)  # three times, just in case

        conn = get_connection(db)
        try:
            cols = [row[1] for row in conn.execute("PRAGMA table_info(transactions)")]
            # Each column appears exactly once.
            assert cols.count("category_audit_matched_rule") == 1
            assert cols.count("category_audit_confidence") == 1
        finally:
            conn.close()
