"""Tests for IMAP polling daemon.

Tests mock at the function level (parse_email, add_transaction, IMAP connection)
to verify the poller's orchestration logic, mirroring test_lambda_handler.py patterns.
"""

import imaplib
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.finance.imap_poller import (
    ImapPoller,
    get_imap_last_poll,
    get_uidvalidity,
    load_poller_state,
    process_message,
    save_poller_state,
)
from src.finance.local_db import ensure_schema

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(**overrides: Any) -> dict[str, Any]:
    """Build a transaction result dict with sensible defaults."""
    result: dict[str, Any] = {
        "forwarded_to": "user@example.com",
        "company": "Starbucks",
        "amount": 5.50,
        "date": "01/15/2026 14:30 PST",
        "transaction_type": "purchase",
        "institution": "CIBC",
        "category": "Restaurant/Dining",
        "name": "Demo",
        "file_name": "imap/2026/01/uid-100.eml",
    }
    result.update(overrides)
    return result


# ---------------------------------------------------------------------------
# process_message tests
# ---------------------------------------------------------------------------


class TestProcessMessage:
    """Tests for the per-email processing pipeline."""

    @patch("src.finance.email_pipeline.notification_service.send")
    @patch("src.finance.email_pipeline.parse_email")
    def test_new_transaction_stores_enriches_notifies(self, mock_parse: MagicMock, mock_notify: MagicMock) -> None:
        result = _make_result()
        mock_parse.return_value = result

        mock_db = MagicMock(name="db")
        mock_db.add_transaction.return_value = "2026.01.15_14.30_uid-100.eml"
        mock_enricher = MagicMock(name="enricher")
        context = {"category_month_total": 100.0}
        mock_enricher.enrich.return_value = context

        status = process_message(b"raw bytes", "100", mock_db, mock_enricher)

        assert status == "new"
        mock_db.add_transaction.assert_called_once_with(result, category_audit=None, extraction_audit=None)
        mock_enricher.enrich.assert_called_once_with(result)

    @patch("src.finance.email_pipeline.notification_service.send")
    @patch("src.finance.email_pipeline.parse_email")
    def test_propagates_category_audit_from_parse_to_db(self, mock_parse: MagicMock, _mock_notify: MagicMock) -> None:
        """parse_email stamps result['_category_audit']; the poller must forward it."""
        audit = {"source": "ai", "model": "gpt-5.4-nano", "reviewed_at": "2026-05-16T10:00:00-07:00"}
        result = _make_result(_category_audit=audit)
        mock_parse.return_value = result

        mock_db = MagicMock(name="db")
        mock_db.add_transaction.return_value = "2026.01.15_14.30_uid-100.eml"

        process_message(b"raw bytes", "200", mock_db, MagicMock())

        args, kwargs = mock_db.add_transaction.call_args
        # The audit was popped off before persistence.
        assert "_category_audit" not in args[0]
        assert kwargs["category_audit"] == audit

    @patch("src.finance.email_pipeline.notification_service.send")
    @patch("src.finance.email_pipeline.parse_email")
    def test_duplicate_skips_enrichment(self, mock_parse: MagicMock, mock_notify: MagicMock) -> None:
        mock_parse.return_value = _make_result()
        mock_db = MagicMock()
        mock_db.add_transaction.return_value = False

        mock_enricher = MagicMock(name="enricher")

        status = process_message(b"raw bytes", "100", mock_db, mock_enricher)

        assert status == "duplicate"
        mock_enricher.enrich.assert_not_called()
        mock_notify.assert_not_called()

    @patch("src.finance.email_pipeline.notification_service.send")
    @patch("src.finance.email_pipeline.parse_email")
    def test_no_parser_match_is_skipped(self, mock_parse: MagicMock, mock_notify: MagicMock) -> None:
        """Emails that no bank parser matched (no `transaction_type`) must not reach the DB."""
        mock_parse.return_value = {"body": "some text", "from_email": "no-reply@accounts.google.com"}
        mock_db = MagicMock(name="db")
        mock_enricher = MagicMock(name="enricher")

        status = process_message(b"raw bytes", "100", mock_db, mock_enricher)

        assert status == "skipped"
        mock_db.add_transaction.assert_not_called()
        mock_enricher.enrich.assert_not_called()
        mock_notify.assert_not_called()

    @patch("src.finance.email_pipeline.notification_service.send")
    @patch("src.finance.email_pipeline.parse_email")
    def test_no_transaction_type_with_store_quarantines(self, mock_parse: MagicMock, mock_notify: MagicMock) -> None:
        """An email no parser matched, but relevant (known sender), is captured.

        With a store wired in, process_message records the failure and returns
        the new "quarantined" status instead of "skipped".
        """
        mock_parse.return_value = {
            "body": "balance alert with no transaction",
            "from_email": "alerts@cibc.com",
            "subject": "Balance alert",
        }
        mock_db = MagicMock(name="db")
        mock_enricher = MagicMock(name="enricher")
        mock_store = MagicMock(name="store")
        mock_store.record_failure.return_value = "pf_abc123"

        status = process_message(b"raw bytes", "100", mock_db, mock_enricher, None, mock_store)

        assert status == "quarantined"
        mock_store.record_failure.assert_called_once()
        recorded = mock_store.record_failure.call_args[0][0]
        assert recorded["detected_institution"] == "CIBC"
        assert recorded["failure_stage"] == "extraction_empty"
        mock_db.add_transaction.assert_not_called()
        mock_enricher.enrich.assert_not_called()
        mock_notify.assert_not_called()

    @patch("src.finance.email_pipeline.notification_service.send")
    @patch("src.finance.email_pipeline.parse_email")
    def test_no_transaction_type_irrelevant_still_skips(self, mock_parse: MagicMock, mock_notify: MagicMock) -> None:
        """An irrelevant email (no institution, no AI) still returns 'skipped'."""
        mock_parse.return_value = {
            "body": "weekly newsletter",
            "from_email": "news@example.com",
            "subject": "This week's deals",
        }
        mock_db = MagicMock()
        mock_store = MagicMock(name="store")

        status = process_message(b"raw", "100", mock_db, MagicMock(), None, mock_store)

        assert status == "skipped"
        mock_store.record_failure.assert_not_called()

    @patch("src.finance.email_pipeline.notification_service.send")
    @patch("src.finance.email_pipeline.parse_email")
    def test_invalid_with_store_quarantines_db_validation(self, mock_parse: MagicMock, mock_notify: MagicMock) -> None:
        """A parsed transaction that fails DB validation is captured + returns 'invalid'."""
        mock_parse.return_value = _make_result()
        mock_db = MagicMock()
        mock_db.add_transaction.return_value = None
        mock_store = MagicMock(name="store")
        mock_store.record_failure.return_value = "pf_dbfail"

        status = process_message(b"raw", "100", mock_db, MagicMock(), None, mock_store)

        assert status == "invalid"
        mock_store.record_failure.assert_called_once()
        recorded = mock_store.record_failure.call_args[0][0]
        assert recorded["failure_stage"] == "db_validation_failed"

    @patch("src.finance.email_pipeline.notification_service.send")
    @patch("src.finance.parse_recovery.recover_or_quarantine")
    @patch("src.finance.email_pipeline.parse_email")
    def test_recovered_transaction_stores_and_marks_recovered(
        self, mock_parse: MagicMock, mock_recover: MagicMock, mock_notify: MagicMock
    ) -> None:
        """A recovered email stores its merged transaction, pops both provenance
        keys onto add_transaction, and flips the row to 'recovered'."""
        from src.finance.parse_recovery import RecoveryOutcome

        mock_parse.return_value = {
            "body": "no parser matched",
            "from_email": "alerts@cibc.com",
            "subject": "alert",
        }
        merged = _make_result(
            _extraction_audit={"method": "ai_fallback", "model": "m"},
            _category_audit={"source": "ai_fallback"},
        )
        mock_recover.return_value = RecoveryOutcome("recovered", merged, "pf_rec")

        mock_db = MagicMock(name="db")
        mock_db.add_transaction.return_value = "2026.01.15_14.30_uid-100.eml"
        mock_db.update_context.return_value = None
        mock_enricher = MagicMock()
        mock_enricher.enrich.return_value = None
        mock_store = MagicMock(name="store")

        status = process_message(b"raw", "100", mock_db, mock_enricher, None, mock_store)

        assert status == "new"
        # Both audits were popped and passed through; neither remains on the dict.
        _, kwargs = mock_db.add_transaction.call_args
        assert kwargs["category_audit"] == {"source": "ai_fallback"}
        assert kwargs["extraction_audit"] == {"method": "ai_fallback", "model": "m"}
        assert "_extraction_audit" not in merged
        assert "_category_audit" not in merged
        mock_store.set_status.assert_called_once_with(
            "pf_rec", "recovered", recovered_date_file_name="2026.01.15_14.30_uid-100.eml"
        )

    @patch("src.finance.email_pipeline.notification_service.send")
    @patch("src.finance.parse_recovery.recover_or_quarantine")
    @patch("src.finance.email_pipeline.parse_email")
    def test_recovered_transaction_db_reject_downgrades(
        self, mock_parse: MagicMock, mock_recover: MagicMock, mock_notify: MagicMock
    ) -> None:
        """A recovered email whose add_transaction returns None downgrades the
        pre-marked 'recovered' row back to 'quarantined' (downgrade, don't lose)."""
        from src.finance.parse_recovery import RecoveryOutcome

        mock_parse.return_value = {
            "body": "no parser matched",
            "from_email": "alerts@cibc.com",
            "subject": "alert",
        }
        merged = _make_result(_extraction_audit={"method": "ai_fallback"})
        mock_recover.return_value = RecoveryOutcome("recovered", merged, "pf_rec")

        mock_db = MagicMock()
        mock_db.add_transaction.return_value = None  # DB rejects the recovered row
        mock_store = MagicMock(name="store")

        status = process_message(b"raw", "100", mock_db, MagicMock(), None, mock_store)

        assert status == "invalid"
        mock_store.set_status.assert_called_once_with("pf_rec", "quarantined")
        # The plain db-invalid path must NOT also fire (no double record).
        mock_store.record_failure.assert_not_called()

    @patch("src.finance.email_pipeline.notification_service.send")
    @patch("src.finance.email_pipeline.parse_email")
    def test_validation_failure_skips_enrichment(self, mock_parse: MagicMock, mock_notify: MagicMock) -> None:
        """A parsed transaction that still fails DB validation returns 'invalid'."""
        mock_parse.return_value = _make_result()
        mock_db = MagicMock()
        mock_db.add_transaction.return_value = None

        mock_enricher = MagicMock(name="enricher")

        status = process_message(b"raw bytes", "100", mock_db, mock_enricher)

        assert status == "invalid"
        mock_enricher.enrich.assert_not_called()
        mock_notify.assert_not_called()

    @patch("src.finance.email_pipeline.notification_service.send")
    @patch("src.finance.email_pipeline.parse_email")
    def test_enrichment_none_still_notifies(self, mock_parse: MagicMock, mock_notify: MagicMock) -> None:
        result = _make_result()
        mock_parse.return_value = result
        mock_db = MagicMock(name="db")
        mock_db.add_transaction.return_value = "2026.01.15_14.30_uid-100.eml"
        mock_enricher = MagicMock()
        mock_enricher.enrich.return_value = None

        status = process_message(b"raw bytes", "100", mock_db, mock_enricher)

        assert status == "new"
        mock_db.update_context.assert_not_called()
        mock_notify.assert_called_once_with(result, context=None)

    @patch("src.finance.email_pipeline.notification_service.send")
    @patch("src.finance.email_pipeline.parse_email")
    def test_parse_error_returns_error(self, mock_parse: MagicMock, mock_notify: MagicMock) -> None:
        mock_parse.side_effect = ValueError("bad email")
        mock_db = MagicMock(name="db")
        mock_enricher = MagicMock()

        status = process_message(b"garbage", "100", mock_db, mock_enricher)

        assert status == "error"
        mock_db.add_transaction.assert_not_called()

    @patch("src.finance.email_pipeline.notification_service.send")
    @patch("src.finance.email_pipeline.parse_email")
    def test_file_name_format(self, mock_parse: MagicMock, mock_notify: MagicMock) -> None:
        mock_parse.return_value = _make_result()
        mock_db = MagicMock()
        mock_db.add_transaction.return_value = False  # doesn't matter for this test
        mock_enricher = MagicMock()

        process_message(b"raw", "42", mock_db, mock_enricher)

        # Verify parse_email was called with correct file_name pattern
        call_args = mock_parse.call_args
        file_name = call_args[0][1]
        assert file_name.startswith("imap/")
        assert "/uid-42.eml" in file_name


# ---------------------------------------------------------------------------
# Poller state persistence tests
# ---------------------------------------------------------------------------


class TestPollerStatePersistence:
    """Tests for poller state (uid + uidvalidity) save/load using config_store."""

    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path: Path) -> None:
        self.db_path = tmp_path / "test.db"
        ensure_schema(self.db_path)

    def test_load_returns_defaults_when_empty(self) -> None:
        assert load_poller_state(self.db_path) == (0, None)

    def test_save_and_load_uid_only(self):
        save_poller_state(self.db_path, uid=42)
        assert load_poller_state(self.db_path) == (42, None)

    def test_save_and_load_with_uidvalidity(self):
        save_poller_state(self.db_path, uid=42, uidvalidity=1234)
        assert load_poller_state(self.db_path) == (42, 1234)

    def test_save_overwrites_previous(self):
        save_poller_state(self.db_path, uid=10, uidvalidity=1)
        save_poller_state(self.db_path, uid=20, uidvalidity=2)
        assert load_poller_state(self.db_path) == (20, 2)

    def test_legacy_payload_missing_uidvalidity(self):
        """Old JSON blobs have only {'uid': N} — ensure we read them gracefully."""
        import json
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO config_store (pk, sk, data_json, version, updated_at) VALUES (?, ?, ?, 1, ?)",
            ("SYSTEM#imap_poller", "last_seen_uid", json.dumps({"uid": 11}), "2026-04-19T00:00:00Z"),
        )
        conn.commit()
        conn.close()
        assert load_poller_state(self.db_path) == (11, None)


# ---------------------------------------------------------------------------
# Heartbeat (get_imap_last_poll) tests
# ---------------------------------------------------------------------------


class TestHeartbeat:
    """Tests for the /health probe's poll-freshness source."""

    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path: Path) -> None:
        self.db_path = tmp_path / "test.db"
        ensure_schema(self.db_path)

    def test_returns_none_on_empty_db(self) -> None:
        assert get_imap_last_poll(self.db_path) is None

    def test_falls_back_to_uid_row_when_no_heartbeat(self):
        save_poller_state(self.db_path, uid=7)
        result = get_imap_last_poll(self.db_path)
        assert result is not None
        assert "T" in result  # looks ISO-8601

    def test_prefers_heartbeat_over_uid_row(self):
        import time

        save_poller_state(self.db_path, uid=7)
        # Small sleep so the heartbeat row has a strictly-later updated_at.
        time.sleep(0.01)
        from src.finance.imap_poller import save_heartbeat

        save_heartbeat(self.db_path)
        result = get_imap_last_poll(self.db_path)
        assert result is not None

    def test_swallows_missing_db_file(self, tmp_path: Path) -> None:
        # Pointing at a path that doesn't exist must not raise — SQLite will
        # actually create it, but query will return None because there's no
        # schema. We accept either "None" or a graceful recovery; the contract
        # is "never raise".
        missing = tmp_path / "does-not-exist" / "x.db"
        # Parent directory does not exist, connect() will raise; helper must
        # swallow that and return None.
        assert get_imap_last_poll(missing) is None

    def test_returns_none_when_config_store_table_missing(self, tmp_path: Path) -> None:
        # /api/v1/health calls this on first boot, before any write has
        # triggered ensure_schema(). SQLite's connect() happily creates the
        # file empty, and the SELECT then raises OperationalError. Without
        # the catch, /api/v1/health returns 500 on a fresh `docker compose up`.
        unschemad = tmp_path / "empty.db"
        unschemad.touch()  # file exists, no tables — exactly the first-boot state
        assert get_imap_last_poll(unschemad) is None


# ---------------------------------------------------------------------------
# poll_once tests
# ---------------------------------------------------------------------------


class TestPollOnce:
    """Tests for a single poll iteration."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path: Path) -> None:
        self.db_path = tmp_path / "test.db"
        ensure_schema(self.db_path)

        self.mock_mail = MagicMock(spec=imaplib.IMAP4_SSL, name="mail")
        self.mock_db = MagicMock()
        self.mock_enricher = MagicMock()

        self.poller = ImapPoller(
            "imap.test.com",
            993,
            "user@test.com",
            "password",
            transactions_db=self.mock_db,
            context_enricher=self.mock_enricher,
            db_path=self.db_path,
        )
        # Inject mock IMAP connection
        self.poller._mail = self.mock_mail

    def test_no_new_messages_returns_zero(self):
        self.mock_mail.search.return_value = ("OK", [b""])
        assert self.poller.poll_once() == 0

    def test_empty_poll_writes_heartbeat(self):
        """A successful no-op poll must still record a heartbeat so /health
        doesn't flag a healthy-but-idle poller as stale."""
        self.mock_mail.search.return_value = ("OK", [b""])
        assert get_imap_last_poll(self.db_path) is None
        self.poller.poll_once()
        assert get_imap_last_poll(self.db_path) is not None

    def test_first_run_searches_unseen(self):
        self.mock_mail.search.return_value = ("OK", [b""])
        self.poller.poll_once()
        self.mock_mail.search.assert_called_once_with(None, "UNSEEN")

    @patch("src.finance.imap_poller.process_message", return_value="new")
    def test_subsequent_run_searches_uid_range(self, _mock_process: MagicMock) -> None:
        save_poller_state(self.db_path, uid=100)
        self.mock_mail.search.return_value = ("OK", [b"101"])
        self.mock_mail.fetch.return_value = ("OK", [(b"101", b"raw email")])

        self.poller.poll_once()

        self.mock_mail.search.assert_called_once_with(None, "UID 101:*")

    @patch("src.finance.imap_poller.process_message", return_value="new")
    def test_saves_highest_uid_after_batch(self, _mock_process: MagicMock) -> None:
        self.mock_mail.search.return_value = ("OK", [b"101 102 103"])
        self.mock_mail.fetch.return_value = ("OK", [(b"x", b"raw email")])

        self.poller.poll_once()

        assert load_poller_state(self.db_path)[0] == 103

    @patch("src.finance.imap_poller.process_message", return_value="new")
    def test_marks_seen_after_processing(self, _mock_process: MagicMock) -> None:
        self.mock_mail.search.return_value = ("OK", [b"50"])
        self.mock_mail.fetch.return_value = ("OK", [(b"50", b"raw email")])

        self.poller.poll_once()

        self.mock_mail.store.assert_called_once_with("50", "+FLAGS", "\\Seen")

    @patch("src.finance.imap_poller.process_message", return_value="quarantined")
    def test_quarantined_marks_seen_and_advances(self, _mock_process: MagicMock) -> None:
        """A 'quarantined' outcome captures the email, so the UID must still be
        marked SEEN and the bookmark advanced — do not leave it unseen."""
        self.mock_mail.search.return_value = ("OK", [b"77"])
        self.mock_mail.fetch.return_value = ("OK", [(b"77", b"raw email")])

        count = self.poller.poll_once()

        assert count == 1
        self.mock_mail.store.assert_called_once_with("77", "+FLAGS", "\\Seen")
        assert load_poller_state(self.db_path)[0] == 77

    def test_empty_fetch_response_skipped(self):
        self.mock_mail.search.return_value = ("OK", [b"50"])
        self.mock_mail.fetch.return_value = ("OK", [None])

        count = self.poller.poll_once()
        assert count == 0

    @patch("src.finance.imap_poller.process_message")
    def test_fetch_response_with_non_tuple_parts_skipped(self, mock_process):
        """If imaplib returns bare bytes (e.g. `[b')']`) instead of a (info, body)
        tuple, the poller must skip safely rather than pass an int to BytesParser."""
        save_poller_state(self.db_path, uid=18)
        self.mock_mail.search.return_value = ("OK", [b"19"])
        self.mock_mail.fetch.return_value = ("OK", [b")"])

        count = self.poller.poll_once()

        assert count == 0
        mock_process.assert_not_called()
        self.mock_mail.store.assert_not_called()
        # Bookmark must not advance — UID 19 needs to be retried next poll.
        assert load_poller_state(self.db_path)[0] == 18

    @patch("src.finance.imap_poller.process_message", return_value="error")
    def test_process_error_does_not_advance_uid(self, _mock_process):
        """A transient parse error must leave the bookmark + SEEN flag untouched
        so the next poll retries instead of silently orphaning the message."""
        save_poller_state(self.db_path, uid=18)
        self.mock_mail.search.return_value = ("OK", [b"19"])
        self.mock_mail.fetch.return_value = ("OK", [(b"19", b"raw email")])

        count = self.poller.poll_once()

        assert count == 0
        self.mock_mail.store.assert_not_called()
        assert load_poller_state(self.db_path)[0] == 18

    @patch("src.finance.imap_poller.process_message", side_effect=["error", "new"])
    def test_mid_batch_error_stops_before_later_successes(self, mock_process: MagicMock) -> None:
        """Regression: uid 19 errors, uid 20 would succeed. The old `continue`
        let uid 20 advance the bookmark to 20, so uid 19 (search starts at
        21 next poll) was never retried and never marked SEEN. The batch must
        stop at the failure; uid 20 is re-fetched on the next poll."""
        save_poller_state(self.db_path, uid=18)
        self.mock_mail.search.return_value = ("OK", [b"19 20"])
        self.mock_mail.fetch.return_value = ("OK", [(b"x", b"raw email")])

        count = self.poller.poll_once()

        assert count == 0
        # Only uid 19 was attempted; the batch stopped before uid 20.
        assert mock_process.call_count == 1
        self.mock_mail.store.assert_not_called()
        assert load_poller_state(self.db_path)[0] == 18

    @patch("src.finance.imap_poller.process_message", return_value="new")
    def test_skips_uids_at_or_below_last(self, _mock_process: MagicMock) -> None:
        """UID search can return last_uid itself; those should be skipped."""
        save_poller_state(self.db_path, uid=100)
        self.mock_mail.search.return_value = ("OK", [b"100 101"])
        self.mock_mail.fetch.return_value = ("OK", [(b"x", b"raw email")])

        count = self.poller.poll_once()

        # Only uid 101 should be processed
        assert count == 1
        assert load_poller_state(self.db_path)[0] == 101

    def test_only_equal_last_uid_logs_heartbeat(self, caplog):
        """`UID N:*` returns the highest existing UID when no new messages exist.
        That no-op must still log the heartbeat so silence unambiguously means dead."""
        import logging

        save_poller_state(self.db_path, uid=42)
        self.mock_mail.search.return_value = ("OK", [b"42"])

        with caplog.at_level(logging.INFO, logger="src.finance.imap_poller"):
            count = self.poller.poll_once()

        assert count == 0
        self.mock_mail.fetch.assert_not_called()
        assert any("poll: no new UIDs" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# UIDVALIDITY tracking tests
# ---------------------------------------------------------------------------


class TestUidValidity:
    """Tests for UIDVALIDITY tracking and auto-reset on mismatch."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.db_path = tmp_path / "test.db"
        ensure_schema(self.db_path)

        self.mock_mail = MagicMock(spec=imaplib.IMAP4_SSL, name="mail")
        self.mock_db = MagicMock()
        self.mock_enricher = MagicMock()

        self.poller = ImapPoller(
            "imap.test.com",
            993,
            "user@test.com",
            "password",
            transactions_db=self.mock_db,
            context_enricher=self.mock_enricher,
            db_path=self.db_path,
        )
        self.poller._mail = self.mock_mail

    def _set_uidvalidity(self, value):
        self.mock_mail.response.return_value = ("OK", [str(value).encode()])

    def testget_uidvalidity_parses_response(self):
        self._set_uidvalidity(1234)
        assert get_uidvalidity(self.mock_mail) == 1234

    def testget_uidvalidity_returns_none_on_missing_data(self):
        self.mock_mail.response.return_value = ("OK", [None])
        assert get_uidvalidity(self.mock_mail) is None

    def testget_uidvalidity_returns_none_on_error(self):
        self.mock_mail.response.side_effect = imaplib.IMAP4.error("boom")
        assert get_uidvalidity(self.mock_mail) is None

    def test_first_run_persists_uidvalidity(self):
        """With no stored state, a poll should save the observed UIDVALIDITY."""
        self._set_uidvalidity(7)
        self.mock_mail.search.return_value = ("OK", [b""])

        self.poller.poll_once()

        assert load_poller_state(self.db_path) == (0, 7)

    @patch("src.finance.imap_poller.process_message", return_value="new")
    def test_mismatch_resets_last_uid(self, _mock_process):
        """When UIDVALIDITY differs from stored value, last_uid resets to 0 and UNSEEN is searched."""
        save_poller_state(self.db_path, uid=100, uidvalidity=5)
        self._set_uidvalidity(9)  # mailbox rebuilt
        self.mock_mail.search.return_value = ("OK", [b"3"])
        self.mock_mail.fetch.return_value = ("OK", [(b"3", b"raw email")])

        count = self.poller.poll_once()

        assert count == 1
        # search should have used UNSEEN, not UID 101:*
        self.mock_mail.search.assert_called_once_with(None, "UNSEEN")
        # New state: fresh UIDVALIDITY, highest UID from this batch
        assert load_poller_state(self.db_path) == (3, 9)

    def test_match_preserves_state(self):
        """When UIDVALIDITY matches, search uses UID range and state is preserved."""
        save_poller_state(self.db_path, uid=100, uidvalidity=5)
        self._set_uidvalidity(5)
        self.mock_mail.search.return_value = ("OK", [b""])

        self.poller.poll_once()

        self.mock_mail.search.assert_called_once_with(None, "UID 101:*")
        assert load_poller_state(self.db_path) == (100, 5)


# ---------------------------------------------------------------------------
# Connection management tests
# ---------------------------------------------------------------------------


class TestConnectionManagement:
    """Tests for connect/disconnect/reconnect behavior."""

    def _make_poller(self):
        return ImapPoller(
            "imap.test.com",
            993,
            "user@test.com",
            "pa ss wo rd",
            transactions_db=MagicMock(),
            context_enricher=MagicMock(),
        )

    @patch("src.finance.imap_poller.imaplib.IMAP4_SSL")
    def test_connect_strips_password_spaces(self, mock_imap_cls: MagicMock) -> None:
        mock_conn = MagicMock(name="conn")
        mock_imap_cls.return_value = mock_conn
        poller = self._make_poller()

        poller.connect()

        mock_conn.login.assert_called_once_with("user@test.com", "password")

    @patch("src.finance.imap_poller.imaplib.IMAP4_SSL")
    def test_connect_probes_with_noop_when_already_connected(self, mock_imap_cls: MagicMock) -> None:
        """When a connection already exists, connect() should NOOP to verify it's alive."""
        poller = self._make_poller()
        existing = MagicMock(name="existing")
        poller._mail = existing

        poller.connect()

        existing.noop.assert_called_once()
        mock_imap_cls.assert_not_called()
        assert poller._mail is existing

    @patch("src.finance.imap_poller.imaplib.IMAP4_SSL")
    def test_connect_reconnects_when_noop_fails(self, mock_imap_cls):
        """A stale connection (NOOP raises) should be torn down and replaced."""
        fresh = MagicMock(name="fresh")
        mock_imap_cls.return_value = fresh

        poller = self._make_poller()
        stale = MagicMock(name="stale")
        stale.noop.side_effect = OSError("broken pipe")
        poller._mail = stale

        poller.connect()

        stale.noop.assert_called_once()
        mock_imap_cls.assert_called_once()
        fresh.login.assert_called_once_with("user@test.com", "password")
        fresh.select.assert_called_once_with("INBOX")
        assert poller._mail is fresh

    def test_disconnect_calls_logout(self):
        poller = self._make_poller()
        mock_mail = MagicMock(name="mail")
        poller._mail = mock_mail

        poller.disconnect()

        mock_mail.logout.assert_called_once()
        assert poller._mail is None

    def test_disconnect_swallows_logout_error(self):
        poller = self._make_poller()
        mock_mail = MagicMock()
        mock_mail.logout.side_effect = OSError("connection lost")
        poller._mail = mock_mail

        poller.disconnect()  # should not raise

        assert poller._mail is None

    def test_disconnect_noop_when_not_connected(self):
        poller = self._make_poller()
        poller.disconnect()  # should not raise


# ---------------------------------------------------------------------------
# Graceful shutdown test
# ---------------------------------------------------------------------------


class TestGracefulShutdown:
    """Tests for signal handling and graceful shutdown."""

    @patch("src.finance.imap_poller.imaplib.IMAP4_SSL")
    def test_shutdown_event_stops_loop(self, mock_imap_cls: MagicMock) -> None:
        """Poller exits cleanly when shutdown event is set."""
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn
        mock_conn.search.return_value = ("OK", [b""])

        poller = ImapPoller(
            "imap.test.com",
            993,
            "user@test.com",
            "password",
            poll_interval=1,
            transactions_db=MagicMock(),
            context_enricher=MagicMock(),
        )

        shutdown = threading.Event()

        # Set shutdown after a brief delay
        def _trigger_shutdown():
            shutdown.set()

        timer = threading.Timer(0.1, _trigger_shutdown)
        timer.start()

        poller.run(shutdown)  # should return quickly

        timer.cancel()
        assert shutdown.is_set()

    @patch("src.finance.imap_poller._BACKOFF_INITIAL", 0.01)
    @patch("src.finance.imap_poller.imaplib.IMAP4_SSL")
    def test_imap_error_triggers_reconnect(self, mock_imap_cls: MagicMock) -> None:
        """IMAP error causes disconnect and backoff, not a crash."""
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn

        call_count = 0

        def _search_side_effect(*args: Any) -> tuple[str, list[bytes]]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise imaplib.IMAP4.error("connection dropped")
            return ("OK", [b""])

        mock_conn.search.side_effect = _search_side_effect

        poller = ImapPoller(
            "imap.test.com",
            993,
            "user@test.com",
            "password",
            poll_interval=0,
            transactions_db=MagicMock(),
            context_enricher=MagicMock(),
        )

        shutdown = threading.Event()
        timer = threading.Timer(0.5, shutdown.set)
        timer.start()

        poller.run(shutdown)

        timer.cancel()
        # Should have connected at least twice (initial + reconnect)
        assert mock_imap_cls.call_count >= 2
