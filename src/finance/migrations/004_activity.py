"""Migration 004 — agent-activity ledger table.

Creates the ``activity`` append-only ledger (one row per mutating API write,
holding who did what plus the before/after images revert needs) and its
``ts`` index for the newest-first feed query.

Forward-only. On a fresh DB the core DDL in ``local_db._SCHEMA_SQL`` already
declares both, so the guarded ``CREATE TABLE IF NOT EXISTS`` is a no-op; on an
upgrading DB this is the migration path. The DDL text is kept byte-identical to
the ``_SCHEMA_SQL`` block so a fresh DB and a migrated DB end up with an
identical ``activity`` schema.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

version = 4
description = "add activity ledger table"


_ACTIVITY_DDL = """
CREATE TABLE IF NOT EXISTS activity (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    ts TEXT NOT NULL,
    principal_kind TEXT,
    principal_id TEXT,
    principal_label TEXT,
    operation_id TEXT,
    method TEXT,
    path TEXT,
    resource_id TEXT,
    summary TEXT,
    before_json TEXT,
    after_json TEXT,
    reversible INTEGER NOT NULL DEFAULT 0,
    reverted_at TEXT,
    reverted_by TEXT
)
"""

_ACTIVITY_INDEX = "CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity(ts)"


def up(conn: sqlite3.Connection) -> None:
    conn.execute(_ACTIVITY_DDL)
    conn.execute(_ACTIVITY_INDEX)
