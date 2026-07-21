"""Shared SQLite database initialization and utilities for the local backend.

All local service classes share a single database file (data/finance.db).
This module handles schema creation, WAL mode, and row-to-item mapping.
"""

import contextlib
import json
import sqlite3
import time
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path("data/finance.db")

# Shared SQL for config_store optimistic locking updates
CONFIG_UPDATE_SQL = (
    "UPDATE config_store SET data_json = ?, version = ?, updated_at = ? WHERE pk = ? AND sk = ? AND version = ?"
)
CONFIG_UPDATE_EXTRA_SQL = (
    "UPDATE config_store SET data_json = ?, version = ?, updated_at = ?,"
    " extra_json = ? WHERE pk = ? AND sk = ? AND version = ?"
)
CONFIG_INSERT_SQL = "INSERT INTO config_store (pk, sk, data_json, version, updated_at) VALUES (?, ?, ?, ?, ?)"
CONFIG_INSERT_EXTRA_SQL = (
    "INSERT INTO config_store (pk, sk, data_json, version, updated_at, extra_json) VALUES (?, ?, ?, ?, ?, ?)"
)

# Maps snake_case column names → PascalCase DynamoDB-style keys.
# API routers expect PascalCase keys from service methods.
_COLUMN_TO_KEY = {
    "forwarded_to": "ForwardedTo",
    "date_file_name": "DateFileName",
    "transaction_hash": "TransactionHash",
    "user_id": "UserId",
    "institution": "Institution",
    "amount": "Amount",
    "company": "Company",
    "transaction_type": "TransactionType",
    "category": "Category",
    "name": "Name",
    "date": "Date",
    "file_name": "FileName",
    "from_name": "FromName",
    "from_email": "FromEmail",
    "to_name": "ToName",
    "to_email": "ToEmail",
    "subject": "Subject",
    "body": "Body",
    "comment": "Comment",
    "ignored": "Ignored",
    "deleted_at": "DeletedAt",
    "category_audit_reviewed_at": "CategoryAudit",
    "category_audit_source": "_audit_source",
    "category_audit_matched_rule": "_audit_matched_rule",
    "category_audit_confidence": "_audit_confidence",
    "category_audit_json": "_audit_json",
    "category_audit_previous_category": "_audit_previous_category",
    "extraction_audit_json": "ExtractionAudit",
    "statement_source": "StatementSource",
    "context_json": "TransactionContext",
    "created_at": "CreatedAt",
}


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Create a new SQLite connection with WAL mode, busy timeout, and foreign keys.

    Sets PRAGMA journal_mode = WAL on every connection as defense-in-depth: the
    imap-poller and finance containers both call get_connection(), and either one
    could create the database file first. WAL is idempotent on an already-WAL database.

    Sets PRAGMA busy_timeout = 5000 so concurrent writes from two containers wait
    up to 5 seconds instead of raising OperationalError immediately.

    Note: busy_timeout does NOT cover the ``journal_mode = WAL`` switch on a
    freshly-created database — SQLite refuses a journal-mode change while another
    connection has the database open and returns SQLITE_BUSY *without* invoking
    the busy handler. Concurrent first-run creation is therefore made safe by the
    bounded retry in :func:`run_with_lock_retry`, which both this module's
    ``ensure_schema`` and ``embedding_cache`` wrap around their schema setup.
    """
    path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Concurrent first-run creation contends on two things busy_timeout cannot cover:
# the WAL journal-mode switch (SQLITE_BUSY without a busy-handler callback while
# another connection holds the fresh file open) and lock upgrades inside a
# transaction. The bounded retry absorbs both; the original error is re-raised
# once the deadline passes.
_SCHEMA_LOCK_RETRY_DEADLINE_S = 10.0
_SCHEMA_LOCK_RETRY_SLEEP_S = 0.05


def _is_locked_error(exc: sqlite3.OperationalError) -> bool:
    """True for the transient 'database is locked' / 'database is busy' family."""
    message = str(exc).lower()
    return "locked" in message or "busy" in message


def run_with_lock_retry[T](
    operation: Callable[[], T],
    *,
    deadline_s: float = _SCHEMA_LOCK_RETRY_DEADLINE_S,
    sleep_s: float = _SCHEMA_LOCK_RETRY_SLEEP_S,
) -> T:
    """Run ``operation`` retrying only the transient locked/busy family until a deadline.

    Shared first-run-creation guard for every local SQLite store whose schema
    setup opens a fresh file (``ensure_schema`` here, ``EmbeddingCache._ensure_db``).
    Any non-lock ``OperationalError`` — and any error once the deadline passes —
    propagates unchanged; only ``database is locked`` / ``busy`` is retried.
    """
    deadline = time.monotonic() + deadline_s
    while True:
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            if not _is_locked_error(exc) or time.monotonic() >= deadline:
                raise
            time.sleep(sleep_s)


def _iter_ddl_statements(script: str) -> Iterator[str]:
    """Yield individual DDL statements from the semicolon-delimited schema script.

    ``executescript`` issues an implicit COMMIT before it runs, which would break
    the surrounding ``BEGIN IMMEDIATE`` transaction, so the schema statements are
    executed one at a time instead. The schema contains only
    ``CREATE TABLE/INDEX IF NOT EXISTS`` statements with no inline ``;``; full
    ``--`` comment lines are stripped *before* splitting — a comment may itself
    contain a ``;`` (one does), which would otherwise break naive splitting.
    """
    lines = [line for line in script.splitlines() if not line.strip().startswith("--")]
    for chunk in "\n".join(lines).split(";"):
        statement = chunk.strip()
        if statement:
            yield statement


def ensure_schema(db_path: Path | None = None) -> None:
    """Create database and tables if they don't exist, and apply pending migrations.

    Runs the versioned migration runner from :mod:`src.finance.migrations` after
    the core DDL. The runner owns the ``schema_version`` table (shape:
    ``version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL``) and handles both
    fresh databases and legacy databases carrying the old placeholder table.

    Safe under concurrency: N processes calling this on the same fresh path all
    succeed. Creation runs inside one ``BEGIN IMMEDIATE`` write transaction (see
    :func:`_create_schema_once`), so the imap-poller and finance containers can
    race first-run creation — the losers wait, then find the schema fully formed
    and nothing left to do. A bounded retry guards residual lock contention.
    """
    path = db_path or DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    run_with_lock_retry(lambda: _create_schema_once(path))


def _create_schema_once(path: Path) -> None:
    """Run the DDL + column-migrations + versioned-migrations under one write txn.

    ``BEGIN IMMEDIATE`` acquires the write lock up front, which honours
    ``busy_timeout`` — unlike a deferred transaction that later upgrades a read
    lock to a write lock, which raises SQLITE_BUSY immediately regardless of the
    timeout. Serialising the whole sequence this way removes every first-run
    race at once: the schema DDL, the ``PRAGMA table_info``/``ALTER`` column
    probes, and the ``schema_version`` create + version inserts all run while a
    single creator holds the write lock.
    """
    conn = get_connection(path)
    try:
        # Take manual control of transactions so BEGIN IMMEDIATE / COMMIT are not
        # second-guessed by the sqlite3 module's implicit transaction handling.
        conn.isolation_level = None
        # journal_mode must be set outside a transaction; get_connection already
        # set it with busy_timeout in effect, this reaffirms it on the manual conn.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in _iter_ddl_statements(_SCHEMA_SQL):
                conn.execute(statement)
            _apply_column_migrations(conn)

            # Versioned migrations run after the baseline DDL so that migration
            # 001 (marker) and any future migrations see a fully-formed database.
            # manage_transactions=False keeps them inside this outer transaction.
            from src.finance.migrations import apply_migrations

            apply_migrations(conn, manage_transactions=False)
            conn.execute("COMMIT")
        except BaseException:
            # Release the write lock so a waiting creator can proceed. Guarded so
            # a rollback hiccup cannot mask the original failure.
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def _apply_column_migrations(conn: sqlite3.Connection) -> None:
    """Idempotently add columns introduced after the initial schema.

    SQLite's ALTER TABLE has no IF NOT EXISTS, so we probe with PRAGMA table_info
    first. Safe to call on every connection bootstrap.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(transactions)")}
    migrations = [
        ("category_audit_matched_rule", "ALTER TABLE transactions ADD COLUMN category_audit_matched_rule TEXT"),
        ("category_audit_confidence", "ALTER TABLE transactions ADD COLUMN category_audit_confidence REAL"),
        ("category_audit_json", "ALTER TABLE transactions ADD COLUMN category_audit_json TEXT"),
        (
            "category_audit_previous_category",
            "ALTER TABLE transactions ADD COLUMN category_audit_previous_category TEXT",
        ),
    ]
    for col, ddl in migrations:
        if col not in existing:
            conn.execute(ddl)


def row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a SQLite Row to a DynamoDB-style PascalCase dict.

    - Amounts are converted from float to Decimal for API compatibility.
    - Boolean 'ignored' (0/1) is converted to Python bool.
    - CategoryAudit is reconstructed from split columns.
    - TransactionContext is parsed from JSON.
    """
    item: dict[str, Any] = {}
    keys = row.keys()
    for col in keys:
        value = row[col]
        if value is None:
            continue

        pascal_key = _COLUMN_TO_KEY.get(col)
        if pascal_key is None:
            continue
        if pascal_key.startswith("_"):
            continue  # Internal columns handled specially

        if col == "amount":
            item["Amount"] = Decimal(str(value))
        elif col == "ignored":
            item["Ignored"] = bool(value)
        elif col == "category_audit_reviewed_at":
            source = row["category_audit_source"] if "category_audit_source" in keys else None
            audit: dict[str, Any] = {"reviewed_at": value, "source": source or "unknown"}
            if "category_audit_matched_rule" in keys:
                matched = row["category_audit_matched_rule"]
                if matched is not None:
                    audit["matched_rule"] = matched
            if "category_audit_confidence" in keys:
                confidence = row["category_audit_confidence"]
                if confidence is not None:
                    audit["confidence"] = confidence
            if "category_audit_previous_category" in keys:
                prev_cat = row["category_audit_previous_category"]
                if prev_cat is not None:
                    audit["previous_category"] = prev_cat
            if "category_audit_json" in keys:
                blob = row["category_audit_json"]
                if blob:
                    try:
                        extra = json.loads(blob)
                    except (json.JSONDecodeError, TypeError):
                        extra = {}
                    if isinstance(extra, dict):
                        for k, v in extra.items():
                            audit.setdefault(k, v)
            item["CategoryAudit"] = audit
        elif col == "extraction_audit_json":
            try:
                extraction = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(extraction, dict):
                item["ExtractionAudit"] = extraction
        elif col == "context_json":
            try:
                ctx = json.loads(value)
                # Convert numeric values to Decimal for consistency
                for k, v in ctx.items():
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        ctx[k] = Decimal(str(v))
                item["TransactionContext"] = ctx
            except (json.JSONDecodeError, TypeError):
                pass
        else:
            item[pascal_key] = value

    return item


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS transactions (
    forwarded_to TEXT NOT NULL,
    date_file_name TEXT NOT NULL,
    transaction_hash TEXT,
    user_id TEXT,
    institution TEXT,
    amount REAL,
    company TEXT,
    transaction_type TEXT,
    category TEXT,
    name TEXT,
    date TEXT,
    file_name TEXT,
    from_name TEXT,
    from_email TEXT,
    to_name TEXT,
    to_email TEXT,
    subject TEXT,
    body TEXT,
    comment TEXT,
    ignored INTEGER NOT NULL DEFAULT 0,
    deleted_at TEXT,
    category_audit_reviewed_at TEXT,
    category_audit_source TEXT,
    category_audit_matched_rule TEXT,
    category_audit_confidence REAL,
    category_audit_json TEXT,
    category_audit_previous_category TEXT,
    extraction_audit_json TEXT,
    statement_source TEXT,
    context_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (forwarded_to, date_file_name)
);

CREATE INDEX IF NOT EXISTS idx_transactions_hash
    ON transactions(forwarded_to, transaction_hash);
CREATE INDEX IF NOT EXISTS idx_transactions_category
    ON transactions(category);
CREATE INDEX IF NOT EXISTS idx_transactions_date_prefix
    ON transactions(forwarded_to, date_file_name);
CREATE INDEX IF NOT EXISTS idx_transactions_date_file_name
    ON transactions(date_file_name);

CREATE TABLE IF NOT EXISTS config_store (
    pk TEXT NOT NULL,
    sk TEXT NOT NULL,
    data_json TEXT NOT NULL DEFAULT '{}',
    version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT,
    extra_json TEXT,
    PRIMARY KEY (pk, sk)
);

-- Dead-letter store for unparseable bank emails (migration 003).
-- Declared here too so fresh DBs match migrated ones (the established pattern).
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
);

CREATE INDEX IF NOT EXISTS idx_parse_failures_status
    ON parse_failures(status, received_at);

-- Append-only agent-activity ledger (migration 004). Declared here too so
-- fresh DBs match migrated ones; the CREATE body is byte-identical to
-- migrations/004_activity.py so the two schemas can never drift.
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
);

CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity(ts);
"""
