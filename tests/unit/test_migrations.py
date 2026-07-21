"""Tests for the versioned SQLite migration runner (src/finance/migrations)."""

from __future__ import annotations

import sqlite3
import sys
import types
from typing import TYPE_CHECKING, Any

import pytest

from src.finance import migrations
from src.finance.migrations import MigrationError, apply_migrations

if TYPE_CHECKING:
    from collections.abc import Iterator


def _fresh_conn() -> sqlite3.Connection:
    """Return a new in-memory SQLite connection with typical pragmas."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _shipped_versions() -> list[int]:
    """Versions of every real migration shipped in this build."""
    return sorted(int(m.name.split("_", 1)[0]) for m in migrations.pkgutil.iter_modules(migrations.__path__))


class TestApplyMigrationsFresh:
    def test_creates_schema_version_table(self) -> None:
        conn = _fresh_conn()
        try:
            apply_migrations(conn)
            row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'").fetchone()
            assert row is not None
        finally:
            conn.close()

    def test_records_all_shipped_migrations_on_fresh_db(self) -> None:
        # Note: ensure_schema() runs the core DDL before this in production —
        # migrations that depend on a table existing need to be tested via the
        # service tests. This unit test only asserts the runner sees every
        # shipped migration and records each row in schema_version.
        from src.finance.local_db import _SCHEMA_SQL

        conn = _fresh_conn()
        try:
            conn.executescript(_SCHEMA_SQL)
            applied = apply_migrations(conn)
            assert applied == _shipped_versions()

            rows = conn.execute("SELECT version, applied_at FROM schema_version ORDER BY version").fetchall()
            assert [r["version"] for r in rows] == _shipped_versions()
            for r in rows:
                assert isinstance(r["applied_at"], str)
                assert r["applied_at"]
        finally:
            conn.close()

    def test_schema_version_table_has_canonical_columns(self) -> None:
        conn = _fresh_conn()
        try:
            apply_migrations(conn)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(schema_version)")}
            assert cols == {"version", "applied_at"}
        finally:
            conn.close()


class TestIdempotency:
    def test_second_call_is_noop(self) -> None:
        from src.finance.local_db import _SCHEMA_SQL

        conn = _fresh_conn()
        try:
            conn.executescript(_SCHEMA_SQL)
            first = apply_migrations(conn)
            second = apply_migrations(conn)
            assert first == _shipped_versions()
            assert second == []
        finally:
            conn.close()

    def test_repeated_calls_do_not_duplicate_rows(self) -> None:
        from src.finance.local_db import _SCHEMA_SQL

        conn = _fresh_conn()
        try:
            conn.executescript(_SCHEMA_SQL)
            for _ in range(5):
                apply_migrations(conn)
            count = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
            assert count == len(_shipped_versions())
        finally:
            conn.close()


class TestLegacyTableUpgrade:
    """Pre-versioning DBs carried a (id INTEGER PRIMARY KEY, version INTEGER) placeholder."""

    def test_drops_and_recreates_legacy_shape(self) -> None:
        from src.finance.local_db import _SCHEMA_SQL

        conn = _fresh_conn()
        try:
            conn.executescript(_SCHEMA_SQL)
            # Replace the default schema_version with the legacy placeholder shape.
            conn.execute("DROP TABLE IF EXISTS schema_version")
            conn.execute("CREATE TABLE schema_version (id INTEGER PRIMARY KEY, version INTEGER NOT NULL)")
            conn.execute("INSERT INTO schema_version (id, version) VALUES (1, 1)")
            conn.commit()

            applied = apply_migrations(conn)
            assert applied == _shipped_versions()  # Re-applies on freshly-rebuilt table

            cols = {r[1] for r in conn.execute("PRAGMA table_info(schema_version)")}
            assert cols == {"version", "applied_at"}

            rows = conn.execute("SELECT version FROM schema_version ORDER BY version").fetchall()
            assert [r["version"] for r in rows] == _shipped_versions()
        finally:
            conn.close()

    def test_unrecognised_shape_raises(self) -> None:
        conn = _fresh_conn()
        try:
            conn.execute("CREATE TABLE schema_version (foo TEXT, bar TEXT)")
            conn.commit()
            with pytest.raises(MigrationError):
                apply_migrations(conn)
        finally:
            conn.close()


class TestDiscoveryValidation:
    """Defensive checks: malformed migration sets must fail loudly, not silently."""

    def _inject(self, monkeypatch: pytest.MonkeyPatch, *modules: tuple[str, dict[str, Any]]) -> None:
        """Temporarily register fake migration modules under src.finance.migrations."""
        original_modules = dict(sys.modules)
        for name, attrs in modules:
            full_name = f"src.finance.migrations.{name}"
            mod = types.ModuleType(full_name)
            for k, v in attrs.items():
                setattr(mod, k, v)
            sys.modules[full_name] = mod

        real_iter = migrations.pkgutil.iter_modules

        def fake_iter(path: Any) -> Iterator[Any]:
            # Skip ALL real migrations so the fakes are the only set under test.
            # New shipped migrations would otherwise sneak into discovery and
            # invalidate the gap/duplicate scenarios.
            _ = real_iter
            for name, _attrs in modules:
                yield types.SimpleNamespace(name=name, ispkg=False, module_finder=None)

        monkeypatch.setattr(migrations.pkgutil, "iter_modules", fake_iter)

        def restore() -> None:
            sys.modules.clear()
            sys.modules.update(original_modules)

        monkeypatch.setattr(migrations, "_restore_sentinel", restore, raising=False)

    def test_gap_in_versions_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._inject(
            monkeypatch,
            ("001_base", {"version": 1, "description": "base", "up": lambda conn: None}),
            ("003_skip", {"version": 3, "description": "skip", "up": lambda conn: None}),
        )
        conn = _fresh_conn()
        try:
            with pytest.raises(MigrationError, match="contiguous"):
                apply_migrations(conn)
        finally:
            conn.close()

    def test_duplicate_version_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._inject(
            monkeypatch,
            ("001_a", {"version": 1, "description": "a", "up": lambda conn: None}),
            ("001_b", {"version": 1, "description": "b", "up": lambda conn: None}),
        )
        conn = _fresh_conn()
        try:
            with pytest.raises(MigrationError):
                apply_migrations(conn)
        finally:
            conn.close()

    def test_missing_version_attribute_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._inject(
            monkeypatch,
            ("001_broken", {"description": "no version", "up": lambda conn: None}),
        )
        conn = _fresh_conn()
        try:
            with pytest.raises(MigrationError, match="version"):
                apply_migrations(conn)
        finally:
            conn.close()

    def test_db_ahead_of_shipped_migrations_raises(self) -> None:
        """If the DB somehow reports a version newer than this build knows, bail out."""
        conn = _fresh_conn()
        try:
            conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (999, '2099-01-01T00:00:00+00:00')")
            conn.commit()
            with pytest.raises(MigrationError, match="Downgrade"):
                apply_migrations(conn)
        finally:
            conn.close()


class TestTransactionalFailure:
    """A failing migration must roll back its own DDL and leave version untouched."""

    def test_failure_rolls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.finance.local_db import _SCHEMA_SQL

        def boom(conn: sqlite3.Connection) -> None:
            conn.execute("CREATE TABLE side_effect (x INTEGER)")
            raise RuntimeError("kaboom")

        # Pick the next version above whatever real migrations ship today so the
        # fake doesn't collide as new migrations land.
        shipped = _shipped_versions()
        fake_version = (max(shipped) if shipped else 0) + 1
        fake_basename = f"{fake_version:03d}_failing"
        fake_name = f"src.finance.migrations.{fake_basename}"
        mod = types.ModuleType(fake_name)
        mod.version = fake_version  # type: ignore[attr-defined]
        mod.description = "failing"  # type: ignore[attr-defined]
        mod.up = boom  # type: ignore[attr-defined]
        sys.modules[fake_name] = mod

        real_iter = migrations.pkgutil.iter_modules

        def fake_iter(path: Any) -> Iterator[Any]:
            yield from real_iter(path)
            yield types.SimpleNamespace(name=fake_basename, ispkg=False, module_finder=None)

        monkeypatch.setattr(migrations.pkgutil, "iter_modules", fake_iter)

        conn = _fresh_conn()
        try:
            conn.executescript(_SCHEMA_SQL)
            with pytest.raises(RuntimeError, match="kaboom"):
                apply_migrations(conn)
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert "side_effect" not in tables
            # Real migrations committed before the failing fake ran; only those
            # versions should be recorded.
            rows = sorted(r["version"] for r in conn.execute("SELECT version FROM schema_version"))
            assert rows == shipped
        finally:
            conn.close()
            sys.modules.pop(fake_name, None)
