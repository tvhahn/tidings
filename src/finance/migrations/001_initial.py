"""Migration 001 — baseline marker.

Records the existing pre-versioning schema as version 1. No DDL runs here;
future schema changes ship as migrations 002, 003, etc. Having an explicit
baseline simplifies reasoning: after this runs, every local-backend database
has at least one row in ``schema_version``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

version = 1
description = "initial schema marker"


def up(conn: sqlite3.Connection) -> None:
    """No-op baseline marker.

    The core schema is created by ``local_db.ensure_schema``'s DDL before this
    runs. Having an explicit version-1 migration keeps the runner loop uniform:
    future migrations simply add 002, 003, …
    """
    _ = conn  # unused — intentional
    return
