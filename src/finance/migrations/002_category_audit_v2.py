"""Migration 002 — CategoryAudit v2 columns.

Adds two columns to ``transactions``:

* ``category_audit_json`` (TEXT) — JSON blob carrying v2 audit fields that
  aren't worth their own column: ``tier``, ``previous_source``, ``model``,
  ``fallback_reason``, ``schema_version``.
* ``category_audit_previous_category`` (TEXT) — the prior ``category`` value
  when an update overwrote a previously-set one. Kept as a dedicated column
  because "show me transactions whose category changed from X" is a likely
  future query.

Forward-only. Legacy rows simply have NULL in both columns; the read path
fills sensible defaults via :func:`category_audit.normalize_audit`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

version = 2
description = "add category_audit_json and category_audit_previous_category columns"


def up(conn: sqlite3.Connection) -> None:
    # On a fresh DB the core DDL already declares both columns, so the
    # PRAGMA returns a populated row set and the ALTER is skipped. On a v1
    # DB this is the upgrade path.
    table = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='transactions'").fetchone()
    if table is None:
        return
    existing = {row[1] for row in conn.execute("PRAGMA table_info(transactions)")}
    if "category_audit_json" not in existing:
        conn.execute("ALTER TABLE transactions ADD COLUMN category_audit_json TEXT")
    if "category_audit_previous_category" not in existing:
        conn.execute("ALTER TABLE transactions ADD COLUMN category_audit_previous_category TEXT")
