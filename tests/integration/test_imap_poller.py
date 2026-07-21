"""End-to-end IMAP → SQLite round-trip integration test.

Exercises the self-hosted ingestion path against a real inbox: fetches one
message via ``BODY.PEEK`` (never marking it read), runs it through the full
pipeline (``parse_email`` → store → ``TransactionContext`` enrich) into an
isolated temporary SQLite database, and verifies the stored row.

Because the fetched message is whatever the live inbox happens to hold, the test
only asserts on the success path: if the message is not a recognized bank
transaction (``invalid`` / ``error`` / ``quarantined`` / ``skipped``) or is a
``duplicate``, the test SKIPS rather than fails. When a transaction *is* stored,
the row is verified and then deleted in a ``finally`` block, so cleanup runs even
when an assertion fails. The temporary database is discarded by pytest either
way, so the real ``data/finance.db`` is never touched.

Required environment (test SKIPS cleanly if either is missing):
    IMAP_USER            mailbox login
    IMAP_PASSWORD        mailbox password / app password (spaces are stripped)

Optional environment (with defaults):
    IMAP_SERVER          IMAP host      (default: imap.gmail.com)
    IMAP_PORT            IMAP port      (default: 993)
    IMAP_FOLDER          mailbox folder (default: INBOX)
    IMAP_SEARCH          search criteria(default: UNSEEN; e.g. ALL)

Example invocation (against a real, disposable inbox):
    IMAP_USER=me@example.com IMAP_PASSWORD='app password' \\
        uv run pytest tests/integration/test_imap_poller.py -m integration
"""

import json
import logging
import os

import pytest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Env gating — read (never connect) at import time so collection with no env
# skips cleanly instead of erroring.
# ---------------------------------------------------------------------------
IMAP_USER = os.environ.get("IMAP_USER")
IMAP_PASSWORD = os.environ.get("IMAP_PASSWORD")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (IMAP_USER and IMAP_PASSWORD),
        reason="IMAP_USER and IMAP_PASSWORD must be set for the IMAP poller e2e test",
    ),
]


def _fetch_one_email(server: str, port: int, user: str, password: str, folder: str, criterion: str):
    """Connect over IMAP, fetch one message via BODY.PEEK, return (uid, raw_bytes).

    Returns ``None`` when the folder holds no matching messages — the caller
    turns that into a skip rather than a failure.
    """
    import imaplib

    password = password.replace(" ", "")
    logger.info("Connecting to %s:%s as %s", server, port, user)
    mail = imaplib.IMAP4_SSL(server, port)
    mail.login(user, password)
    try:
        status, _ = mail.select(folder, readonly=True)
        if status != "OK":
            pytest.skip(f"could not select IMAP folder {folder!r}")

        _, data = mail.search(None, criterion)
        uids = data[0].split() if data[0] else []
        if not uids:
            return None

        uid = uids[-1]  # most recent match
        uid_str = uid.decode()
        logger.info("Fetching uid=%s (most recent of %d)", uid_str, len(uids))
        _, msg_data = mail.fetch(uid, "(BODY.PEEK[])")  # PEEK — do not mark read
        if not msg_data or not msg_data[0]:
            pytest.skip(f"empty IMAP response for uid={uid_str}")
        return uid_str, msg_data[0][1]
    finally:
        mail.logout()
        logger.info("IMAP connection closed")


def test_imap_pipeline_stores_transaction(tmp_path) -> None:
    """Fetch one email, run parse → store → enrich, verify the SQLite write."""
    from src.finance.email_pipeline import parse_email
    from src.finance.imap_poller import process_message
    from src.finance.local_db import ensure_schema, get_connection
    from src.finance.transaction_context import TransactionContextEnricher
    from src.finance.transaction_db_local import TransactionsDBLocal

    server = os.environ.get("IMAP_SERVER", "imap.gmail.com")
    port = int(os.environ.get("IMAP_PORT", "993"))
    folder = os.environ.get("IMAP_FOLDER", "INBOX")
    criterion = os.environ.get("IMAP_SEARCH", "UNSEEN")

    fetched = _fetch_one_email(server, port, IMAP_USER, IMAP_PASSWORD, folder, criterion)
    if fetched is None:
        pytest.skip(f"no messages matched {criterion!r} in {folder!r} — nothing to test")
    uid_str, raw_bytes = fetched

    # Isolated DB — the real data/finance.db is never touched.
    db_path = tmp_path / "imap_e2e.db"
    ensure_schema(db_path)
    transactions_db = TransactionsDBLocal(db_path=db_path)
    # No budget service and no AI client: budget context is absent and the
    # category falls back to Miscellaneous — we only assert the storage path.
    enricher = TransactionContextEnricher(transactions_db, budget_service=None)

    status = process_message(raw_bytes, uid_str, transactions_db, enricher, api_client=None)
    logger.info("process_message returned %r for uid=%s", status, uid_str)

    if status != "new":
        # The live inbox's most recent message wasn't a fresh bank transaction
        # (non-bank mail, already-parsed duplicate, quarantined, etc.). Surface
        # what was parsed for diagnostics, then skip — this is environmental,
        # not a defect.
        parsed = parse_email(raw_bytes, f"imap/test/uid-{uid_str}.eml", api_client=None)
        pytest.skip(
            f"process_message status={status!r} (from={parsed.get('from_email', '?')}, "
            f"subject={parsed.get('subject', '?')}, institution={parsed.get('institution', 'n/a')}) "
            "— not a new bank transaction"
        )

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM transactions WHERE file_name LIKE ?",
            (f"%uid-{uid_str}.eml",),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None, "process_message returned 'new' but no row was stored"

    try:
        # --- Verify the stored transaction ---
        assert row["institution"], "stored transaction has no institution"
        assert row["company"], "stored transaction has no company"
        assert row["amount"] is not None, "stored transaction has no amount"
        assert row["date_file_name"], "stored transaction has no date_file_name"
        if row["context_json"]:
            # Enrichment ran — must be valid JSON.
            json.loads(row["context_json"])
    finally:
        # --- Cleanup: remove the test transaction (runs even on failure) ---
        deleted = transactions_db.permanently_delete(row["forwarded_to"], row["date_file_name"])
        if deleted:
            logger.info("Cleaned up test transaction %s", row["date_file_name"])
        else:
            logger.warning("Cleanup found no transaction to delete for %s", row["date_file_name"])
