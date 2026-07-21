"""Concurrency regression tests for first-run SQLite schema creation.

Simulates N containers/processes importing the app and hitting the *same*
fresh database path at the same instant — the race that made the pytest-xdist
backend suite fail ~1 run in 3. On a clean checkout (no ``data/*.db``) the
xdist workers import ``src.api.dependencies``, which runs
``create_transactions_db()`` at import time, which calls ``ensure_schema`` on a
brand-new ``data/demo.db``. Two workers creating it concurrently raced on the
DDL + migration sequence and raised, in three observed forms:

* ``sqlite3.OperationalError: database is locked`` (the schema_version INSERT
  upgrading a read lock to a write lock — busy_timeout does not wait on lock
  upgrades),
* ``table schema_version already exists`` (two workers both CREATE it), and
* ``database is locked`` from the ``PRAGMA journal_mode = WAL`` in
  ``get_connection`` (WAL switch races before busy_timeout is even set).

These tests pin the invariant: **N concurrent ``ensure_schema`` calls on one
fresh path all succeed (some may wait; none may raise) and the schema-version
bookkeeping is written exactly once.**

Uses the ``spawn`` start method explicitly — ``fork`` + threads + sqlite is its
own flake source, and the production race is genuinely cross-process. Each
round funnels every worker through a shared wall-clock spin-gate so they enter
``ensure_schema`` within scheduler granularity; without that tight start,
process-spawn jitter spreads the calls out and the race hides.
"""

from __future__ import annotations

import multiprocessing as mp
import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

# Enough concurrency + rounds to lose the race reliably on unpatched code,
# small enough that the file stays a couple of seconds of wall time.
_WORKERS = 8
_ROUNDS = 2
# Lead time for every spawned worker to import + reach the spin-gate before the
# shared start instant. Comfortably longer than a cold import on a loaded box.
_START_DELAY_S = 0.4
_BARRIER_TIMEOUT = 30.0
_JOIN_TIMEOUT = 30.0


def _shipped_versions() -> list[int]:
    """Versions of every real migration shipped in this build."""
    from src.finance import migrations

    return sorted(int(m.name.split("_", 1)[0]) for m in migrations.pkgutil.iter_modules(migrations.__path__))


def _spin_until(start_at: object) -> None:
    """Busy-wait to the shared start instant so all workers fire together."""
    target = start_at.value  # type: ignore[attr-defined]
    while time.time() < target:
        pass


def _ensure_schema_worker(db_path: str, barrier: object, start_at: object, results: object) -> None:
    """Child entrypoint: create the schema on the shared path, report outcome.

    Always puts exactly one ``(status, detail)`` tuple on ``results`` so the
    parent can read a fixed number of messages without racing on join.
    """
    from src.finance.local_db import ensure_schema

    try:
        barrier.wait(timeout=_BARRIER_TIMEOUT)  # type: ignore[attr-defined]
        _spin_until(start_at)
        ensure_schema(Path(db_path))
    except BaseException:  # report any failure verbatim to the parent
        results.put(("error", traceback.format_exc()))  # type: ignore[attr-defined]
    else:
        results.put(("ok", ""))  # type: ignore[attr-defined]


def _transactions_db_worker(db_path: str, barrier: object, start_at: object, results: object) -> None:
    """Child entrypoint: build ``TransactionsDBLocal`` (its ``__init__`` runs ensure_schema)."""
    from src.finance.transaction_db_local import TransactionsDBLocal

    try:
        barrier.wait(timeout=_BARRIER_TIMEOUT)  # type: ignore[attr-defined]
        _spin_until(start_at)
        TransactionsDBLocal(db_path=Path(db_path))
    except BaseException:  # report any failure verbatim to the parent
        results.put(("error", traceback.format_exc()))  # type: ignore[attr-defined]
    else:
        results.put(("ok", ""))  # type: ignore[attr-defined]


def _embedding_cache_worker(db_path: str, barrier: object, start_at: object, results: object) -> None:
    """Child entrypoint: build ``EmbeddingCache`` (its ``__init__`` runs _ensure_db) and write once."""
    from src.finance.embedding_cache import EmbeddingCache

    try:
        barrier.wait(timeout=_BARRIER_TIMEOUT)  # type: ignore[attr-defined]
        _spin_until(start_at)
        cache = EmbeddingCache(db_path=Path(db_path))
        cache.put_many([("acme corp", [0.1, 0.2, 0.3])])
    except BaseException:  # report any failure verbatim to the parent
        results.put(("error", traceback.format_exc()))  # type: ignore[attr-defined]
    else:
        results.put(("ok", ""))  # type: ignore[attr-defined]


def _statement_store_worker(db_path: str, barrier: object, start_at: object, results: object) -> None:
    """Child entrypoint: build ``StatementStore`` (its ``__init__`` runs _ensure_db)."""
    from src.finance.statement_store import StatementStore

    try:
        barrier.wait(timeout=_BARRIER_TIMEOUT)  # type: ignore[attr-defined]
        _spin_until(start_at)
        StatementStore(db_path=Path(db_path))
    except BaseException:  # report any failure verbatim to the parent
        results.put(("error", traceback.format_exc()))  # type: ignore[attr-defined]
    else:
        results.put(("ok", ""))  # type: ignore[attr-defined]


def _run_one_round(target: Callable[..., None], db_path: Path) -> list[str]:
    """Launch ``_WORKERS`` spawn processes at ``target`` on ``db_path``; return error tracebacks.

    Drains a fixed number of result messages before joining so a full queue
    pipe can never deadlock the join, then fails loudly on any non-zero child
    exit.
    """
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(_WORKERS)
    start_at = ctx.Value("d", time.time() + _START_DELAY_S)
    results: mp.Queue = ctx.Queue()

    procs = [ctx.Process(target=target, args=(str(db_path), barrier, start_at, results)) for _ in range(_WORKERS)]
    for proc in procs:
        proc.start()

    errors: list[str] = []
    for _ in range(_WORKERS):
        status, detail = results.get(timeout=_JOIN_TIMEOUT)
        if status == "error":
            errors.append(detail)

    for proc in procs:
        proc.join(timeout=_JOIN_TIMEOUT)
        assert proc.exitcode == 0, f"worker exited with code {proc.exitcode!r} (expected clean exit)"

    return errors


def _assert_schema_exactly_once(db_path: Path) -> None:
    """The created DB has the core tables and each migration recorded exactly once."""
    from src.finance.local_db import get_connection

    conn = get_connection(db_path)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "transactions" in tables
        assert "config_store" in tables
        assert "schema_version" in tables

        versions = [r[0] for r in conn.execute("SELECT version FROM schema_version ORDER BY version").fetchall()]
        assert versions == _shipped_versions(), f"schema_version rows not exactly-once: {versions!r}"
    finally:
        conn.close()


def _assert_embedding_cache_ready(db_path: Path) -> None:
    """The created cache has its table and exactly one row (all workers wrote the same key)."""
    from src.finance.local_db import get_connection

    conn = get_connection(db_path)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "embedding_cache" in tables

        count = conn.execute("SELECT COUNT(*) FROM embedding_cache").fetchone()[0]
        assert count == 1, f"embedding_cache should hold one row (INSERT OR IGNORE), got {count}"
    finally:
        conn.close()


def _assert_statement_store_ready(db_path: Path) -> None:
    """The created store has its tables and exactly one schema_version row."""
    from src.finance.local_db import get_connection

    conn = get_connection(db_path)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "statements" in tables
        assert "statement_transactions" in tables

        count = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
        assert count == 1, f"schema_version should hold one row (INSERT OR IGNORE), got {count}"
    finally:
        conn.close()


def _run_concurrent_rounds(target: Callable[..., None], tmp_path: Path, assert_ready: Callable[[Path], None]) -> None:
    """Drive ``_ROUNDS`` independent fresh-path races and assert each is clean."""
    for round_index in range(_ROUNDS):
        db_path = tmp_path / f"round_{round_index}" / "store.db"
        db_path.parent.mkdir(parents=True)

        errors = _run_one_round(target, db_path)

        assert not errors, f"round {round_index}: {len(errors)} worker(s) failed; first traceback:\n{errors[0]}"
        assert_ready(db_path)


class TestConcurrentFirstRun:
    def test_ensure_schema_survives_concurrent_first_run(self, tmp_path: Path) -> None:
        """8 processes calling ensure_schema on one fresh path: all succeed, schema recorded once."""
        _run_concurrent_rounds(_ensure_schema_worker, tmp_path, _assert_schema_exactly_once)

    def test_transactions_db_init_survives_concurrent_first_run(self, tmp_path: Path) -> None:
        """Same race through the real construction path: TransactionsDBLocal.__init__."""
        _run_concurrent_rounds(_transactions_db_worker, tmp_path, _assert_schema_exactly_once)

    def test_embedding_cache_survives_concurrent_first_run(self, tmp_path: Path) -> None:
        """EmbeddingCache first-run creation races the WAL switch; the shared retry absorbs it."""
        _run_concurrent_rounds(_embedding_cache_worker, tmp_path, _assert_embedding_cache_ready)

    def test_statement_store_survives_concurrent_first_run(self, tmp_path: Path) -> None:
        """StatementStore first-run creation races the WAL switch; the shared retry absorbs it."""
        _run_concurrent_rounds(_statement_store_worker, tmp_path, _assert_statement_store_ready)
