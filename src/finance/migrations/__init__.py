"""Schema migration runner for the SQLite local backend.

A migration is a Python module in this package whose name matches ``NNN_<slug>.py``
and exposes module-level attributes:

* ``version`` (int) — monotonically increasing integer starting at 1.
* ``description`` (str) — human-readable one-line summary.
* ``up(conn: sqlite3.Connection) -> None`` — idempotent upgrade step. Called
  inside a transaction managed by :func:`apply_migrations`; do not call
  ``conn.commit()`` or ``conn.rollback()`` yourself.

Versions must form a contiguous sequence starting at 1. Gaps raise
``MigrationError`` defensively to prevent silently shipping a half-applied set.

Migration version ``1`` is intentionally a no-op marker: it records the
existing pre-versioning schema as the baseline. Future schema changes (new
tables, new columns) ship as migrations ``002``, ``003``, etc.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3
    from types import ModuleType

logger = logging.getLogger(__name__)

_MIGRATION_NAME_RE = re.compile(r"^(\d{3})_[a-z0-9_]+$")


class MigrationError(RuntimeError):
    """Raised when the migration set is malformed (gaps, duplicates, missing attrs)."""


@dataclass(frozen=True)
class _Migration:
    version: int
    description: str
    module: ModuleType


def _discover_migrations() -> list[_Migration]:
    """Find all migration modules in this package and return them sorted by version.

    Raises MigrationError if modules are malformed or versions collide / have gaps.
    """
    migrations: list[_Migration] = []
    package = importlib.import_module(__name__)
    for module_info in pkgutil.iter_modules(package.__path__):
        name = module_info.name
        if not _MIGRATION_NAME_RE.match(name):
            continue
        module = importlib.import_module(f"{__name__}.{name}")
        version = getattr(module, "version", None)
        description = getattr(module, "description", None)
        up = getattr(module, "up", None)
        if not isinstance(version, int) or version < 1:
            raise MigrationError(f"Migration {name!r} missing or invalid 'version' (must be int >= 1)")
        if not isinstance(description, str) or not description:
            raise MigrationError(f"Migration {name!r} missing non-empty 'description'")
        if not callable(up):
            raise MigrationError(f"Migration {name!r} missing callable 'up(conn)'")
        migrations.append(_Migration(version=version, description=description, module=module))

    migrations.sort(key=lambda m: m.version)

    # Defensive checks: no duplicates, no gaps, starts at 1.
    seen: set[int] = set()
    for i, m in enumerate(migrations, start=1):
        if m.version in seen:
            raise MigrationError(f"Duplicate migration version {m.version}")
        seen.add(m.version)
        if m.version != i:
            raise MigrationError(
                f"Migration versions must be contiguous starting at 1; expected {i}, found {m.version}"
            )

    return migrations


def _ensure_schema_version_table(conn: sqlite3.Connection) -> None:
    """Create the schema_version table if missing, upgrading the legacy shape if present.

    The pre-versioning placeholder used ``(id INTEGER PRIMARY KEY, version INTEGER NOT NULL)``
    and held a single row ``(1, 1)`` that was never consulted. We replace it with
    ``(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)`` and carry the
    baseline forward by inserting ``version = 1`` inside migration 001.
    """
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'").fetchone()
    if row is None:
        conn.execute("CREATE TABLE schema_version ( version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        return

    # Detect the legacy shape by inspecting columns.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(schema_version)")}
    if cols == {"version", "applied_at"}:
        return  # already the canonical shape
    if cols == {"id", "version"}:
        # Legacy placeholder — drop and recreate. No data worth preserving; the
        # single (1, 1) row was a marker, and migration 001 will re-insert.
        conn.execute("DROP TABLE schema_version")
        conn.execute("CREATE TABLE schema_version ( version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        return

    raise MigrationError(f"schema_version table exists with unexpected columns: {sorted(cols)!r}")


def _current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    if row is None or row[0] is None:
        return 0
    return int(row[0])


def _record_version(conn: sqlite3.Connection, version: int) -> None:
    """Mark ``version`` as applied.

    ``INSERT OR IGNORE`` keeps the write idempotent if a concurrent first-run
    creator already recorded the row. For a single-process upgrade the row never
    pre-exists (``pending`` only holds versions above ``current``), so this is
    identical to a plain ``INSERT`` there — behaviour is unchanged.
    """
    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
        (version, datetime.now(UTC).isoformat()),
    )


def apply_migrations(conn: sqlite3.Connection, *, manage_transactions: bool = True) -> list[int]:
    """Apply pending migrations. Returns the list of versions applied.

    Idempotent: a second call on the same connection (or process) is a no-op
    returning ``[]``.

    ``manage_transactions`` controls transaction ownership:

    * ``True`` (default, for standalone callers) — each migration runs inside
      its own ``BEGIN``/``COMMIT``; on failure that migration rolls back and
      earlier committed ones stay applied.
    * ``False`` — the caller already holds a write transaction (see
      ``local_db.ensure_schema``'s ``BEGIN IMMEDIATE``, which serialises
      concurrent first-run creation). Each migration then runs inline and the
      caller owns the surrounding commit/rollback, so the whole
      DDL + migration sequence is one atomic transaction.

    Out-of-order or skipped module files raise :class:`MigrationError` before
    any DDL runs (discovery-time validation). A database that already contains
    versions newer than the known migrations likewise raises.
    """
    _ensure_schema_version_table(conn)
    current = _current_version(conn)
    migrations = _discover_migrations()

    if migrations and current > migrations[-1].version:
        raise MigrationError(
            f"Database is at schema version {current} but this build only ships "
            f"up to version {migrations[-1].version}. Downgrade is not supported."
        )

    pending = [m for m in migrations if m.version > current]
    applied: list[int] = []
    for m in pending:
        logger.info("Applying migration %03d: %s", m.version, m.description)
        if manage_transactions:
            try:
                # Wrap each migration in its own transaction. SQLite's default
                # implicit-transaction mode means a BEGIN here is fine even though
                # callers may have their own autocommit expectations — we commit
                # before returning control.
                conn.execute("BEGIN")
                m.module.up(conn)
                _record_version(conn, m.version)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        else:
            # Inline: the caller's transaction spans every migration; do not open
            # or close one here (a nested BEGIN would raise).
            m.module.up(conn)
            _record_version(conn, m.version)
        applied.append(m.version)

    return applied


__all__ = ["MigrationError", "apply_migrations"]
