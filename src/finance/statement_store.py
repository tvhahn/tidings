"""SQLite persistence for statement import workflow.

Stores statement upload metadata, parsed transactions, reconciliation results,
user edits, and import outcomes so users can resume partially-completed imports.
"""

import contextlib
import hashlib
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.finance.local_db import get_connection, run_with_lock_retry

# `_assign_row_ids` is consumed by the statement-preview router helper (and the
# row-id test suite) to pre-compute ids that match the persisted rows; the
# underscore marks it internal to the statement-import subsystem.
__all__ = ["StatementStore", "_assign_row_ids", "row_id_for"]

# `row_id` is a stable per-row id used by `PATCH /api/v1/statements/{id}/transactions/{row_id}`.
# Replaces the positional `tx_index` shape, which was fragile under concurrent
# edits + reorderings + agent retries (per the sub-spec at
# `docs/specs/01_backend-as-platform/2026-04-30-statements-stable-row-ids/`).
#
# Format: `r` + 16 hex chars. The leading `r` makes the id non-numeric so the
# router can cleanly distinguish row_ids from legacy int paths and 410 the
# legacy shape without ambiguity.
_ROW_ID_PREFIX = "r"


def row_id_for(date: str, amount: Any, raw_description: str, dup_counter: int = 0) -> str:
    """Deterministic per-row id derived from content + a duplicate counter.

    Stable across re-parse (same input → same id) and across the lifetime
    of the row (the underlying fields don't change after parse). The
    `dup_counter` disambiguates true duplicates within a statement
    (same date + amount + description repeated).
    """
    amount_str = f"{float(amount):.2f}" if amount is not None else ""
    key = f"{date or ''}|{amount_str}|{raw_description or ''}|{dup_counter}"
    return _ROW_ID_PREFIX + hashlib.sha256(key.encode()).hexdigest()[:16]


def _assign_row_ids(rows: list[dict[str, Any]]) -> None:
    """Populate `row_id` on each row in place.

    Mutates the rows. Used at save_statement time and as the lazy-backfill
    path for rows that pre-date the `row_id` column.
    """
    counters: dict[tuple[str, Any, str], int] = {}
    for row in rows:
        date = row.get("date") or ""
        amount = row.get("amount")
        desc = row.get("raw_description") or ""
        key = (date, amount, desc)
        n = counters.get(key, 0)
        counters[key] = n + 1
        row["row_id"] = row_id_for(date, amount, desc, n)


class StatementStore:
    """SQLite-backed storage for statement import state."""

    DB_PATH = Path("data/statements.db")
    SCHEMA_VERSION = 1

    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or self.DB_PATH
        if os.environ.get("PYTEST_CURRENT_TEST") and self._db_path == self.DB_PATH:
            raise RuntimeError(
                "StatementStore must use a tmp db_path under pytest; "
                "the tests/conftest.py isolation fixture should have redirected this."
            )
        self._ensure_db()

    def _connect(self) -> sqlite3.Connection:
        # Shared connection factory (row_factory, WAL, busy_timeout, foreign_keys).
        # foreign_keys=ON was already set here, so the statements→transactions
        # ON DELETE CASCADE continues to be enforced unchanged.
        return get_connection(self._db_path)

    def _ensure_db(self):
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        # Wrap the fresh-file schema setup in the shared lock retry: two processes
        # creating this store at once race the WAL journal-mode switch, which
        # raises SQLITE_BUSY without honouring busy_timeout. The body is otherwise
        # idempotent (executescript IF NOT EXISTS, INSERT OR IGNORE, guarded
        # ALTERs), so a plain retry — no BEGIN IMMEDIATE — suffices here, matching
        # EmbeddingCache._ensure_db.
        run_with_lock_retry(self._create_schema_once)

    def _create_schema_once(self) -> None:
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(_SCHEMA_SQL)
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (id, version) VALUES (1, ?)",
                (self.SCHEMA_VERSION,),
            )
            # Migrations for new columns — suppress "column already exists" errors
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute("ALTER TABLE statement_transactions ADD COLUMN db_transaction_type TEXT")
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute("ALTER TABLE statements ADD COLUMN suspected_duplicate_count INTEGER NOT NULL DEFAULT 0")
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute("ALTER TABLE statement_transactions ADD COLUMN row_id TEXT")
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute("ALTER TABLE statements ADD COLUMN parsed_with_ai INTEGER NOT NULL DEFAULT 0")
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_statement_transactions_row_id "
                    "ON statement_transactions(statement_id, row_id)"
                )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def generate_statement_id(
        institution: str,
        account_type: str,
        period_start: str | None,
        period_end: str | None,
        filename: str,
    ) -> str:
        parts = "|".join(
            [
                institution,
                account_type,
                period_start or "",
                period_end or "",
                filename,
            ]
        )
        return hashlib.sha256(parts.encode()).hexdigest()[:16]

    def save_statement(
        self,
        statement: dict[str, Any],
        transaction_rows: list[dict[str, Any]],
    ) -> str:
        """Save or replace a statement and its transactions.

        Returns the statement_id.
        """
        sid = statement["id"]
        now = datetime.now(UTC).isoformat()

        conn = self._connect()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO statements (
                    id, filename, institution, account_type,
                    period_start, period_end, pdf_path,
                    uploaded_at, updated_at,
                    total_parsed, matched_count, ambiguous_count,
                    suspected_duplicate_count,
                    new_count, previously_imported_count, status,
                    parsed_with_ai
                ) VALUES (
                    :id, :filename, :institution, :account_type,
                    :period_start, :period_end, :pdf_path,
                    COALESCE(
                        (SELECT uploaded_at FROM statements WHERE id = :id),
                        :now
                    ),
                    :now,
                    :total_parsed, :matched_count, :ambiguous_count,
                    :suspected_duplicate_count,
                    :new_count, :previously_imported_count, :status,
                    :parsed_with_ai
                )""",
                {
                    **statement,
                    "now": now,
                    "status": statement.get("status", "pending_review"),
                    "suspected_duplicate_count": statement.get("suspected_duplicate_count", 0),
                    "parsed_with_ai": 1 if statement.get("parsed_with_ai") else 0,
                },
            )
            # Delete old transactions then reinsert
            conn.execute(
                "DELETE FROM statement_transactions WHERE statement_id = ?",
                (sid,),
            )
            _assign_row_ids(transaction_rows)
            for row in transaction_rows:
                # Set default action based on tier
                action = row.get("action")
                if action is None:
                    action = _default_action(
                        row.get("reconcile_tier", "new"),
                        row.get("company_differs", False),
                        row.get("enrichable", False),
                    )
                conn.execute(
                    """INSERT INTO statement_transactions (
                        statement_id, tx_index, row_id, reconcile_tier,
                        date, raw_description, cleaned_description,
                        amount, type, balance,
                        db_forwarded_to, db_date_file_name,
                        db_company, db_amount, db_category,
                        db_transaction_type,
                        company_differs, enrichable, reason,
                        candidates_json, suggested_category,
                        action, edited_company, edited_category,
                        action_result, acted_at
                    ) VALUES (
                        :statement_id, :tx_index, :row_id, :reconcile_tier,
                        :date, :raw_description, :cleaned_description,
                        :amount, :type, :balance,
                        :db_forwarded_to, :db_date_file_name,
                        :db_company, :db_amount, :db_category,
                        :db_transaction_type,
                        :company_differs, :enrichable, :reason,
                        :candidates_json, :suggested_category,
                        :action, :edited_company, :edited_category,
                        :action_result, :acted_at
                    )""",
                    {
                        "statement_id": sid,
                        "tx_index": row["tx_index"],
                        "row_id": row["row_id"],
                        "reconcile_tier": row["reconcile_tier"],
                        "date": row["date"],
                        "raw_description": row.get("raw_description", ""),
                        "cleaned_description": row.get("cleaned_description", ""),
                        "amount": row["amount"],
                        "type": row.get("type", "withdrawal"),
                        "balance": row.get("balance"),
                        "db_forwarded_to": row.get("db_forwarded_to"),
                        "db_date_file_name": row.get("db_date_file_name"),
                        "db_company": row.get("db_company"),
                        "db_amount": row.get("db_amount"),
                        "db_category": row.get("db_category"),
                        "db_transaction_type": row.get("db_transaction_type"),
                        "company_differs": row.get("company_differs", False),
                        "enrichable": row.get("enrichable", False),
                        "reason": row.get("reason"),
                        "candidates_json": row.get("candidates_json"),
                        "suggested_category": row.get("suggested_category", "miscellaneous"),
                        "action": action,
                        "edited_company": row.get("edited_company"),
                        "edited_category": row.get("edited_category"),
                        "action_result": row.get("action_result"),
                        "acted_at": row.get("acted_at"),
                    },
                )

            self._compute_and_update_status(conn, sid)
            conn.commit()
        finally:
            conn.close()
        return sid

    def get_statement(self, statement_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                f"SELECT s.*, {_OUTCOME_COUNT_SQL} "  # noqa: S608 — interpolates _OUTCOME_COUNT_SQL module constant; values bound via ?
                "FROM statements s "
                "LEFT JOIN statement_transactions t ON t.statement_id = s.id "
                "WHERE s.id = ? "
                "GROUP BY s.id",
                (statement_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_statements(self) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT s.*, {_OUTCOME_COUNT_SQL} "  # noqa: S608 — interpolates _OUTCOME_COUNT_SQL module constant; values bound via ?
                "FROM statements s "
                "LEFT JOIN statement_transactions t ON t.statement_id = s.id "
                "GROUP BY s.id "
                "ORDER BY s.uploaded_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def delete_statement(self, statement_id: str) -> bool:
        conn = self._connect()
        try:
            cursor = conn.execute(
                "DELETE FROM statements WHERE id = ?",
                (statement_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_transactions(self, statement_id: str) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM statement_transactions WHERE statement_id = ? ORDER BY tx_index",
                    (statement_id,),
                ).fetchall()
            ]
            # Lazy-backfill: any row from before the row_id migration shows
            # NULL here. Compute deterministically + persist so the next
            # caller (and the PATCH route) sees a stable id.
            missing = [r for r in rows if not r.get("row_id")]
            if missing:
                _assign_row_ids(missing)
                for r in missing:
                    conn.execute(
                        "UPDATE statement_transactions SET row_id = ? WHERE statement_id = ? AND tx_index = ?",
                        (r["row_id"], statement_id, r["tx_index"]),
                    )
                conn.commit()
            return rows
        finally:
            conn.close()

    def update_transaction_action(
        self,
        statement_id: str,
        tx_index: int,
        action: str,
        company: str | None = None,
        category: str | None = None,
    ) -> bool:
        """Internal write path keyed by the legacy positional index.

        Still used by `record_import_results` and the bulk handler, both of
        which construct results / payloads internally and never hand the
        index to a network consumer. The router-facing path is
        `update_transaction_action_by_row_id`.
        """
        conn = self._connect()
        try:
            parts = ["action = ?"]
            params: list[Any] = [action]
            if company is not None:
                parts.append("edited_company = ?")
                params.append(company)
            if category is not None:
                parts.append("edited_category = ?")
                params.append(category)
            params.extend([statement_id, tx_index])
            cursor = conn.execute(
                f"UPDATE statement_transactions SET {', '.join(parts)} WHERE statement_id = ? AND tx_index = ?",  # noqa: S608 — SET list is hardcoded column fragments; values bound via ?
                params,
            )
            if cursor.rowcount == 0:
                return False
            self._compute_and_update_status(conn, statement_id)
            conn.commit()
            return True
        finally:
            conn.close()

    def update_transaction_action_by_row_id(
        self,
        statement_id: str,
        row_id: str,
        action: str,
        company: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any] | None:
        """Update a single transaction by its stable row_id.

        Returns the updated row's `{tx_index, row_id, action}` so the route
        can echo something useful in the response. None when the row_id is
        unknown for this statement.
        """
        conn = self._connect()
        try:
            parts = ["action = ?"]
            params: list[Any] = [action]
            if company is not None:
                parts.append("edited_company = ?")
                params.append(company)
            if category is not None:
                parts.append("edited_category = ?")
                params.append(category)
            params.extend([statement_id, row_id])
            cursor = conn.execute(
                f"UPDATE statement_transactions SET {', '.join(parts)} WHERE statement_id = ? AND row_id = ?",  # noqa: S608 — SET list is hardcoded column fragments; values bound via ?
                params,
            )
            if cursor.rowcount == 0:
                return None
            existing = conn.execute(
                "SELECT tx_index FROM statement_transactions WHERE statement_id = ? AND row_id = ?",
                (statement_id, row_id),
            ).fetchone()
            self._compute_and_update_status(conn, statement_id)
            conn.commit()
            if not existing:
                return None
            return {"tx_index": existing["tx_index"], "row_id": row_id, "action": action}
        finally:
            conn.close()

    def bulk_update_actions(
        self,
        statement_id: str,
        updates: list[dict[str, Any]],
    ) -> int:
        conn = self._connect()
        try:
            count = 0
            for u in updates:
                parts = ["action = ?"]
                params: list[Any] = [u["action"]]
                if "company" in u and u["company"] is not None:
                    parts.append("edited_company = ?")
                    params.append(u["company"])
                if "category" in u and u["category"] is not None:
                    parts.append("edited_category = ?")
                    params.append(u["category"])
                params.extend([statement_id, u["tx_index"]])
                cursor = conn.execute(
                    f"UPDATE statement_transactions SET {', '.join(parts)} WHERE statement_id = ? AND tx_index = ?",  # noqa: S608 — SET list is hardcoded column fragments; values bound via ?
                    params,
                )
                count += cursor.rowcount
            self._compute_and_update_status(conn, statement_id)
            conn.commit()
            return count
        finally:
            conn.close()

    def record_import_results(
        self,
        statement_id: str,
        results: list[dict[str, Any]],
    ) -> None:
        """Record import outcomes for transactions.

        Each result dict: {tx_index, action_result, acted_at?}
        """
        now = datetime.now(UTC).isoformat()
        conn = self._connect()
        try:
            for r in results:
                conn.execute(
                    """UPDATE statement_transactions
                    SET action_result = ?, acted_at = ?
                    WHERE statement_id = ? AND tx_index = ?""",
                    (
                        r["action_result"],
                        r.get("acted_at", now),
                        statement_id,
                        r["tx_index"],
                    ),
                )
            self._compute_and_update_status(conn, statement_id)
            conn.commit()
        finally:
            conn.close()

    def capture_summary(self) -> dict[str, Any] | None:
        """Aggregate reconciliation outcomes into a personal email-capture rate.

        Joins ``statement_transactions.reconcile_tier`` to
        ``statements.institution`` over every imported statement:

        * ``caught`` = rows the email pipeline already had (tier ``matched``);
        * ``missed`` = rows only the statement surfaced (tiers ``new`` and
          ``previously_imported``);
        * ``ambiguous`` and ``suspected_duplicate`` are indeterminate and
          excluded from both sides.

        Aggregates the per-row tiers directly rather than the denormalized
        ``matched_count`` / ``new_count`` columns on ``statements`` (stored
        inputs, not recomputed). Returns ``None`` when no counted rows exist.
        Otherwise ``rate = caught / (caught + missed)`` overall, per institution,
        and per transaction ``type``; the two breakdown lists are sorted by name.
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT s.institution AS institution, t.type AS type, t.reconcile_tier AS tier
                FROM statement_transactions t
                JOIN statements s ON s.id = t.statement_id
                WHERE t.reconcile_tier IN ('matched', 'new', 'previously_imported')
                """
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return None

        overall_caught = 0
        overall_total = 0
        by_institution: dict[str, list[int]] = {}
        by_type: dict[str, list[int]] = {}
        for row in rows:
            caught = 1 if row["tier"] == "matched" else 0
            overall_caught += caught
            overall_total += 1
            inst = by_institution.setdefault(row["institution"], [0, 0])
            inst[0] += caught
            inst[1] += 1
            typ = by_type.setdefault(row["type"], [0, 0])
            typ[0] += caught
            typ[1] += 1

        return {
            "overall": {
                "caught": overall_caught,
                "total": overall_total,
                "rate": overall_caught / overall_total,
            },
            "by_institution": [
                {"institution": name, "caught": c, "total": t, "rate": c / t}
                for name, (c, t) in sorted(by_institution.items())
            ],
            "by_type": [
                {"type": name, "caught": c, "total": t, "rate": c / t} for name, (c, t) in sorted(by_type.items())
            ],
        }

    def _compute_and_update_status(self, conn: sqlite3.Connection, statement_id: str):
        """Recompute and persist statement status based on transaction states."""
        rows = conn.execute(
            "SELECT action, action_result FROM statement_transactions WHERE statement_id = ?",
            (statement_id,),
        ).fetchall()

        if not rows:
            status = "pending_review"
        else:
            has_result = any(r["action_result"] is not None for r in rows)
            all_resolved = all(r["action_result"] is not None or r["action"] == "skip" for r in rows)
            if all_resolved and has_result:
                status = "complete"
            elif has_result:
                status = "in_progress"
            else:
                status = "pending_review"

        now = datetime.now(UTC).isoformat()
        update_fields = {"status": status, "updated_at": now, "id": statement_id}
        if status == "complete":
            update_fields["completed_at"] = now
            conn.execute(
                "UPDATE statements SET status = :status, updated_at = :updated_at, "
                "completed_at = :completed_at WHERE id = :id",
                update_fields,
            )
        else:
            conn.execute(
                "UPDATE statements SET status = :status, updated_at = :updated_at WHERE id = :id",
                update_fields,
            )


_OUTCOME_COUNT_SQL = (
    "COALESCE(SUM(CASE WHEN t.action_result = 'imported' THEN 1 ELSE 0 END), 0) AS imported_count, "
    "COALESCE(SUM(CASE WHEN t.action_result = 'enriched' THEN 1 ELSE 0 END), 0) AS enriched_count, "
    "COALESCE(SUM(CASE WHEN t.action_result = 'updated' THEN 1 ELSE 0 END), 0) AS updated_count, "
    "COALESCE(SUM(CASE WHEN t.action_result = 'skipped' THEN 1 ELSE 0 END), 0) AS skipped_count, "
    "COALESCE(SUM(CASE WHEN t.action_result = 'duplicate' THEN 1 ELSE 0 END), 0) AS duplicate_count"
)


def _default_action(tier: str, company_differs: bool, enrichable: bool) -> str:
    if tier == "new":
        return "import"
    if tier == "matched":
        return "enrich" if company_differs else "skip"
    if tier == "ambiguous":
        return "enrich" if enrichable else "skip"
    # remaining tiers such as suspected duplicate or previously imported
    return "skip"


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    id INTEGER PRIMARY KEY,
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS statements (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    institution TEXT NOT NULL,
    account_type TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT,
    pdf_path TEXT,
    uploaded_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    total_parsed INTEGER NOT NULL DEFAULT 0,
    matched_count INTEGER NOT NULL DEFAULT 0,
    ambiguous_count INTEGER NOT NULL DEFAULT 0,
    new_count INTEGER NOT NULL DEFAULT 0,
    previously_imported_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending_review',
    parsed_with_ai INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS statement_transactions (
    statement_id TEXT NOT NULL,
    tx_index INTEGER NOT NULL,
    reconcile_tier TEXT NOT NULL,
    date TEXT NOT NULL,
    raw_description TEXT NOT NULL DEFAULT '',
    cleaned_description TEXT NOT NULL DEFAULT '',
    amount REAL NOT NULL,
    type TEXT NOT NULL DEFAULT 'withdrawal',
    balance REAL,
    db_forwarded_to TEXT,
    db_date_file_name TEXT,
    db_company TEXT,
    db_amount REAL,
    db_category TEXT,
    company_differs INTEGER NOT NULL DEFAULT 0,
    enrichable INTEGER NOT NULL DEFAULT 0,
    reason TEXT,
    candidates_json TEXT,
    suggested_category TEXT NOT NULL DEFAULT 'miscellaneous',
    action TEXT NOT NULL DEFAULT 'skip',
    edited_company TEXT,
    edited_category TEXT,
    action_result TEXT,
    acted_at TEXT,
    UNIQUE(statement_id, tx_index),
    FOREIGN KEY (statement_id) REFERENCES statements(id) ON DELETE CASCADE
);
"""
