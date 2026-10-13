"""Migration 005 — DuplicateOf column for repeated bank alerts.

Adds ``duplicate_of`` (TEXT) to ``transactions``: the ``date_file_name`` of the
row an email transaction repeats. Set together with ``ignored = 1`` when
ingestion stores a re-sent or twice-delivered alert (issue #86; see
``src/finance/duplicate_alerts.py``). Kept after a restore as provenance.

Forward-only. On a fresh DB the core DDL already declares the column, so the
PRAGMA probe skips the ALTER; legacy rows stay NULL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

version = 5
description = "add duplicate_of column to transactions"


def up(conn: sqlite3.Connection) -> None:
    table = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='transactions'").fetchone()
    if table is None:
        return
    existing = {row[1] for row in conn.execute("PRAGMA table_info(transactions)")}
    if "duplicate_of" not in existing:
        conn.execute("ALTER TABLE transactions ADD COLUMN duplicate_of TEXT")
