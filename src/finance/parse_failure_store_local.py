"""SQLite implementation of the parse-failure (dead-letter) store.

Mirrors the DynamoDB :class:`~src.finance.parse_failure_store.ParseFailureStore`
public API. Failed bank-email parses are persisted here with the full
``email_details`` dict so they can be retried later via
``parse_email_body(body, email_details, api_client)``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from src.finance.category_audit import now_local_iso
from src.finance.local_db import DEFAULT_DB_PATH, ensure_schema, get_connection
from src.finance.parse_failure_store_base import ParseFailureStoreBase

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

logger = logging.getLogger(__name__)

# Valid status lifecycle values.
VALID_STATUSES = ("quarantined", "recovered", "retried", "dismissed")

# Failure stages — where in the pipeline the parse gave up.
VALID_STAGES = (
    "no_parser_match",
    "extraction_empty",
    "ai_extraction_failed",
    "ai_validation_failed",
    "db_validation_failed",
)

# Statuses that are eligible for the opportunistic 90-day prune-on-write.
_PRUNABLE_STATUSES = ("dismissed", "recovered", "retried")

# Columns returned in summary listings — deliberately excludes ``email_json``
# (the full body blob) which is large and only needed for retry/detail.
_SUMMARY_COLUMNS = (
    "id",
    "received_at",
    "from_email",
    "subject",
    "file_name",
    "detected_institution",
    "failure_stage",
    "status",
    "recovered_date_file_name",
    "alert_classifier_result",
    "created_at",
    "updated_at",
)


def failure_id_for(email_details: dict[str, Any]) -> str:
    """Deterministic failure id derived from email content.

    ``"pf_" + sha256(forwarded_to | from_email | subject | date | body)[:16]``.
    Mirrors :func:`src.finance.statement_store.row_id_for`. Stable across Lambda
    redeliveries so re-recording the same email upserts rather than duplicating.
    """
    parts = [
        str(email_details.get("forwarded_to") or ""),
        str(email_details.get("from_email") or ""),
        str(email_details.get("subject") or ""),
        str(email_details.get("date") or ""),
        str(email_details.get("body") or ""),
    ]
    key = "|".join(parts)
    return "pf_" + hashlib.sha256(key.encode()).hexdigest()[:16]


def _row_to_summary(row: sqlite3.Row) -> dict[str, Any]:
    """Map a SQLite row to a summary dict (no ``email_json``)."""
    summary: dict[str, Any] = {col: row[col] for col in _SUMMARY_COLUMNS}
    raw = summary.get("alert_classifier_result")
    summary["alert_classifier_result"] = ParseFailureStoreBase.coerce_classifier(raw)
    return summary


def _row_to_full(row: sqlite3.Row) -> dict[str, Any]:
    """Map a SQLite row to a full dict (includes ``email_json``)."""
    full = _row_to_summary(row)
    full["email_json"] = row["email_json"]
    return full


class ParseFailureStoreLocal(ParseFailureStoreBase):
    """SQLite-backed dead-letter store for unparseable bank emails."""

    def __init__(self, db_path: Path | None = None, user_id: str = "default") -> None:
        self._db_path = db_path or DEFAULT_DB_PATH
        self._user_id = user_id
        ensure_schema(self._db_path)

    def _connect(self) -> sqlite3.Connection:
        return get_connection(self._db_path)

    def record_failure(self, failure: dict[str, Any]) -> str:
        """Persist (idempotently) a parse failure and return its deterministic id.

        The id is derived from the email's content, so recording the same email
        twice (e.g. a Lambda redelivery) upserts the same row rather than
        creating a duplicate. After the write, opportunistically prunes
        dismissed/recovered/retried rows older than 90 days.
        """
        email_details = failure.get("email_details") or {}
        failure_id = failure.get("id") or failure_id_for(email_details)
        now = now_local_iso()
        received_at = failure.get("received_at") or now
        classifier = failure.get("alert_classifier_result")
        classifier_int = None if classifier is None else int(bool(classifier))
        email_json = failure.get("email_json")
        if email_json is None:
            email_json = json.dumps(email_details)

        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO parse_failures (
                    id, user_id, received_at, from_email, subject, file_name,
                    detected_institution, failure_stage, status,
                    recovered_date_file_name, alert_classifier_result,
                    email_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    failure_stage = excluded.failure_stage
                """,
                (
                    failure_id,
                    self._user_id,
                    received_at,
                    failure.get("from_email") or email_details.get("from_email"),
                    failure.get("subject") or email_details.get("subject"),
                    failure.get("file_name") or email_details.get("file_name"),
                    failure.get("detected_institution"),
                    failure.get("failure_stage", "no_parser_match"),
                    failure.get("status", "quarantined"),
                    failure.get("recovered_date_file_name"),
                    classifier_int,
                    email_json,
                    received_at,
                    now,
                ),
            )
            self._prune(conn, now)
            conn.commit()
        finally:
            conn.close()
        return failure_id

    def _prune(self, conn: sqlite3.Connection, now_iso: str) -> None:
        """Delete terminal-status rows older than 90 days (opportunistic)."""
        from datetime import datetime

        try:
            cutoff = (datetime.fromisoformat(now_iso) - timedelta(days=90)).isoformat()
        except ValueError:
            return
        placeholders = ",".join("?" for _ in _PRUNABLE_STATUSES)
        conn.execute(
            f"DELETE FROM parse_failures WHERE status IN ({placeholders}) AND received_at < ?",  # noqa: S608 — placeholder count derived from constant tuple; values bound via ?
            (*_PRUNABLE_STATUSES, cutoff),
        )

    def get_failure(self, failure_id: str) -> dict[str, Any] | None:
        """Return the full failure row (including ``email_json``) or None."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM parse_failures WHERE id = ? AND user_id = ?",
                (failure_id, self._user_id),
            ).fetchone()
            return _row_to_full(row) if row else None
        finally:
            conn.close()

    def list_failures(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """List failure summaries (no ``email_json``), newest first.

        Optionally filtered by ``status``. Ordered ``received_at DESC``.
        """
        conn = self._connect()
        try:
            params: list[Any] = [self._user_id]
            sql = "SELECT * FROM parse_failures WHERE user_id = ?"
            if status is not None:
                sql += " AND status = ?"
                params.append(status)
            sql += " ORDER BY received_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [_row_to_summary(r) for r in rows]
        finally:
            conn.close()

    def list_failures_full(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """List full failure rows (including ``email_json``), newest first.

        Same server-side ``WHERE``/``ORDER BY``/``LIMIT`` as :meth:`list_failures`
        but keeps ``email_json`` — the bulk-retry sweep needs each body to re-run
        the parsers, so this lets it filter and retry in one pass rather than
        re-querying every matched row via :meth:`get_failure`.
        """
        conn = self._connect()
        try:
            params: list[Any] = [self._user_id]
            sql = "SELECT * FROM parse_failures WHERE user_id = ?"
            if status is not None:
                sql += " AND status = ?"
                params.append(status)
            sql += " ORDER BY received_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [_row_to_full(r) for r in rows]
        finally:
            conn.close()

    def set_status(self, failure_id: str, status: str, recovered_date_file_name: str | None = None) -> bool:
        """Transition a failure to ``status``. Returns True if a row was updated.

        ``recovered_date_file_name`` is written only when non-None. Passing None
        (a dismiss, or a duplicate retry/resolve where no new row was created)
        leaves any existing ``recovered_date_file_name`` intact rather than
        clearing the link to the transaction that already recovered this failure.
        """
        now = now_local_iso()
        conn = self._connect()
        try:
            if recovered_date_file_name is not None:
                cursor = conn.execute(
                    """
                    UPDATE parse_failures
                    SET status = ?, recovered_date_file_name = ?, updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (status, recovered_date_file_name, now, failure_id, self._user_id),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE parse_failures
                    SET status = ?, updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (status, now, failure_id, self._user_id),
                )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def count_recent_quarantined(self, days: int = 7) -> int:
        """Count rows still in ``quarantined`` status within the last ``days``."""
        from datetime import datetime

        cutoff = (datetime.fromisoformat(now_local_iso()) - timedelta(days=days)).isoformat()
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT COUNT(*) FROM parse_failures
                WHERE user_id = ? AND status = 'quarantined' AND received_at > ?
                """,
                (self._user_id, cutoff),
            ).fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()

    def latest_received_by_institution(self) -> dict[str, str]:
        """Map each detected institution to its most recent ``received_at``.

        Groups over every row with a non-null ``detected_institution`` (any
        status) and takes ``MAX(received_at)`` per institution.
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT detected_institution AS institution, MAX(received_at) AS latest
                FROM parse_failures
                WHERE user_id = ? AND detected_institution IS NOT NULL
                GROUP BY detected_institution
                """,
                (self._user_id,),
            ).fetchall()
            return {row["institution"]: row["latest"] for row in rows if row["latest"] is not None}
        finally:
            conn.close()

    def has_other_recent_failure(self, institution: str, hours: int = 24) -> bool:
        """Whether another quarantined failure for ``institution`` exists in the window.

        Contract: this is called *after* the current failure has already been
        written, so the just-recorded row is in the table. We therefore use
        ``count > 1`` semantics within the window — ``True`` means at least one
        *other* (prior) quarantined failure for the same institution exists in
        the last ``hours`` hours, which is the drift-notification throttle gate.
        """
        from datetime import datetime

        cutoff = (datetime.fromisoformat(now_local_iso()) - timedelta(hours=hours)).isoformat()
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT COUNT(*) FROM parse_failures
                WHERE user_id = ?
                  AND detected_institution = ?
                  AND status = 'quarantined'
                  AND received_at > ?
                """,
                (self._user_id, institution, cutoff),
            ).fetchone()
            return (int(row[0]) if row else 0) > 1
        finally:
            conn.close()
