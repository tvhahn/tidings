"""Tests for Lambda handler decision branches.

Tests mock at the function level (parse_email, add_transaction, send_sms)
rather than at the AWS SDK level, to verify the handler's orchestration logic.
"""

import importlib
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from docker.email_parsing.lambda_function import handler
from src.finance.ai_cli import DEFAULT_CATEGORIZATION_REASONING_EFFORT, DEFAULT_OPENAI_CHAT_MODEL
from src.finance.secrets import get_openai_api_key

# A model that is deliberately NOT the shared default, used to prove that an
# env override reaches the client and that a foreign model gets no tuned effort.
FOREIGN_MODEL = "gpt-5.4-nano"


def _s3_event(bucket: str = "test-bucket", key: str = "emails/test.eml") -> dict[str, Any]:
    """Build a minimal S3 Lambda event."""
    return {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": bucket},
                    "object": {"key": key},
                }
            }
        ]
    }


class TestHandlerMissingApiKey:
    """Handler should return 500 when every secret tier misses."""

    def test_missing_api_key_returns_500(self) -> None:
        get_openai_api_key.cache_clear()
        with patch(
            "docker.email_parsing.lambda_function.get_openai_api_key",
            side_effect=RuntimeError("no key anywhere"),
        ):
            result = handler(_s3_event(), None)
        assert result is not None
        assert result["statusCode"] == 500
        assert "OpenAI credentials unavailable" in result["body"]


class TestHandlerProcessing:
    """Tests for the main handler processing loop."""

    @pytest.fixture(autouse=True)
    def _setup_env(self) -> Iterator[None]:
        """Provide a fake OpenAI key for all tests in this class."""
        get_openai_api_key.cache_clear()
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
            patch(
                "docker.email_parsing.lambda_function.get_openai_api_key",
                return_value="test-key",
            ),
        ):
            yield
        get_openai_api_key.cache_clear()

    @patch("docker.email_parsing.lambda_function.context_enricher")
    @patch("docker.email_parsing.lambda_function.notification_service.send")
    @patch("docker.email_parsing.lambda_function.transactions_db")
    @patch("docker.email_parsing.lambda_function.parse_email")
    @patch("docker.email_parsing.lambda_function.get_s3_file")
    def test_successful_new_transaction_sends_sms(
        self,
        mock_get_s3: MagicMock,
        mock_parse: MagicMock,
        mock_db: MagicMock,
        mock_sms: MagicMock,
        mock_enricher: MagicMock,
    ) -> None:
        """A new (non-duplicate) transaction triggers SMS."""
        mock_get_s3.return_value = b"raw email bytes"
        mock_parse.return_value = {
            "forwarded_to": "user@example.com",
            "company": "Starbucks",
            "amount": 5.50,
            "transaction_type": "purchase",
        }
        mock_db.add_transaction.return_value = "2026.01.15_14.30_test.eml"
        mock_enricher.enrich.return_value = {"category_month_total": 100.0}

        handler(_s3_event(), None)

        mock_sms.assert_called_once()
        mock_db.add_transaction.assert_called_once()

    @patch("docker.email_parsing.lambda_function.context_enricher")
    @patch("docker.email_parsing.lambda_function.notification_service.send")
    @patch("docker.email_parsing.lambda_function.transactions_db")
    @patch("docker.email_parsing.lambda_function.parse_email")
    @patch("docker.email_parsing.lambda_function.get_s3_file")
    def test_duplicate_transaction_skips_sms(
        self,
        mock_get_s3: MagicMock,
        mock_parse: MagicMock,
        mock_db: MagicMock,
        mock_sms: MagicMock,
        mock_enricher: MagicMock,
    ) -> None:
        """A duplicate transaction should NOT trigger SMS."""
        mock_get_s3.return_value = b"raw email bytes"
        mock_parse.return_value = {
            "company": "Starbucks",
            "amount": 5.50,
            "transaction_type": "purchase",
        }
        mock_db.add_transaction.return_value = False  # duplicate

        handler(_s3_event(), None)

        mock_sms.assert_not_called()
        mock_enricher.enrich.assert_not_called()

    @patch("docker.email_parsing.lambda_function.context_enricher")
    @patch("docker.email_parsing.lambda_function.notification_service.send")
    @patch("docker.email_parsing.lambda_function.transactions_db")
    @patch("docker.email_parsing.lambda_function.parse_email")
    @patch("docker.email_parsing.lambda_function.get_s3_file")
    def test_validation_failure_skips_sms(
        self,
        mock_get_s3: MagicMock,
        mock_parse: MagicMock,
        mock_db: MagicMock,
        mock_sms: MagicMock,
        mock_enricher: MagicMock,
    ) -> None:
        """When add_transaction returns None (validation error), skip SMS."""
        mock_get_s3.return_value = b"raw email bytes"
        mock_parse.return_value = {"body": "some text"}
        mock_db.add_transaction.return_value = None  # validation failure

        handler(_s3_event(), None)

        mock_sms.assert_not_called()
        mock_enricher.enrich.assert_not_called()

    @patch("docker.email_parsing.lambda_function.context_enricher")
    @patch("docker.email_parsing.lambda_function.notification_service.send")
    @patch("docker.email_parsing.lambda_function.transactions_db")
    @patch("docker.email_parsing.lambda_function.parse_email")
    @patch("docker.email_parsing.lambda_function.get_s3_file")
    def test_empty_s3_file_skips_processing(
        self,
        mock_get_s3: MagicMock,
        mock_parse: MagicMock,
        mock_db: MagicMock,
        mock_sms: MagicMock,
        mock_enricher: MagicMock,
    ) -> None:
        """When S3 file content is None/empty, skip processing entirely."""
        mock_get_s3.return_value = None

        handler(_s3_event(), None)

        mock_parse.assert_not_called()
        mock_db.add_transaction.assert_not_called()
        mock_sms.assert_not_called()

    @patch("docker.email_parsing.lambda_function.context_enricher")
    @patch("docker.email_parsing.lambda_function.notification_service.send")
    @patch("docker.email_parsing.lambda_function.transactions_db")
    @patch("docker.email_parsing.lambda_function.parse_email")
    @patch("docker.email_parsing.lambda_function.get_s3_file")
    def test_multiple_s3_records(
        self,
        mock_get_s3: MagicMock,
        mock_parse: MagicMock,
        mock_db: MagicMock,
        mock_sms: MagicMock,
        mock_enricher: MagicMock,
    ) -> None:
        """Handler processes all records in the event."""
        event = {
            "Records": [
                {"s3": {"bucket": {"name": "b"}, "object": {"key": "k1"}}},
                {"s3": {"bucket": {"name": "b"}, "object": {"key": "k2"}}},
            ]
        }
        mock_get_s3.return_value = b"raw"
        mock_parse.return_value = {
            "forwarded_to": "user@example.com",
            "company": "X",
            "amount": 1.0,
            "transaction_type": "purchase",
        }
        mock_db.add_transaction.return_value = "2026.01.15_14.30_test.eml"
        mock_enricher.enrich.return_value = None

        handler(event, None)

        assert mock_get_s3.call_count == 2
        assert mock_parse.call_count == 2
        assert mock_sms.call_count == 2

    @patch("docker.email_parsing.lambda_function.context_enricher")
    @patch("docker.email_parsing.lambda_function.notification_service.send")
    @patch("docker.email_parsing.lambda_function.transactions_db")
    @patch("docker.email_parsing.lambda_function.parse_email")
    @patch("docker.email_parsing.lambda_function.get_s3_file")
    def test_enrichment_called_for_new_transaction(
        self,
        mock_get_s3: MagicMock,
        mock_parse: MagicMock,
        mock_db: MagicMock,
        mock_sms: MagicMock,
        mock_enricher: MagicMock,
    ) -> None:
        """Enrichment should be called for new transactions."""
        mock_get_s3.return_value = b"raw email bytes"
        result = {
            "forwarded_to": "user@example.com",
            "company": "Starbucks",
            "amount": 5.50,
            "transaction_type": "purchase",
        }
        mock_parse.return_value = result
        mock_db.add_transaction.return_value = "2026.01.15_14.30_test.eml"
        mock_enricher.enrich.return_value = {"category_month_total": 50.0}

        handler(_s3_event(), None)

        mock_enricher.enrich.assert_called_once_with(result)

    @patch("docker.email_parsing.lambda_function.context_enricher")
    @patch("docker.email_parsing.lambda_function.notification_service.send")
    @patch("docker.email_parsing.lambda_function.transactions_db")
    @patch("docker.email_parsing.lambda_function.parse_email")
    @patch("docker.email_parsing.lambda_function.get_s3_file")
    def test_update_context_called_on_enrichment_success(
        self,
        mock_get_s3: MagicMock,
        mock_parse: MagicMock,
        mock_db: MagicMock,
        mock_sms: MagicMock,
        mock_enricher: MagicMock,
    ) -> None:
        """update_context should be called when enrichment succeeds."""
        mock_get_s3.return_value = b"raw email bytes"
        mock_parse.return_value = {
            "forwarded_to": "user@example.com",
            "company": "Starbucks",
            "amount": 5.50,
            "transaction_type": "purchase",
        }
        mock_db.add_transaction.return_value = "2026.01.15_14.30_test.eml"
        context = {"category_month_total": 50.0}
        mock_enricher.enrich.return_value = context

        handler(_s3_event(), None)

        mock_db.update_context.assert_called_once_with("user@example.com", "2026.01.15_14.30_test.eml", context)

    @patch("docker.email_parsing.lambda_function.context_enricher")
    @patch("docker.email_parsing.lambda_function.notification_service.send")
    @patch("docker.email_parsing.lambda_function.transactions_db")
    @patch("docker.email_parsing.lambda_function.parse_email")
    @patch("docker.email_parsing.lambda_function.get_s3_file")
    def test_update_context_not_called_when_enrichment_returns_none(
        self,
        mock_get_s3: MagicMock,
        mock_parse: MagicMock,
        mock_db: MagicMock,
        mock_sms: MagicMock,
        mock_enricher: MagicMock,
    ) -> None:
        """update_context should NOT be called when enrichment returns None."""
        mock_get_s3.return_value = b"raw email bytes"
        mock_parse.return_value = {
            "forwarded_to": "user@example.com",
            "company": "Starbucks",
            "amount": 5.50,
            "transaction_type": "purchase",
        }
        mock_db.add_transaction.return_value = "2026.01.15_14.30_test.eml"
        mock_enricher.enrich.return_value = None

        handler(_s3_event(), None)

        mock_db.update_context.assert_not_called()
        # SMS should still be sent even without enrichment
        mock_sms.assert_called_once()

    @patch("docker.email_parsing.lambda_function.context_enricher")
    @patch("docker.email_parsing.lambda_function.notification_service.send")
    @patch("docker.email_parsing.lambda_function.transactions_db")
    @patch("docker.email_parsing.lambda_function.parse_email")
    @patch("docker.email_parsing.lambda_function.get_s3_file")
    def test_category_audit_threaded_to_add_transaction(
        self,
        mock_get_s3: MagicMock,
        mock_parse: MagicMock,
        mock_db: MagicMock,
        _mock_sms: MagicMock,
        mock_enricher: MagicMock,
    ) -> None:
        """When parse_email surfaces _category_audit, it must be passed to add_transaction and stripped."""
        mock_get_s3.return_value = b"raw email bytes"
        audit = {"source": "override_normalized", "matched_rule": "COFFEE SPOT", "confidence": 1.0}
        mock_parse.return_value = {
            "forwarded_to": "user@example.com",
            "company": "COFFEE SPOT AT NEW MALL",
            "amount": 4.50,
            "transaction_type": "purchase",
            "_category_audit": audit,
        }
        mock_db.add_transaction.return_value = "2026.01.15_14.30_test.eml"
        mock_enricher.enrich.return_value = None

        handler(_s3_event(), None)

        _, kwargs = mock_db.add_transaction.call_args
        assert kwargs["category_audit"] == audit
        # The sentinel key must be stripped before the dict is handed to add_transaction.
        passed_result = mock_db.add_transaction.call_args[0][0]
        assert "_category_audit" not in passed_result

    @patch("docker.email_parsing.lambda_function.context_enricher")
    @patch("docker.email_parsing.lambda_function.notification_service.send")
    @patch("docker.email_parsing.lambda_function.transactions_db")
    @patch("docker.email_parsing.lambda_function.parse_email")
    @patch("docker.email_parsing.lambda_function.get_s3_file")
    def test_no_audit_passes_none(
        self,
        mock_get_s3: MagicMock,
        mock_parse: MagicMock,
        mock_db: MagicMock,
        _mock_sms: MagicMock,
        mock_enricher: MagicMock,
    ) -> None:
        """When no audit is produced (OpenAI fallback), add_transaction gets category_audit=None."""
        mock_get_s3.return_value = b"raw email bytes"
        mock_parse.return_value = {
            "forwarded_to": "user@example.com",
            "company": "X",
            "amount": 1.0,
            "transaction_type": "purchase",
        }
        mock_db.add_transaction.return_value = "2026.01.15_14.30_test.eml"
        mock_enricher.enrich.return_value = None

        handler(_s3_event(), None)

        _, kwargs = mock_db.add_transaction.call_args
        assert kwargs["category_audit"] is None


class TestHandlerFailureIsolation:
    """Per-record isolation: a poison record must not abort the batch, and the
    invocation must fail at the end so S3 retry + the DLQ destination see it."""

    @pytest.fixture(autouse=True)
    def _setup_env(self) -> Iterator[None]:
        get_openai_api_key.cache_clear()
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
            patch(
                "docker.email_parsing.lambda_function.get_openai_api_key",
                return_value="test-key",
            ),
        ):
            yield
        get_openai_api_key.cache_clear()

    @patch("docker.email_parsing.lambda_function.context_enricher")
    @patch("docker.email_parsing.lambda_function.notification_service.send")
    @patch("docker.email_parsing.lambda_function.transactions_db")
    @patch("docker.email_parsing.lambda_function.parse_email")
    @patch("docker.email_parsing.lambda_function.get_s3_file")
    def test_poison_record_does_not_block_rest_of_batch(
        self,
        mock_get_s3: MagicMock,
        mock_parse: MagicMock,
        mock_db: MagicMock,
        mock_sms: MagicMock,
        mock_enricher: MagicMock,
    ) -> None:
        event = {
            "Records": [
                {"s3": {"bucket": {"name": "b"}, "object": {"key": "poison"}}},
                {"s3": {"bucket": {"name": "b"}, "object": {"key": "good"}}},
            ]
        }
        mock_get_s3.return_value = b"raw"
        mock_parse.side_effect = [
            ValueError("parser exploded"),
            {
                "forwarded_to": "user@example.com",
                "company": "X",
                "amount": 1.0,
                "transaction_type": "purchase",
            },
        ]
        mock_db.add_transaction.return_value = "2026.01.15_14.30_test.eml"
        mock_enricher.enrich.return_value = None

        with pytest.raises(RuntimeError, match=r"1 of 2 record\(s\) failed.*poison"):
            handler(event, None)

        # The good record was still fully processed.
        mock_db.add_transaction.assert_called_once()
        mock_sms.assert_called_once()

    @patch("docker.email_parsing.lambda_function.context_enricher")
    @patch("docker.email_parsing.lambda_function.notification_service.send")
    @patch("docker.email_parsing.lambda_function.transactions_db")
    @patch("docker.email_parsing.lambda_function.parse_email")
    @patch("docker.email_parsing.lambda_function.get_s3_file")
    def test_s3_fetch_error_fails_the_invocation(
        self,
        mock_get_s3: MagicMock,
        mock_parse: MagicMock,
        mock_db: MagicMock,
        mock_sms: MagicMock,
        mock_enricher: MagicMock,
    ) -> None:
        """A transient S3 error must surface as a failed invocation (retried),
        not a logged no-op that silently drops the email."""
        mock_get_s3.side_effect = ConnectionError("S3 hiccup")

        with pytest.raises(RuntimeError, match=r"1 of 1 record\(s\) failed"):
            handler(_s3_event(), None)

        mock_parse.assert_not_called()
        mock_sms.assert_not_called()


class TestCategorizationSettings:
    """The Lambda's env-var override channel for model + reasoning effort.

    The Lambda ships no `data/config.json`, so `get_ai_client()`'s config path
    is unreachable there; `CATEGORIZATION_MODEL` / `CATEGORIZATION_REASONING_EFFORT`
    are the override channel, resolved through the same shared resolver.
    """

    @pytest.fixture(autouse=True)
    def _setup_env(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
        get_openai_api_key.cache_clear()
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.delenv("CATEGORIZATION_MODEL", raising=False)
        monkeypatch.delenv("CATEGORIZATION_REASONING_EFFORT", raising=False)
        with (
            patch(
                "docker.email_parsing.lambda_function.get_openai_api_key",
                return_value="test-key",
            ),
            # Empty S3 object → the record is skipped and the handler returns
            # after the client has been built, which is all these tests need.
            patch("docker.email_parsing.lambda_function.get_s3_file", return_value=b""),
        ):
            yield
        get_openai_api_key.cache_clear()

    def _run(self) -> MagicMock:
        """Invoke the handler with OpenAIClient mocked; return the mock."""
        with patch("docker.email_parsing.lambda_function.OpenAIClient") as mock_client:
            handler(_s3_event(), None)
        return mock_client

    def test_no_env_uses_shared_defaults(self) -> None:
        mock_client = self._run()
        mock_client.assert_called_once_with(
            model=DEFAULT_OPENAI_CHAT_MODEL,
            api_key="test-key",
            reasoning_effort=DEFAULT_CATEGORIZATION_REASONING_EFFORT,
        )

    def test_both_env_vars_pass_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CATEGORIZATION_MODEL", FOREIGN_MODEL)
        monkeypatch.setenv("CATEGORIZATION_REASONING_EFFORT", "medium")
        mock_client = self._run()
        mock_client.assert_called_once_with(model=FOREIGN_MODEL, api_key="test-key", reasoning_effort="medium")

    def test_blank_env_vars_fall_back_to_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CATEGORIZATION_MODEL", "   ")
        monkeypatch.setenv("CATEGORIZATION_REASONING_EFFORT", "  ")
        mock_client = self._run()
        mock_client.assert_called_once_with(
            model=DEFAULT_OPENAI_CHAT_MODEL,
            api_key="test-key",
            reasoning_effort=DEFAULT_CATEGORIZATION_REASONING_EFFORT,
        )

    def test_model_only_override_drops_the_tuned_effort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A foreign model must not inherit an effort tuned for the default one."""
        monkeypatch.setenv("CATEGORIZATION_MODEL", FOREIGN_MODEL)
        mock_client = self._run()
        mock_client.assert_called_once_with(model=FOREIGN_MODEL, api_key="test-key", reasoning_effort=None)

    def test_effort_only_override_keeps_the_default_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CATEGORIZATION_REASONING_EFFORT", "high")
        mock_client = self._run()
        mock_client.assert_called_once_with(
            model=DEFAULT_OPENAI_CHAT_MODEL, api_key="test-key", reasoning_effort="high"
        )

    def test_invalid_effort_warns_and_falls_back(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A typo in the env map must degrade to the default, never crash ingestion."""
        monkeypatch.setenv("CATEGORIZATION_REASONING_EFFORT", "turbo")
        with caplog.at_level(logging.WARNING):
            mock_client = self._run()
        mock_client.assert_called_once_with(
            model=DEFAULT_OPENAI_CHAT_MODEL,
            api_key="test-key",
            reasoning_effort=DEFAULT_CATEGORIZATION_REASONING_EFFORT,
        )
        assert "turbo" in caplog.text

    def test_settings_are_read_at_invocation_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Env is consulted per invocation, so an env-map update needs no cold start."""
        first = self._run()
        first.assert_called_once_with(
            model=DEFAULT_OPENAI_CHAT_MODEL,
            api_key="test-key",
            reasoning_effort=DEFAULT_CATEGORIZATION_REASONING_EFFORT,
        )
        monkeypatch.setenv("CATEGORIZATION_MODEL", FOREIGN_MODEL)
        second = self._run()
        second.assert_called_once_with(model=FOREIGN_MODEL, api_key="test-key", reasoning_effort=None)

    def test_resolved_settings_are_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """A deploy boot-check greps CloudWatch for this exact prefix."""
        with caplog.at_level(logging.INFO):
            self._run()
        expected = (
            f"Categorization model={DEFAULT_OPENAI_CHAT_MODEL} "
            f"reasoning_effort={DEFAULT_CATEGORIZATION_REASONING_EFFORT}"
        )
        assert expected in caplog.text


# ---------------------------------------------------------------------------
# Import-time partition wiring
# ---------------------------------------------------------------------------


@contextmanager
def _module_with_user_id(user_id: str | None) -> Iterator[Any]:
    """Re-import the handler module with ``USER_ID`` set (or absent).

    The module builds its stores at import time, so the env has to be in place
    before the module body runs — hence the reload. ``patch.dict`` restores the
    ambient environment on exit and the trailing reload rebuilds the module
    against it, so no later test sees a partition from this one.
    """
    module = importlib.import_module("docker.email_parsing.lambda_function")
    with patch.dict(os.environ, {} if user_id is None else {"USER_ID": user_id}):
        if user_id is None:
            os.environ.pop("USER_ID", None)
        importlib.reload(module)
        try:
            yield module
        finally:
            pass
    importlib.reload(module)


class TestParseFailurePartition:
    """Quarantined emails must land where the dashboard reads them.

    ``storage.create_parse_failure_store()`` keys off ``USER#<USER_ID>``; a
    handler that used the "default" fallback wrote quarantined emails into a
    partition no read path enumerates, so "Needs review" stayed empty.
    """

    def test_store_partition_follows_the_user_id_env(self) -> None:
        with _module_with_user_id("alice") as module:
            assert module.parse_failure_store.USER_PK == "USER#alice"

    def test_store_partition_matches_the_budget_service(self) -> None:
        """Both import-time stores resolve the user the same way."""
        with _module_with_user_id("alice") as module:
            assert module.parse_failure_store.USER_PK == module.budget_service.USER_PK

    def test_falls_back_to_default_without_the_env(self) -> None:
        with _module_with_user_id(None) as module:
            assert module.parse_failure_store.USER_PK == "USER#default"
