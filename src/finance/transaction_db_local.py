"""SQLite implementation of TransactionsDB — mirrors the DynamoDB public API."""

import json
import logging
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from dateutil.parser import parse as dateutil_parse

from src.finance.app_timezone import get_tzinfos
from src.finance.category_audit import build_audit
from src.finance.local_db import DEFAULT_DB_PATH, ensure_schema, get_connection, row_to_item
from src.finance.transaction_db_base import TransactionsDBBase
from src.finance.transaction_hash import bump_hash_occurrence, generate_transaction_hash

if TYPE_CHECKING:
    from src.finance.protocols import TransactionItem

logger = logging.getLogger(__name__)

_DEDICATED_AUDIT_KEYS = {"reviewed_at", "source", "matched_rule", "confidence", "previous_category"}

# Month-scoped filters use GLOB, not LIKE: GLOB is case-sensitive, so SQLite can
# rewrite the 'YYYY.MM*' prefix into an index range on date_file_name. LIKE is
# case-insensitive and cannot use the BINARY-collated indexes, forcing a scan.
# The prefix is digits and a dot — no GLOB metacharacters.
_QUERY_MONTH_PARTITION_SQL = """SELECT forwarded_to, date_file_name, amount, category, company,
          transaction_type, deleted_at, ignored
   FROM transactions
   WHERE forwarded_to = ? AND date_file_name GLOB ?"""
_LATEST_IN_MONTH_SQL = "SELECT MAX(date_file_name) AS latest FROM transactions WHERE date_file_name GLOB ?"


def _split_audit(
    audit: dict[str, Any] | None,
) -> tuple[str | None, str | None, str | None, float | None, str | None, str | None]:
    """Decompose an audit dict into the columns SQLite stores.

    Returns ``(reviewed_at, source, matched_rule, confidence, previous_category, json_blob)``.
    The blob carries every audit field NOT in :data:`_DEDICATED_AUDIT_KEYS`
    (e.g. ``tier``, ``previous_source``, ``model``, ``fallback_reason``,
    ``schema_version``). Returns all-``None`` for an empty/None audit.
    """
    if not audit:
        return None, None, None, None, None, None
    extras = {k: v for k, v in audit.items() if k not in _DEDICATED_AUDIT_KEYS}
    blob = json.dumps(extras, default=str) if extras else None
    confidence = audit.get("confidence")
    if isinstance(confidence, Decimal):
        confidence = float(confidence)
    return (
        audit.get("reviewed_at"),
        audit.get("source"),
        audit.get("matched_rule"),
        confidence,
        audit.get("previous_category"),
        blob,
    )


class TransactionsDBLocal(TransactionsDBBase):
    """SQLite-backed transaction storage with the same public API as TransactionsDB."""

    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or DEFAULT_DB_PATH
        ensure_schema(self._db_path)
        # Per-thread: the connection an in-progress bulk import shares across
        # its writes. Instances are shared by concurrent request threads, so
        # this must never leak into another thread's calls.
        self._bulk = threading.local()

    def _connect(self) -> sqlite3.Connection:
        return get_connection(self._db_path)

    @contextmanager
    def _session_conn(self) -> Iterator[sqlite3.Connection]:
        """Yield this thread's bulk-session connection, or a fresh one committed on success.

        Inside :meth:`_bulk_write_session` every write shares one connection and
        the session commits once at the end. Outside it this is the usual
        open → work → commit → close cycle.
        """
        shared: sqlite3.Connection | None = getattr(self._bulk, "conn", None)
        if shared is not None:
            yield shared
            return
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def _bulk_write_session(self) -> Iterator[None]:
        """Run a bulk import on one connection and one transaction.

        Rows that fail individually are still counted and skipped by the
        caller (SQLite rolls back just the failing statement); everything
        written commits together when the batch finishes.
        """
        conn = self._connect()
        self._bulk.conn = conn
        try:
            yield
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            self._bulk.conn = None
            conn.close()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def add_transaction(
        self,
        transaction_data: dict[str, Any],
        category_audit: dict[str, Any] | None = None,
        extraction_audit: dict[str, Any] | None = None,
    ) -> str | bool | None:
        """Add a new transaction. Returns DateFileName if written, False if dup, None if invalid.

        When `category_audit` is provided, its fields (`reviewed_at`, `source`,
        `matched_rule`, `confidence`) are persisted to the paired SQLite columns.

        When `extraction_audit` is provided, the whole dict is serialized to the
        `extraction_audit_json` column (provenance for AI-recovered rows).
        """
        missing = self._validate_required_fields(
            transaction_data,
            ["forwarded_to", "file_name", "date", "amount", "institution", "transaction_type"],
        )
        if missing:
            logger.error("Missing required field: %s", missing)
            return None

        transaction_hash = generate_transaction_hash(transaction_data)

        conn = self._connect()
        try:
            # Check duplicate
            row = conn.execute(
                "SELECT 1 FROM transactions WHERE forwarded_to = ? AND transaction_hash = ?",
                (transaction_data["forwarded_to"], transaction_hash),
            ).fetchone()
            if row:
                logger.info("Duplicate transaction (hash=%s). Skipping.", transaction_hash)
                return False

            # Parse date for DateFileName
            date_obj = dateutil_parse(transaction_data["date"], tzinfos=get_tzinfos())
            formatted = date_obj.strftime("%Y.%m.%d_%H.%M")
            date_file_name = f"{formatted}_{transaction_data['file_name'].split('/')[-1]}"

            cat = self._normalize_category(transaction_data)
            amount = float(transaction_data["amount"]) if transaction_data.get("amount") is not None else None

            reviewed_at, source, matched_rule, confidence, prev_cat, audit_json = _split_audit(category_audit)
            extraction_json = json.dumps(extraction_audit, default=str) if extraction_audit else None
            # A merchant auto-ignore rule (or an explicit upstream flag) makes the
            # row arrive Ignored — the write-time parallel to category overrides.
            ignored = 1 if self._resolve_ignored(transaction_data) else 0
            conn.execute(
                """INSERT INTO transactions (
                    forwarded_to, date_file_name, transaction_hash, user_id,
                    institution, amount, company, transaction_type, category,
                    name, date, file_name,
                    from_name, from_email, to_name, to_email,
                    subject, body, ignored,
                    category_audit_reviewed_at, category_audit_source,
                    category_audit_matched_rule, category_audit_confidence,
                    category_audit_previous_category, category_audit_json,
                    extraction_audit_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    transaction_data["forwarded_to"],
                    date_file_name,
                    transaction_hash,
                    transaction_data.get("user_id"),
                    transaction_data.get("institution"),
                    amount,
                    transaction_data.get("company"),
                    transaction_data.get("transaction_type"),
                    cat,
                    transaction_data.get("name"),
                    transaction_data["date"],
                    transaction_data["file_name"],
                    transaction_data.get("from_name"),
                    (transaction_data["from_email"].lower() if transaction_data.get("from_email") else None),
                    transaction_data.get("to_name"),
                    (transaction_data["to_email"].lower() if transaction_data.get("to_email") else None),
                    transaction_data.get("subject"),
                    transaction_data.get("body"),
                    ignored,
                    reviewed_at,
                    source,
                    matched_rule,
                    confidence,
                    prev_cat,
                    audit_json,
                    extraction_json,
                ),
            )
            conn.commit()
            logger.info("Transaction added: %s", date_file_name)
            return date_file_name
        finally:
            conn.close()

    def find_date_file_name_by_hash(self, forwarded_to: str, transaction_hash: str) -> str | None:
        """Look up the date_file_name of a transaction with the given hash. None if absent."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT date_file_name FROM transactions WHERE forwarded_to = ? AND transaction_hash = ?",
                (forwarded_to, transaction_hash),
            ).fetchone()
            return row["date_file_name"] if row else None
        finally:
            conn.close()

    def get_hash_index(self, forwarded_to: str) -> dict[str, str]:
        """Return ``{transaction_hash: date_file_name}`` for one partition (lowest name wins)."""
        with self._session_conn() as conn:
            rows = conn.execute(
                """SELECT transaction_hash, date_file_name FROM transactions
                   WHERE forwarded_to = ? AND transaction_hash IS NOT NULL
                   ORDER BY date_file_name""",
                (forwarded_to,),
            ).fetchall()
        index: dict[str, str] = {}
        for row in rows:
            index.setdefault(row["transaction_hash"], row["date_file_name"])
        return index

    def _insert_imported(
        self,
        row: dict[str, Any],
        category_audit: dict[str, Any] | None,
        occurrence: int = 0,
    ) -> str | None:
        """Force-insert a transaction bypassing the dedup check.

        See the DynamoDB implementation's docstring for the contract. When
        ``occurrence > 0`` the stored transaction_hash is bumped to disable
        the hash-dedup index collision (supports the "keep both" strategy).
        """
        missing = self._validate_required_fields(row, ["forwarded_to", "file_name", "date"])
        if missing:
            logger.error("Imported row missing required field: %s", missing)
            return None

        base_hash = generate_transaction_hash(row)
        stored_hash = bump_hash_occurrence(base_hash, occurrence)

        date_obj = dateutil_parse(row["date"], tzinfos=get_tzinfos())
        formatted = date_obj.strftime("%Y.%m.%d_%H.%M")
        file_name_tail = row["file_name"].split("/")[-1]
        if occurrence > 0:
            # Ensure PK uniqueness for "keep both" — see counterpart in transaction_db.py.
            file_name_tail = f"{file_name_tail}.occ{occurrence}"
        date_file_name = f"{formatted}_{file_name_tail}"

        cat = self._normalize_category(row)
        amount = float(row["amount"]) if row.get("amount") is not None else None
        reviewed_at, source, matched_rule, confidence, prev_cat, audit_json = _split_audit(category_audit)

        with self._session_conn() as conn:
            conn.execute(
                """INSERT INTO transactions (
                    forwarded_to, date_file_name, transaction_hash, user_id,
                    institution, amount, company, transaction_type, category,
                    name, date, file_name,
                    from_name, from_email, to_name, to_email,
                    subject, body, comment, ignored, deleted_at,
                    category_audit_reviewed_at, category_audit_source,
                    category_audit_matched_rule, category_audit_confidence,
                    category_audit_previous_category, category_audit_json,
                    statement_source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["forwarded_to"],
                    date_file_name,
                    stored_hash,
                    row.get("user_id"),
                    row.get("institution"),
                    amount,
                    row.get("company"),
                    row.get("transaction_type"),
                    cat,
                    row.get("name"),
                    row["date"],
                    row["file_name"],
                    row.get("from_name"),
                    (row["from_email"].lower() if row.get("from_email") else None),
                    row.get("to_name"),
                    (row["to_email"].lower() if row.get("to_email") else None),
                    row.get("subject"),
                    row.get("body"),
                    row.get("comment"),
                    1 if row.get("ignored") else 0,
                    row.get("deleted_at"),
                    reviewed_at,
                    source,
                    matched_rule,
                    confidence,
                    prev_cat,
                    audit_json,
                    row.get("statement_source"),
                ),
            )
        return date_file_name

    def add_statement_transaction(
        self,
        txn_data: dict[str, Any],
        audit_source: str = "statement_import",
        *,
        known_hashes: dict[str, str] | None = None,
    ) -> str | bool | None:
        """Add a statement-imported transaction. Returns DateFileName if written, False if dup, None if invalid.

        With ``known_hashes`` (a preloaded ``get_hash_index`` map) the duplicate
        check reads the map instead of the table; the map gains the new row.
        """
        stmt_required = [
            "forwarded_to",
            "date",
            "amount",
            "company",
            "institution",
            "transaction_type",
            "category",
            "statement_source",
        ]
        missing = self._validate_required_fields(txn_data, stmt_required)
        if missing:
            logger.error("Missing required field: %s", missing)
            return None

        transaction_hash = self._compute_statement_hash(txn_data)

        conn = self._connect()
        try:
            if known_hashes is not None:
                is_duplicate = transaction_hash in known_hashes
            else:
                is_duplicate = (
                    conn.execute(
                        "SELECT 1 FROM transactions WHERE forwarded_to = ? AND transaction_hash = ?",
                        (txn_data["forwarded_to"], transaction_hash),
                    ).fetchone()
                    is not None
                )
            if is_duplicate:
                logger.info("Duplicate statement transaction (hash=%s). Skipping.", transaction_hash)
                return False

            date_file_name, synthetic_date = self._synthesize_statement_keys(txn_data, transaction_hash)

            category = self._normalize_category(txn_data)
            reviewed_at, source, _, _, _, audit_json = _split_audit(build_audit(audit_source))

            conn.execute(
                """INSERT INTO transactions (
                    forwarded_to, date_file_name, transaction_hash,
                    institution, amount, company, transaction_type, category,
                    name, user_id, date, statement_source,
                    category_audit_reviewed_at, category_audit_source, category_audit_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    txn_data["forwarded_to"],
                    date_file_name,
                    transaction_hash,
                    txn_data["institution"],
                    float(txn_data["amount"]),
                    txn_data["company"],
                    txn_data["transaction_type"],
                    category,
                    txn_data.get("name"),
                    txn_data.get("user_id"),
                    synthetic_date,
                    txn_data["statement_source"],
                    reviewed_at,
                    source,
                    audit_json,
                ),
            )
            conn.commit()
            if known_hashes is not None:
                known_hashes[transaction_hash] = date_file_name
            logger.info("Statement transaction added: %s", date_file_name)
            return date_file_name
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Update operations
    # ------------------------------------------------------------------

    def _audit_update_columns(self, audit: dict[str, Any]) -> tuple[list[str], list[Any]]:
        """SQL fragments + params that overwrite the five audit columns from a built audit dict."""
        reviewed_at, source, matched_rule, confidence, prev_cat, audit_json = _split_audit(audit)
        return (
            [
                "category_audit_reviewed_at = ?",
                "category_audit_source = ?",
                "category_audit_matched_rule = ?",
                "category_audit_confidence = ?",
                "category_audit_previous_category = ?",
                "category_audit_json = ?",
            ],
            [reviewed_at, source, matched_rule, confidence, prev_cat, audit_json],
        )

    def update_category(
        self, forwarded_to: str, date_file_name: str, new_category: str, source: str = "manual"
    ) -> str | None:
        """Update category and audit metadata. Returns old category or None."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT category, category_audit_source FROM transactions"
                " WHERE forwarded_to = ? AND date_file_name = ?",
                (forwarded_to, date_file_name),
            ).fetchone()
            old_category = row["category"] if row else None
            prev_source = row["category_audit_source"] if row else None

            audit = build_audit(source, previous_category=old_category, previous_source=prev_source)
            audit_cols, audit_params = self._audit_update_columns(audit)
            set_clause = ", ".join(["category = ?", *audit_cols])
            params = [new_category.lower(), *audit_params, forwarded_to, date_file_name]
            conn.execute(
                f"UPDATE transactions SET {set_clause} WHERE forwarded_to = ? AND date_file_name = ?",  # noqa: S608 — set_clause is fixed column fragments; values bound via ?
                params,
            )
            conn.commit()
            return old_category
        finally:
            conn.close()

    def mark_category_reviewed(self, forwarded_to: str, date_file_name: str, source: str = "audit") -> None:
        """Mark category as reviewed without changing it."""
        conn = self._connect()
        try:
            audit_cols, audit_params = self._audit_update_columns(build_audit(source))
            set_clause = ", ".join(audit_cols)
            params = [*audit_params, forwarded_to, date_file_name]
            conn.execute(
                f"UPDATE transactions SET {set_clause} WHERE forwarded_to = ? AND date_file_name = ?",  # noqa: S608 — set_clause is fixed column fragments; values bound via ?
                params,
            )
            conn.commit()
        finally:
            conn.close()

    def enrich_transaction(
        self,
        forwarded_to: str,
        date_file_name: str,
        new_company: str,
        new_category: str,
        source: str = "statement_enrich",
        statement_source: str | None = None,
    ) -> dict[str, Any] | None:
        """Enrich transaction from statement data. Returns old values dict or None.

        Company (and statement_source, when given) always update. The category
        is preserved — category and audit columns left untouched — when the
        existing row was manually categorized or when the incoming category is
        the ``miscellaneous`` fallback and the existing one is real (see
        ``_resolve_enrich_category``). Otherwise category and audit are
        rewritten. The returned dict carries ``category_preserved``.
        """
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT company, category, category_audit_source FROM transactions"
                " WHERE forwarded_to = ? AND date_file_name = ?",
                (forwarded_to, date_file_name),
            ).fetchone()
            if not row:
                return None

            old_company = row["company"]
            old_category = row["category"]
            preserve = self._resolve_enrich_category(
                old_category, row["category_audit_source"], new_category.lower(), source
            )

            if preserve:
                logger.info(
                    "enrich_transaction: preserving category %r (source=%r) over incoming %r (source=%r) for %s",
                    old_category,
                    row["category_audit_source"],
                    new_category.lower(),
                    source,
                    date_file_name,
                )
                parts = ["company = ?"]
                params: list[Any] = [new_company]
                if statement_source is not None:
                    parts.append("statement_source = ?")
                    params.append(statement_source)
                params.extend([forwarded_to, date_file_name])
                conn.execute(
                    f"UPDATE transactions SET {', '.join(parts)} WHERE forwarded_to = ? AND date_file_name = ?",  # noqa: S608 — set_clause is fixed column fragments; values bound via ?
                    params,
                )
                conn.commit()
                return {"old_company": old_company, "old_category": old_category, "category_preserved": True}

            audit = build_audit(
                source,
                previous_category=old_category,
                previous_source=row["category_audit_source"],
            )
            audit_cols, audit_params = self._audit_update_columns(audit)
            parts = ["company = ?", "category = ?", *audit_cols]
            params = [new_company, new_category.lower(), *audit_params]
            if statement_source is not None:
                parts.append("statement_source = ?")
                params.append(statement_source)
            params.extend([forwarded_to, date_file_name])

            conn.execute(
                f"UPDATE transactions SET {', '.join(parts)} WHERE forwarded_to = ? AND date_file_name = ?",  # noqa: S608 — set_clause is fixed column fragments; values bound via ?
                params,
            )
            conn.commit()
            return {"old_company": old_company, "old_category": old_category, "category_preserved": False}
        finally:
            conn.close()

    def update_fields(
        self,
        forwarded_to: str,
        date_file_name: str,
        fields: dict[str, Any],
        category: str | None = None,
    ) -> dict[str, Any] | None:
        """Update transaction fields dynamically. Returns old values dict."""
        if not fields:
            return None

        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT company, amount, transaction_type, category, category_audit_source"
                " FROM transactions WHERE forwarded_to = ? AND date_file_name = ?",
                (forwarded_to, date_file_name),
            ).fetchone()

            parts: list[str] = []
            params: list[Any] = []
            if "company" in fields:
                parts.append("company = ?")
                params.append(fields["company"])
            if "amount" in fields:
                parts.append("amount = ?")
                params.append(float(fields["amount"]))
            if "transaction_type" in fields:
                parts.append("transaction_type = ?")
                params.append(fields["transaction_type"])
            if category is not None:
                parts.append("category = ?")
                params.append(category.lower())

            if category is not None and row is not None:
                audit = build_audit(
                    "manual_edit",
                    previous_category=row["category"],
                    previous_source=row["category_audit_source"],
                )
            else:
                audit = build_audit("manual_edit")
            audit_cols, audit_params = self._audit_update_columns(audit)
            parts.extend(audit_cols)
            params.extend(audit_params)
            params.extend([forwarded_to, date_file_name])

            conn.execute(
                f"UPDATE transactions SET {', '.join(parts)} WHERE forwarded_to = ? AND date_file_name = ?",  # noqa: S608 — set_clause is fixed column fragments; values bound via ?
                params,
            )
            conn.commit()

            old_amount = float(row["amount"]) if row and row["amount"] is not None else None
            return {
                "old_company": row["company"] if row else None,
                "old_amount": old_amount,
                "old_transaction_type": row["transaction_type"] if row else None,
                "old_category": row["category"] if row else None,
            }
        finally:
            conn.close()

    def get_item(self, forwarded_to: str, date_file_name: str) -> "TransactionItem | None":
        """Fetch a single transaction by composite key."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM transactions WHERE forwarded_to = ? AND date_file_name = ?",
                (forwarded_to, date_file_name),
            ).fetchone()
            # sqlite boundary: row_to_item builds the stored PascalCase shape.
            return cast("TransactionItem", row_to_item(row)) if row else None
        finally:
            conn.close()

    def update_context(self, forwarded_to: str, date_file_name: str, context: dict[str, Any]) -> None:
        """Store enrichment context. Fails silently."""
        try:
            ctx_json = json.dumps(context, default=str)
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE transactions SET context_json = ? WHERE forwarded_to = ? AND date_file_name = ?",
                    (ctx_json, forwarded_to, date_file_name),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            logger.exception("Failed to update transaction context — continuing")

    def set_ignored(self, forwarded_to: str, date_file_name: str, ignored: bool) -> bool | None:
        """Set or clear the Ignored flag. Returns previous value."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT ignored FROM transactions WHERE forwarded_to = ? AND date_file_name = ?",
                (forwarded_to, date_file_name),
            ).fetchone()
            old_val = bool(row["ignored"]) if row else None

            conn.execute(
                "UPDATE transactions SET ignored = ? WHERE forwarded_to = ? AND date_file_name = ?",
                (1 if ignored else 0, forwarded_to, date_file_name),
            )
            conn.commit()
            return old_val
        finally:
            conn.close()

    def set_ignored_many(self, keys: Sequence[tuple[str, str]], ignored: bool) -> int:
        """Set or clear Ignored on many rows in one transaction. Returns the number of keys."""
        with self._session_conn() as conn:
            conn.executemany(
                "UPDATE transactions SET ignored = ? WHERE forwarded_to = ? AND date_file_name = ?",
                [(1 if ignored else 0, forwarded_to, date_file_name) for forwarded_to, date_file_name in keys],
            )
        return len(keys)

    def set_deleted(self, forwarded_to: str, date_file_name: str, deleted: bool) -> bool | str | None:
        """Set or clear DeletedAt. Returns previous value."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT deleted_at FROM transactions WHERE forwarded_to = ? AND date_file_name = ?",
                (forwarded_to, date_file_name),
            ).fetchone()
            old_val = row["deleted_at"] if row else None

            if deleted:
                now = datetime.now(UTC).isoformat()
                conn.execute(
                    "UPDATE transactions SET deleted_at = ? WHERE forwarded_to = ? AND date_file_name = ?",
                    (now, forwarded_to, date_file_name),
                )
            else:
                conn.execute(
                    "UPDATE transactions SET deleted_at = NULL WHERE forwarded_to = ? AND date_file_name = ?",
                    (forwarded_to, date_file_name),
                )
            conn.commit()
            return old_val
        finally:
            conn.close()

    def permanently_delete(self, forwarded_to: str, date_file_name: str) -> "TransactionItem | None":
        """Permanently delete a transaction. Returns the deleted item or None."""
        # Shares the bulk-import connection when called from an overwrite import.
        with self._session_conn() as conn:
            row = conn.execute(
                "SELECT * FROM transactions WHERE forwarded_to = ? AND date_file_name = ?",
                (forwarded_to, date_file_name),
            ).fetchone()
            if not row:
                return None
            # sqlite boundary: row_to_item builds the stored PascalCase shape.
            item = cast("TransactionItem", row_to_item(row))
            conn.execute(
                "DELETE FROM transactions WHERE forwarded_to = ? AND date_file_name = ?",
                (forwarded_to, date_file_name),
            )
        return item

    def set_comment(self, forwarded_to: str, date_file_name: str, comment: str | None) -> str | None:
        """Set or clear a comment. Returns previous value."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT comment FROM transactions WHERE forwarded_to = ? AND date_file_name = ?",
                (forwarded_to, date_file_name),
            ).fetchone()
            old_val = row["comment"] if row else None

            conn.execute(
                "UPDATE transactions SET comment = ? WHERE forwarded_to = ? AND date_file_name = ?",
                (comment or None, forwarded_to, date_file_name),
            )
            conn.commit()
            return old_val
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Query operations
    # ------------------------------------------------------------------

    def scan_by_category(self, category: str) -> "list[TransactionItem]":
        """Find all non-deleted transactions with the given category."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT forwarded_to, date_file_name FROM transactions WHERE category = ? AND deleted_at IS NULL",
                (category.lower(),),
            ).fetchall()
            return cast(
                "list[TransactionItem]",
                [{"ForwardedTo": r["forwarded_to"], "DateFileName": r["date_file_name"]} for r in rows],
            )
        finally:
            conn.close()

    def count_by_category(self, category: str) -> int:
        """Count non-deleted transactions with the given category."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM transactions WHERE category = ? AND deleted_at IS NULL",
                (category.lower(),),
            ).fetchone()
            return row["cnt"]
        finally:
            conn.close()

    def query_month_partition(self, forwarded_to: str, year_month: str) -> "list[TransactionItem]":
        """Return transactions for one user/month as PascalCase dicts.

        Uses GLOB prefix matching on date_file_name (e.g. '2026.04*') to mirror
        DynamoDB's begins_with condition on the DateFileName sort key. GLOB is
        case-sensitive, so SQLite bounds the (forwarded_to, date_file_name)
        index range by the month prefix too; a case-insensitive LIKE would only
        use the forwarded_to equality and scan the whole partition.
        """
        prefix = year_month.replace("-", ".")
        conn = self._connect()
        try:
            rows = conn.execute(_QUERY_MONTH_PARTITION_SQL, (forwarded_to, f"{prefix}*")).fetchall()
            # sqlite boundary: row_to_item builds the stored PascalCase shape.
            return cast("list[TransactionItem]", [row_to_item(row) for row in rows])
        finally:
            conn.close()

    def scan_all_transactions(self) -> "list[TransactionItem]":
        """Return every row as a PascalCase dict — used by the full-data backup."""
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM transactions ORDER BY date_file_name").fetchall()
            # sqlite boundary: row_to_item builds the stored PascalCase shape.
            return cast("list[TransactionItem]", [row_to_item(row) for row in rows])
        finally:
            conn.close()

    def get_latest_date_file_name(self, year_month: str | None = None) -> str | None:
        """Return the largest date_file_name, optionally filtered to a month."""
        conn = self._connect()
        try:
            if year_month:
                prefix = year_month.replace("-", ".")
                row = conn.execute(_LATEST_IN_MONTH_SQL, (f"{prefix}*",)).fetchone()
            else:
                row = conn.execute("SELECT MAX(date_file_name) AS latest FROM transactions").fetchone()
            return row["latest"] if row and row["latest"] else None
        finally:
            conn.close()

    def get_recent_audits(self, limit: int = 25) -> list[dict[str, Any]]:
        """Return the most recent rows' category provenance, newest-first.

        Mirrors the DynamoDB backend: bounded, excludes soft-deleted rows, and
        reuses row_to_item() so the reconstructed CategoryAudit (including
        fallback_reason from category_audit_json) matches the canonical shape.
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT category, category_audit_reviewed_at, category_audit_source,
                          category_audit_matched_rule, category_audit_confidence,
                          category_audit_previous_category, category_audit_json
                   FROM transactions
                   WHERE deleted_at IS NULL
                   ORDER BY date_file_name DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
            return [row_to_item(row) for row in rows]
        finally:
            conn.close()

    # batch_update_category is inherited from TransactionsDBBase
