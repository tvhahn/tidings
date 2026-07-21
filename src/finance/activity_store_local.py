"""SQLite implementation of the agent-activity ledger.

Mirrors the DynamoDB :class:`~src.finance.activity_store.ActivityStore` public
API. Append-only: ``record`` inserts, ``mark_reverted`` stamps the revert
marker, and reads never mutate. Prune-on-write drops entries older than
``RETENTION_DAYS`` so the SQLite backend expires ledger history on the same
horizon as the DynamoDB TTL.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from src.finance.local_db import DEFAULT_DB_PATH, ensure_schema, get_connection

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

# Retention horizon — prune-on-write deletes entries older than this. Kept
# identical to the DynamoDB TTL window so the two backends agree on how long a
# revert stays possible.
RETENTION_DAYS = 90

# Ledger columns returned to callers, in declaration order.
_ENTRY_COLUMNS = (
    "id",
    "ts",
    "principal_kind",
    "principal_id",
    "principal_label",
    "operation_id",
    "method",
    "path",
    "resource_id",
    "summary",
    "before_json",
    "after_json",
    "reversible",
    "reverted_at",
    "reverted_by",
)


def _utc_now_iso() -> str:
    """Timezone-aware UTC ISO-8601 timestamp."""
    return datetime.now(UTC).isoformat()


def _row_to_entry(row: sqlite3.Row) -> dict[str, Any]:
    """Map a SQLite row to a normalized entry dict (``reversible`` → bool)."""
    entry: dict[str, Any] = {col: row[col] for col in _ENTRY_COLUMNS}
    entry["reversible"] = bool(entry["reversible"])
    return entry


class ActivityStoreLocal:
    """SQLite-backed append-only agent-activity ledger."""

    def __init__(self, db_path: Path | None = None, user_id: str = "default") -> None:
        self._db_path = db_path or DEFAULT_DB_PATH
        self._user_id = user_id
        ensure_schema(self._db_path)

    def _connect(self) -> sqlite3.Connection:
        return get_connection(self._db_path)

    def record(self, entry: dict[str, Any]) -> str:
        """Append a ledger entry and return its id.

        ``id`` defaults to a fresh ``uuid4().hex``; ``ts`` defaults to the
        current timezone-aware UTC time. After the write, opportunistically
        prunes entries older than ``RETENTION_DAYS``.
        """
        entry_id = entry.get("id") or uuid.uuid4().hex
        ts = entry.get("ts") or _utc_now_iso()
        now = _utc_now_iso()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO activity (
                    id, user_id, ts, principal_kind, principal_id, principal_label,
                    operation_id, method, path, resource_id, summary,
                    before_json, after_json, reversible, reverted_at, reverted_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    self._user_id,
                    ts,
                    entry.get("principal_kind"),
                    entry.get("principal_id"),
                    entry.get("principal_label"),
                    entry.get("operation_id"),
                    entry.get("method"),
                    entry.get("path"),
                    entry.get("resource_id"),
                    entry.get("summary"),
                    entry.get("before_json"),
                    entry.get("after_json"),
                    int(bool(entry.get("reversible", False))),
                    entry.get("reverted_at"),
                    entry.get("reverted_by"),
                ),
            )
            self._prune(conn, now)
            conn.commit()
        finally:
            conn.close()
        return entry_id

    def _prune(self, conn: sqlite3.Connection, now_iso: str) -> None:
        """Delete ledger entries older than ``RETENTION_DAYS`` (opportunistic)."""
        try:
            cutoff = (datetime.fromisoformat(now_iso) - timedelta(days=RETENTION_DAYS)).isoformat()
        except ValueError:
            return
        conn.execute("DELETE FROM activity WHERE ts < ?", (cutoff,))

    def list_entries(
        self,
        principal: str | None = None,
        since: str | None = None,
        operation: str | None = None,
        limit: int = 100,
        principal_kind: str | None = None,
    ) -> list[dict[str, Any]]:
        """List ledger entries newest-first, filtered then limited.

        ``principal`` exact-matches ``principal_id``; ``principal_kind``
        exact-matches ``principal_kind`` (filtered in SQL, before the limit, so a
        non-token caller's own feed is never crowded out by token entries);
        ``since`` is an inclusive ISO-8601 lower bound on ``ts``; ``operation``
        exact-matches ``operation_id``; ``limit`` is applied after filtering.
        """
        conn = self._connect()
        try:
            params: list[Any] = [self._user_id]
            sql = "SELECT * FROM activity WHERE user_id = ?"
            if principal is not None:
                sql += " AND principal_id = ?"
                params.append(principal)
            if principal_kind is not None:
                sql += " AND principal_kind = ?"
                params.append(principal_kind)
            if since is not None:
                sql += " AND ts >= ?"
                params.append(since)
            if operation is not None:
                sql += " AND operation_id = ?"
                params.append(operation)
            sql += " ORDER BY ts DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [_row_to_entry(r) for r in rows]
        finally:
            conn.close()

    def get_entry(self, entry_id: str) -> dict[str, Any] | None:
        """Return a single ledger entry by id, or None."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM activity WHERE id = ? AND user_id = ?",
                (entry_id, self._user_id),
            ).fetchone()
            return _row_to_entry(row) if row else None
        finally:
            conn.close()

    def mark_reverted(self, entry_id: str, reverted_by_entry_id: str, ts: str | None = None) -> None:
        """Stamp ``reverted_at``/``reverted_by`` on an entry (the only mutation).

        ``ts`` is accepted for signature parity with the DynamoDB backend (which
        uses it to reconstruct the item's sort key without a scan) but ignored
        here — the SQLite row is addressed directly by its primary-key ``id``.
        """
        now = _utc_now_iso()
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE activity SET reverted_at = ?, reverted_by = ? WHERE id = ? AND user_id = ?",
                (now, reverted_by_entry_id, entry_id, self._user_id),
            )
            conn.commit()
        finally:
            conn.close()
