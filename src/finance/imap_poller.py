"""IMAP polling daemon for self-hosted email ingestion.

Connects to an IMAP inbox, fetches bank transaction emails, and runs them
through the same parse_email() pipeline used by the AWS Lambda handler.
Designed to run as a long-lived Docker service alongside the finance dashboard.

Usage:
    IMAP_USER=you@gmail.com IMAP_PASSWORD="xxxx xxxx" \
    uv run python -m src.finance.imap_poller
"""

import contextlib
import imaplib
import logging
import os
import signal
import sys
import threading
from pathlib import Path
from types import FrameType

from src.finance.ai_client import AIProviderClient
from src.finance.email_pipeline import process_message
from src.finance.local_db import DEFAULT_DB_PATH, ensure_schema
from src.finance.poller_state import (
    get_imap_last_poll,
    get_uidvalidity,
    load_poller_state,
    save_heartbeat,
    save_poller_state,
)
from src.finance.protocols import IParseFailureStore, ITransactionsDB
from src.finance.storage import (
    create_parse_failure_store,
    create_transaction_context_enricher,
    create_transactions_db,
)
from src.finance.transaction_context import TransactionContextEnricher

# Re-exported for backward compatibility. ``src/api/routers/health.py`` and the
# `python -m src.finance.imap_poller` sidecar both import from this module, and
# a large body of tests patch these names here — persistence lives in
# ``poller_state`` and the per-message pipeline in ``email_pipeline`` now, but
# they remain reachable (and patchable) through this module's namespace.
__all__ = [
    "DEFAULT_DB_PATH",
    "ImapPoller",
    "get_imap_last_poll",
    "get_uidvalidity",
    "load_poller_state",
    "main",
    "process_message",
    "save_heartbeat",
    "save_poller_state",
]

logger = logging.getLogger(__name__)

_POLL_INTERVAL_DEFAULT = 60
_BACKOFF_INITIAL = 5
_BACKOFF_MAX = 300
_SOCKET_TIMEOUT = 30


def _mask_user(user: str) -> str:
    """Mask an IMAP username for log output.

    Self-hosters paste poller logs into bug reports; the full account
    address must never appear in them.
    """
    local, _, domain = user.partition("@")
    masked = (local[0] + "***") if local else "***"
    return f"{masked}@{domain}" if domain else masked


# ---------------------------------------------------------------------------
# IMAP Poller
# ---------------------------------------------------------------------------


class ImapPoller:
    """Polls an IMAP inbox for bank transaction emails."""

    def __init__(
        self,
        server: str,
        port: int,
        user: str,
        password: str,
        folder: str = "INBOX",
        poll_interval: int = _POLL_INTERVAL_DEFAULT,
        *,
        transactions_db: ITransactionsDB,
        context_enricher: TransactionContextEnricher,
        api_client: AIProviderClient | None = None,
        parse_failure_store: IParseFailureStore | None = None,
        db_path: Path = DEFAULT_DB_PATH,
    ):
        self._server = server
        self._port = port
        self._user = user
        self._password = password
        self._folder = folder
        self.poll_interval = poll_interval
        self._transactions_db = transactions_db
        self._context_enricher = context_enricher
        self._api_client = api_client
        self._parse_failure_store = parse_failure_store
        self._db_path = db_path
        self._mail = None

    def connect(self):
        """Connect to the IMAP server, or verify the existing connection is alive via NOOP."""
        if self._mail is not None:
            try:
                self._mail.noop()
                return
            except Exception as exc:
                logger.warning("IMAP connection stale (%s), reconnecting", exc)
                self._mail = None
        password = self._password.replace(" ", "")  # Google App Passwords have spaces
        self._mail = imaplib.IMAP4_SSL(self._server, self._port, timeout=_SOCKET_TIMEOUT)
        self._mail.login(self._user, password)
        self._mail.select(self._folder)
        logger.info("Connected to %s:%s as %s", self._server, self._port, _mask_user(self._user))

    def disconnect(self):
        """Disconnect from the IMAP server. Swallows errors."""
        if self._mail is not None:
            with contextlib.suppress(Exception):
                self._mail.logout()
            self._mail = None

    def poll_once(self) -> int:
        """Fetch and process new emails. Returns count of messages processed.

        Always records a heartbeat (``last_poll_at``) on successful completion,
        even when zero messages are fetched — otherwise a healthy idle poller
        would look stale to the /health endpoint.
        """
        if self._mail is None:
            raise RuntimeError("ImapPoller not connected; call connect() first")

        last_uid, last_validity = load_poller_state(self._db_path)
        current_validity = get_uidvalidity(self._mail)

        validity_changed = (
            current_validity is not None and last_validity is not None and current_validity != last_validity
        )
        if validity_changed:
            logger.warning(
                "UIDVALIDITY changed (%s -> %s), resetting last_seen_uid from %d to 0",
                last_validity,
                current_validity,
                last_uid,
            )
            last_uid = 0

        if last_uid > 0:
            search_query = f"UID {last_uid + 1}:*"
        else:
            search_query = "UNSEEN"
        _, data = self._mail.search(None, search_query)

        uids = data[0].split() if data[0] else []
        # Filter out UIDs we've already seen — IMAP `UID N:*` returns the highest
        # existing UID when no message has UID >= N (RFC quirk), so equal-to-last
        # is the no-news case. Strictly-less means stale state worth warning about.
        new_uids: list[bytes] = []
        for uid in uids:
            uid_int = int(uid.decode())
            if uid_int == last_uid:
                continue
            if uid_int < last_uid:
                logger.warning(
                    "poll: search returned uid=%d < last_seen_uid=%d — possible UIDVALIDITY change or stale state",
                    uid_int,
                    last_uid,
                )
                continue
            new_uids.append(uid)

        if not new_uids:
            logger.info("poll: no new UIDs (search %s, last_uid=%d)", search_query, last_uid)
            if validity_changed or (current_validity is not None and last_validity is None):
                save_poller_state(self._db_path, last_uid, current_validity)
            save_heartbeat(self._db_path)
            return 0

        highest_uid = last_uid
        processed = 0

        for uid in new_uids:
            uid_str = uid.decode()
            uid_int = int(uid_str)

            logger.info("Fetching uid=%s", uid_str)
            _, msg_data = self._mail.fetch(uid_str, "(BODY[])")

            # imaplib's FETCH response is a list of mixed tuples and bare bytes
            # (e.g. `[(b'19 (BODY[] {n}', b'<raw>'), b')']`). For some Gmail
            # responses `msg_data[0]` is a bare bytes object, so `msg_data[0][1]`
            # silently returns an int and crashes BytesParser downstream. Scan
            # for the first tuple part whose payload is bytes.
            raw_bytes: bytes | None = None
            for part in msg_data or []:
                if isinstance(part, tuple) and len(part) >= 2:
                    raw_bytes = bytes(part[1])
                    break
            if not raw_bytes:
                # Stop the batch here: if we kept going and a later UID
                # succeeded, the bookmark would advance past this one and it
                # would never be retried (the next search starts at
                # last_seen_uid + 1).
                logger.warning("Empty or malformed fetch response for uid=%s — stopping batch for retry", uid_str)
                break

            outcome = process_message(
                raw_bytes,
                uid_str,
                self._transactions_db,
                self._context_enricher,
                self._api_client,
                self._parse_failure_store,
            )

            # A transient error (parser crash, network hiccup) must leave the
            # bookmark untouched so the next poll can retry. Only outcomes where
            # we made a deliberate decision — new/duplicate/invalid/skipped/
            # quarantined — advance last_seen_uid and mark the message SEEN.
            # `quarantined` counts as captured: the email is safe in the
            # dead-letter store, so do NOT leave it unseen. `break`, not
            # `continue`: processing later UIDs in this batch would advance the
            # bookmark past the failed one and orphan it forever. Later
            # messages stay unfetched and are picked up on the next poll once
            # the failed UID succeeds (hash dedup makes any overlap idempotent).
            if outcome == "error":
                logger.warning("uid=%s: process_message returned error, stopping batch for retry", uid_str)
                break

            self._mail.store(uid_str, "+FLAGS", "\\Seen")

            if uid_int > highest_uid:
                highest_uid = uid_int
            processed += 1

        validity_to_save = current_validity if current_validity is not None else last_validity
        if highest_uid > last_uid or validity_changed or (current_validity is not None and last_validity is None):
            save_poller_state(self._db_path, highest_uid, validity_to_save)

        save_heartbeat(self._db_path)
        return processed

    def run(self, shutdown_event: threading.Event):
        """Main poll loop. Blocks until shutdown_event is set."""
        backoff = 0

        while not shutdown_event.is_set():
            try:
                self.connect()
                count = self.poll_once()
                if count > 0:
                    logger.info("Processed %d message(s)", count)
                backoff = 0
            except (imaplib.IMAP4.error, OSError, ConnectionError) as exc:
                logger.warning("IMAP error: %s. Reconnecting in %ds", exc, backoff or _BACKOFF_INITIAL)
                self.disconnect()
                if shutdown_event.wait(backoff or _BACKOFF_INITIAL):
                    break
                backoff = min((backoff or _BACKOFF_INITIAL) * 2, _BACKOFF_MAX)
                continue
            except Exception:
                logger.exception("Unexpected error in poll loop")
                self.disconnect()
                if shutdown_event.wait(backoff or _BACKOFF_INITIAL):
                    break
                backoff = min((backoff or _BACKOFF_INITIAL) * 2, _BACKOFF_MAX)
                continue

            if shutdown_event.wait(self.poll_interval):
                break

        self.disconnect()
        logger.info("Poller stopped")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        level=logging.INFO,
        stream=sys.stdout,
    )

    server = os.environ.get("IMAP_SERVER", "imap.gmail.com")
    port = int(os.environ.get("IMAP_PORT", "993"))
    user = os.environ.get("IMAP_USER", "").strip()
    password = os.environ.get("IMAP_PASSWORD", "").strip()
    folder = os.environ.get("IMAP_FOLDER", "INBOX")
    poll_interval = int(os.environ.get("IMAP_POLL_INTERVAL", str(_POLL_INTERVAL_DEFAULT)))

    # Graceful shutdown on SIGTERM/SIGINT — install before any wait loop so the
    # idle branch below is also interruptible.
    shutdown = threading.Event()

    def _handle_signal(signum: int, _frame: FrameType | None) -> None:
        logger.info("Received signal %s, shutting down...", signum)
        shutdown.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # If IMAP creds are missing, idle instead of crashing. The container's
    # `restart: unless-stopped` policy would otherwise crash-loop us forever on
    # a bare `docker compose up` with no .env wired.
    if not user or not password:
        logger.info(
            "IMAP credentials not configured (IMAP_USER/IMAP_PASSWORD empty); "
            "idling. Set both in .env to enable polling."
        )
        while not shutdown.is_set():
            shutdown.wait(timeout=poll_interval)
        return

    # Ensure SQLite schema exists (safe if finance container already created it)
    ensure_schema()

    # AI client for categorization — prefers ChatGPT OAuth, falls back to API key.
    from src.finance.ai_client import get_ai_client

    api_client = get_ai_client()
    if api_client is None:
        logger.info("No AI provider configured — categories will default to Miscellaneous")
    else:
        logger.info("AI categorization enabled (provider: %s)", type(api_client).__name__)

    transactions_db = create_transactions_db()
    context_enricher = create_transaction_context_enricher()
    parse_failure_store = create_parse_failure_store()

    logger.info(
        "Starting IMAP poller: server=%s, user=%s, folder=%s, interval=%ds",
        server,
        _mask_user(user),
        folder,
        poll_interval,
    )

    poller = ImapPoller(
        server,
        port,
        user,
        password,
        folder,
        poll_interval,
        transactions_db=transactions_db,
        context_enricher=context_enricher,
        api_client=api_client,
        parse_failure_store=parse_failure_store,
    )
    poller.run(shutdown)


if __name__ == "__main__":
    main()
