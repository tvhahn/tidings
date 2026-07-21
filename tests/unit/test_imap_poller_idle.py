"""Tests for the idle path in imap_poller.main().

When IMAP_USER or IMAP_PASSWORD is empty/unset, the daemon must log a single
idle line and wait on the shutdown event instead of crashing. This is the
load-bearing fix for the bare `docker compose up` UX — without it, the
`restart: unless-stopped` policy crash-loops the imap-poller container forever
for any self-hoster who hasn't wired IMAP creds yet.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from src.finance.imap_poller import main


class _OneShotEvent:
    """Minimal threading.Event stand-in: the first `wait()` returns True and
    flips `is_set()`, so the idle loop exits after one iteration."""

    def __init__(self) -> None:
        self._set = False

    def set(self) -> None:
        self._set = True

    def is_set(self) -> bool:
        return self._set

    def wait(self, timeout: float | None = None) -> bool:
        self._set = True
        return True


@pytest.fixture
def _silence_signal_handlers():
    """Don't install real signal handlers during tests — pytest's own handlers
    must stay in place. Yields the patcher so callers can assert no-op."""
    with patch("src.finance.imap_poller.signal.signal") as sig:
        yield sig


class TestImapPollerIdle:
    """main() idles cleanly when IMAP credentials are unset or empty."""

    @patch("src.finance.imap_poller.create_transactions_db")
    @patch("src.finance.imap_poller.create_transaction_context_enricher")
    @patch("src.finance.imap_poller.ensure_schema")
    @patch("src.finance.imap_poller.ImapPoller")
    @patch("src.finance.imap_poller.threading.Event", new=_OneShotEvent)
    def test_missing_user_idles_without_crashing(
        self,
        mock_poller_cls: MagicMock,
        mock_ensure_schema: MagicMock,
        mock_enricher: MagicMock,
        mock_create_db: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        _silence_signal_handlers: MagicMock,
    ) -> None:
        monkeypatch.delenv("IMAP_USER", raising=False)
        monkeypatch.setenv("IMAP_PASSWORD", "some-secret")

        with caplog.at_level(logging.INFO, logger="src.finance.imap_poller"):
            main()

        assert any(
            "IMAP credentials not configured" in rec.message and "idling" in rec.message for rec in caplog.records
        ), f"expected idle log line, got: {[r.message for r in caplog.records]}"

        # Idle path must skip all setup — no DB, no AI, no IMAP class instantiated.
        mock_ensure_schema.assert_not_called()
        mock_create_db.assert_not_called()
        mock_enricher.assert_not_called()
        mock_poller_cls.assert_not_called()

    @patch("src.finance.imap_poller.create_transactions_db")
    @patch("src.finance.imap_poller.create_transaction_context_enricher")
    @patch("src.finance.imap_poller.ensure_schema")
    @patch("src.finance.imap_poller.ImapPoller")
    @patch("src.finance.imap_poller.threading.Event", new=_OneShotEvent)
    def test_missing_password_idles_without_crashing(
        self,
        mock_poller_cls: MagicMock,
        mock_ensure_schema: MagicMock,
        mock_enricher: MagicMock,
        mock_create_db: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        _silence_signal_handlers: MagicMock,
    ) -> None:
        monkeypatch.setenv("IMAP_USER", "user@example.com")
        monkeypatch.delenv("IMAP_PASSWORD", raising=False)

        with caplog.at_level(logging.INFO, logger="src.finance.imap_poller"):
            main()

        assert any("IMAP credentials not configured" in rec.message for rec in caplog.records)
        mock_ensure_schema.assert_not_called()
        mock_create_db.assert_not_called()
        mock_enricher.assert_not_called()
        mock_poller_cls.assert_not_called()

    @patch("src.finance.imap_poller.create_transactions_db")
    @patch("src.finance.imap_poller.create_transaction_context_enricher")
    @patch("src.finance.imap_poller.ensure_schema")
    @patch("src.finance.imap_poller.ImapPoller")
    @patch("src.finance.imap_poller.threading.Event", new=_OneShotEvent)
    def test_whitespace_only_creds_treated_as_missing(
        self,
        mock_poller_cls: MagicMock,
        mock_ensure_schema: MagicMock,
        mock_enricher: MagicMock,
        mock_create_db: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        _silence_signal_handlers: MagicMock,
    ) -> None:
        # `.strip()` should treat "   " as empty — otherwise a stray space in
        # an unedited .env.example would cause a confusing IMAP auth error.
        monkeypatch.setenv("IMAP_USER", "   ")
        monkeypatch.setenv("IMAP_PASSWORD", "secret")

        with caplog.at_level(logging.INFO, logger="src.finance.imap_poller"):
            main()

        assert any("IMAP credentials not configured" in rec.message for rec in caplog.records)
        mock_poller_cls.assert_not_called()

    @patch("src.finance.imap_poller.create_transactions_db")
    @patch("src.finance.imap_poller.create_transaction_context_enricher")
    @patch("src.finance.imap_poller.ensure_schema")
    @patch("src.finance.ai_client.get_ai_client")
    @patch("src.finance.imap_poller.ImapPoller")
    def test_creds_present_reaches_poller(
        self,
        mock_poller_cls: MagicMock,
        mock_get_ai: MagicMock,
        mock_ensure_schema: MagicMock,
        mock_enricher: MagicMock,
        mock_create_db: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        _silence_signal_handlers: MagicMock,
    ) -> None:
        """Happy path: both creds set → main() reaches ImapPoller.run()."""
        monkeypatch.setenv("IMAP_USER", "user@example.com")
        monkeypatch.setenv("IMAP_PASSWORD", "secret")

        mock_get_ai.return_value = None  # no AI provider → categorizes to Misc
        mock_poller_instance = MagicMock(name="poller_instance")
        mock_poller_cls.return_value = mock_poller_instance

        main()

        mock_ensure_schema.assert_called_once()
        mock_poller_cls.assert_called_once()
        mock_poller_instance.run.assert_called_once()
