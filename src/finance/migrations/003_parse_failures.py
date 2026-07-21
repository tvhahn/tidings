"""Migration 003 — parse-failure quarantine + extraction-audit column.

Two changes shipped in one migration so a single schema bump covers Phases 1
and 2 of the parse-failure-quarantine feature:

* Creates the ``parse_failures`` dead-letter table (+ status/received_at index)
  that holds unparseable bank emails for review/retry.
* Adds the ``extraction_audit_json`` column to ``transactions`` (Phase 2:
  provenance for AI-extracted rows).

Forward-only. On a fresh DB the core DDL in ``local_db._SCHEMA_SQL`` already
declares both, so the guarded ALTER is skipped; on an upgrading DB this is the
migration path. Skips the column ALTER if ``transactions`` is absent, mirroring
``002_category_audit_v2``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

version = 3
description = "add parse_failures table and transactions.extraction_audit_json column"


_PARSE_FAILURES_DDL = """
CREATE TABLE IF NOT EXISTS parse_failures (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    received_at TEXT NOT NULL,
    from_email TEXT,
    subject TEXT,
    file_name TEXT,
    detected_institution TEXT,
    failure_stage TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'quarantined',
    recovered_date_file_name TEXT,
    alert_classifier_result INTEGER,
    email_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_PARSE_FAILURES_INDEX = "CREATE INDEX IF NOT EXISTS idx_parse_failures_status ON parse_failures(status, received_at)"


def up(conn: sqlite3.Connection) -> None:
    conn.execute(_PARSE_FAILURES_DDL)
    conn.execute(_PARSE_FAILURES_INDEX)

    # Phase 2 column — guarded like 002: skip if transactions is absent, and
    # on a fresh DB the core DDL already declares it so the ALTER is skipped.
    table = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='transactions'").fetchone()
    if table is None:
        return
    existing = {row[1] for row in conn.execute("PRAGMA table_info(transactions)")}
    if "extraction_audit_json" not in existing:
        conn.execute("ALTER TABLE transactions ADD COLUMN extraction_audit_json TEXT")
