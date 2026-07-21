"""Tests for Lambda handler decision branches.

Tests mock at the function level (parse_email, add_transaction, send_sms)
rather than at the AWS SDK level, to verify the handler's orchestration logic.
"""

import os
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from docker.email_parsing.lambda_function import handler
from src.finance.secrets import get_openai_api_key


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
