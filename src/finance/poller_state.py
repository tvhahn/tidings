"""Poller state + heartbeat persistence for the IMAP poller.

Owns the ``config_store`` reads/writes that track the poller's progress
(last-seen UID + UIDVALIDITY) and liveness (heartbeat), plus the health
endpoint's freshness probe (``get_imap_last_poll``). Split out of
``imap_poller`` so the persistence layer is independent of the IMAP client
and CLI daemon. Sync + SQLite-only, via ``local_db.get_connection``.
"""

import imaplib
import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from src.finance.local_db import DEFAULT_DB_PATH, get_connection

logger = logging.getLogger(__name__)

_UID_STORE_PK = "SYSTEM#imap_poller"
_UID_STORE_SK = "last_seen_uid"
_HEARTBEAT_SK = "last_poll_at"


def load_poller_state(db_path: Path = DEFAULT_DB_PATH) -> tuple[int, int | None]:
    """Return (last_seen_uid, last_seen_uidvalidity). Missing keys default to 0/None."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT data_json FROM config_store WHERE pk = ? AND sk = ?",
            (_UID_STORE_PK, _UID_STORE_SK),
        ).fetchone()
        if row:
            data = json.loads(row["data_json"])
            return data.get("uid", 0), data.get("uidvalidity")
        return 0, None
    finally:
        conn.close()


def save_poller_state(
    db_path: Path = DEFAULT_DB_PATH,
    uid: int = 0,
    uidvalidity: int | None = None,
) -> None:
    conn = get_connection(db_path)
    try:
        now = datetime.now(UTC).isoformat()
        payload: dict[str, int] = {"uid": uid}
        if uidvalidity is not None:
            payload["uidvalidity"] = uidvalidity
        conn.execute(
            "INSERT OR REPLACE INTO config_store (pk, sk, data_json, version, updated_at) VALUES (?, ?, ?, 1, ?)",
            (_UID_STORE_PK, _UID_STORE_SK, json.dumps(payload), now),
        )
        conn.commit()
    finally:
        conn.close()


def save_heartbeat(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Record a successful IMAP poll tick.

    Writes a row to ``config_store`` keyed by ``SYSTEM#imap_poller / last_poll_at``.
    The health endpoint reads ``updated_at`` to derive the poller's freshness —
    without this heartbeat, an idle but healthy poller would silently look stale
    (``save_poller_state`` only runs when a *new* message arrives or
    UIDVALIDITY changes).
    """
    conn = get_connection(db_path)
    try:
        now = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO config_store (pk, sk, data_json, version, updated_at) VALUES (?, ?, ?, 1, ?)",
            (_UID_STORE_PK, _HEARTBEAT_SK, json.dumps({"ts": now}), now),
        )
        conn.commit()
    finally:
        conn.close()


def get_uidvalidity(mail: imaplib.IMAP4) -> int | None:
    """Read UIDVALIDITY from the server's cached untagged response (populated by SELECT)."""
    try:
        _, data = mail.response("UIDVALIDITY")
        if data and data[0]:
            return int(data[0])
    except Exception:
        logger.debug("could not parse UIDVALIDITY response", exc_info=True)
    return None


def get_imap_last_poll(db_path: Path | None = None) -> str | None:
    """Return the ISO-8601 UTC timestamp of the last successful poll, or ``None``.

    Preference order:
    1. Heartbeat row (``last_poll_at``) — updated every successful tick.
    2. Legacy: ``last_seen_uid.updated_at`` — the old behaviour, kept as a
       fallback so the endpoint reports *something* on installs that predate
       the heartbeat. Returns ``None`` if neither row exists.

    Returns ``None`` (rather than raising) on a fresh database where
    ``config_store`` has not yet been created — ``/api/v1/health`` calls this
    on first boot before any write has triggered ``ensure_schema()``.

    ``db_path`` defaults to the module-level ``DEFAULT_DB_PATH`` read at call
    time (not import time) so tests can monkeypatch it.
    """
    path = db_path if db_path is not None else DEFAULT_DB_PATH
    try:
        conn = get_connection(path)
    except Exception:
        return None
    try:
        row = conn.execute(
            "SELECT updated_at FROM config_store WHERE pk = ? AND sk = ?",
            (_UID_STORE_PK, _HEARTBEAT_SK),
        ).fetchone()
        if row and row["updated_at"]:
            return row["updated_at"]
        row = conn.execute(
            "SELECT updated_at FROM config_store WHERE pk = ? AND sk = ?",
            (_UID_STORE_PK, _UID_STORE_SK),
        ).fetchone()
        if row and row["updated_at"]:
            return row["updated_at"]
        return None
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
