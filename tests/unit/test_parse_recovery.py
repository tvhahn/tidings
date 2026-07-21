"""Unit tests for the shared parse-failure recovery / quarantine gate.

Covers the Phase 1 relevance truth-table (institution by sender / by body /
classifier True / False / None / no client), the fail-open guarantee on store
errors, and correct ``failure_stage`` selection.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from src.finance.parse_recovery import (
    RecoveryOutcome,
    _has_currency_amount,
    _looks_like_alert,
    downgrade_to_quarantined,
    mark_recovered,
    quarantine_db_invalid,
    recover_or_quarantine,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _email(**overrides: Any) -> dict[str, Any]:
    details: dict[str, Any] = {
        "from_email": "no-reply@accounts.google.com",
        "subject": "Security alert",
        "body": "some unrelated text",
        "date": "01/15/2026 14:30 PST",
        "forwarded_to": "user@example.com",
        "file_name": "imap/2026/01/uid-1.eml",
    }
    details.update(overrides)
    return details


class _RecordingStore:
    """Minimal IParseFailureStore stand-in that records calls.

    ``has_other_recent_failure`` defaults to ``False`` (this is the first
    failure for the institution) so a quarantine with a detected institution
    fires the drift notification; tests override ``other_recent`` to exercise
    the throttle.
    """

    def __init__(self, *, other_recent: bool = False) -> None:
        self.recorded: list[dict[str, Any]] = []
        self.status_calls: list[tuple[str, str, str | None]] = []
        self.other_recent = other_recent
        self.throttle_checks: list[tuple[str, int]] = []

    def record_failure(self, failure: dict[str, Any]) -> str:
        self.recorded.append(failure)
        return "pf_test123"

    def set_status(self, failure_id: str, status: str, recovered_date_file_name: str | None = None) -> bool:
        self.status_calls.append((failure_id, status, recovered_date_file_name))
        return True

    def has_other_recent_failure(self, institution: str, hours: int = 24) -> bool:
        self.throttle_checks.append((institution, hours))
        return self.other_recent


def _classifier_completion(value: str) -> SimpleNamespace:
    """Mock completion whose forced tool call returns true_or_false=value."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    tool_calls=[
                        SimpleNamespace(
                            function=SimpleNamespace(
                                name="detect_if_transaction_alert",
                                arguments=json.dumps({"true_or_false": value}),
                            )
                        )
                    ]
                )
            )
        ]
    )


# ---------------------------------------------------------------------------
# Relevance gate — institution detected
# ---------------------------------------------------------------------------


class TestInstitutionDetected:
    def test_sender_domain_quarantines_extraction_empty(self) -> None:
        """A known sender domain → relevant → quarantined with extraction_empty."""
        store = _RecordingStore()
        outcome = recover_or_quarantine(_email(from_email="alerts@cibc.com"), store, api_client=None)

        assert outcome.status == "quarantined"
        assert outcome.failure_id == "pf_test123"
        assert len(store.recorded) == 1
        rec = store.recorded[0]
        assert rec["detected_institution"] == "CIBC"
        assert rec["failure_stage"] == "extraction_empty"
        # Classifier was not consulted when the institution is known.
        assert rec["alert_classifier_result"] is None

    def test_body_keyword_quarantines_no_parser_match(self) -> None:
        """No sender match but a parser name in the body → relevant, no_parser_match."""
        store = _RecordingStore()
        body = "Your RBC account had activity today."
        outcome = recover_or_quarantine(
            _email(from_email="weird@unknown.example", body=body),
            store,
            api_client=None,
        )

        assert outcome.status == "quarantined"
        rec = store.recorded[0]
        # Institution not detected by *sender*, so it stays None and the stage
        # reflects that no parser matched.
        assert rec["detected_institution"] is None
        assert rec["failure_stage"] == "no_parser_match"


# ---------------------------------------------------------------------------
# Relevance gate — AI classifier
# ---------------------------------------------------------------------------


class TestClassifierGate:
    """Relevance-gate behavior when the AI classifier is consulted.

    The classifier (``email_is_transaction_alert``, which ships subject+body to
    the AI) is reached only when a client is present AND ``ai_extraction_enabled``
    is set — the *same* consent as the extraction fallback (Finding 2). Its
    ``True``/``None`` → relevant, ``False`` → ignored. Extraction is stubbed to
    fail here so the relevance decision is observed on the quarantine path.
    """

    def _enabled(self):
        return patch("src.finance.app_config.get_config", return_value={"ai_extraction_enabled": True})

    def _extraction_fails(self):
        return patch(
            "src.finance.parse_recovery.extract_transaction",
            return_value=(None, "ai_extraction_failed"),
        )

    def test_classifier_true_is_relevant(self) -> None:
        store = _RecordingStore()
        client = MagicMock(name="api_client")
        client.chat.return_value = _classifier_completion("True")

        with self._enabled(), self._extraction_fails():
            outcome = recover_or_quarantine(_email(), store, api_client=client)

        assert outcome.status == "quarantined"
        rec = store.recorded[0]
        assert rec["alert_classifier_result"] is True
        # The classifier was consulted exactly once (extraction is mocked, so
        # the extractor does not re-hit chat()).
        client.chat.assert_called_once()

    def test_classifier_false_ignored_no_record(self) -> None:
        store = _RecordingStore()
        client = MagicMock()
        client.chat.return_value = _classifier_completion("False")

        with self._enabled():
            outcome = recover_or_quarantine(_email(), store, api_client=client)

        assert outcome == RecoveryOutcome("ignored", None, None)
        assert store.recorded == []

    def test_classifier_none_biases_to_capture(self) -> None:
        """Classifier error (None) → treat as relevant and quarantine."""
        store = _RecordingStore()
        client = MagicMock()
        # No tool_calls → email_is_transaction_alert returns None.
        client.chat.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None))])

        with self._enabled(), self._extraction_fails():
            outcome = recover_or_quarantine(_email(), store, api_client=client)

        assert outcome.status == "quarantined"
        rec = store.recorded[0]
        # alert_classifier_result is None because the classifier could not decide.
        assert rec["alert_classifier_result"] is None

    def test_client_present_but_consent_off_skips_classifier(self) -> None:
        """Finding 2: a client is present but ``ai_extraction_enabled`` is off.
        The AI classifier must NOT be consulted (no email body reaches the AI) —
        the deterministic screen decides instead. A ``chat`` that raises on call
        proves it is never invoked; an alert-shaped body is still captured."""
        store = _RecordingStore()
        client = MagicMock(name="api_client")
        client.chat.side_effect = AssertionError("classifier must not be called when consent is off")
        body = "A purchase of $42.00 was made on your card ending in 1234."

        with patch("src.finance.app_config.get_config", return_value={"ai_extraction_enabled": False}):
            outcome = recover_or_quarantine(
                _email(from_email="alerts@totally-unknown-bank.example", body=body),
                store,
                api_client=client,
            )

        assert outcome.status == "quarantined"
        client.chat.assert_not_called()
        rec = store.recorded[0]
        assert rec["failure_stage"] == "no_parser_match"
        assert rec["alert_classifier_result"] is None

    def test_client_present_consent_off_non_alert_ignored(self) -> None:
        """Consent off + a non-alert body → ignored via the deterministic screen,
        still with no AI call."""
        store = _RecordingStore()
        client = MagicMock(name="api_client")
        client.chat.side_effect = AssertionError("classifier must not be called when consent is off")

        with patch("src.finance.app_config.get_config", return_value={"ai_extraction_enabled": False}):
            outcome = recover_or_quarantine(
                _email(from_email="news@unknown.example", body="This week's newsletter, nothing to see."),
                store,
                api_client=client,
            )

        assert outcome == RecoveryOutcome("ignored", None, None)
        client.chat.assert_not_called()
        assert store.recorded == []


# ---------------------------------------------------------------------------
# Relevance gate — no client, no institution
# ---------------------------------------------------------------------------


class TestNoClientGate:
    def test_no_client_no_institution_ignored(self) -> None:
        store = _RecordingStore()
        outcome = recover_or_quarantine(_email(), store, api_client=None)

        assert outcome == RecoveryOutcome("ignored", None, None)
        assert store.recorded == []

    def test_no_client_body_keyword_quarantines(self) -> None:
        store = _RecordingStore()
        outcome = recover_or_quarantine(
            _email(body="Simplii e-Transfer received"),
            store,
            api_client=None,
        )
        assert outcome.status == "quarantined"

    def test_unknown_sender_alert_shaped_body_quarantines(self) -> None:
        """L4 deterministic screen: unknown sender + alert-shaped body (currency
        amount + a high-signal word, no marketing/receipt marker) + no AI client
        → quarantined no_parser_match with alert_classifier_result None. No AI
        call is made."""
        store = _RecordingStore()
        body = "A purchase of $42.00 was charged to your account ending in 1234."
        outcome = recover_or_quarantine(
            _email(from_email="alerts@totally-unknown-bank.example", body=body),
            store,
            api_client=None,
        )
        assert outcome.status == "quarantined"
        assert outcome.failure_id == "pf_test123"
        rec = store.recorded[0]
        assert rec["detected_institution"] is None
        assert rec["failure_stage"] == "no_parser_match"
        assert rec["alert_classifier_result"] is None

    def test_unknown_sender_alert_shaped_does_not_notify(self) -> None:
        """The L4 capture has no detected institution, so drift never fires and
        the throttle is not even consulted."""
        store = _RecordingStore()
        body = "You spent $9.99 on a purchase from your account."
        with patch("src.finance.parse_recovery.notification_service.send_raw") as send_raw:
            outcome = recover_or_quarantine(
                _email(from_email="alerts@unknown.example", body=body),
                store,
                api_client=None,
            )
        assert outcome.status == "quarantined"
        send_raw.assert_not_called()
        assert store.throttle_checks == []

    def test_unknown_sender_newsletter_no_amount_ignored(self) -> None:
        """No $ amount (a newsletter) → ignored, nothing recorded."""
        store = _RecordingStore()
        body = "This month's newsletter: your purchase habits and account tips."
        outcome = recover_or_quarantine(
            _email(from_email="news@unknown.example", body=body),
            store,
            api_client=None,
        )
        assert outcome == RecoveryOutcome("ignored", None, None)
        assert store.recorded == []

    def test_unknown_sender_amount_single_keyword_ignored(self) -> None:
        """A receipt: currency amount + a high-signal word ("purchase") but a
        receipt marker ("invoice" / "thank you for your purchase") vetoes it, so
        it stays out of the permanent quarantine backlog → ignored."""
        store = _RecordingStore()
        body = "Your invoice total is $120.00. Thank you for your purchase."
        outcome = recover_or_quarantine(
            _email(from_email="billing@unknown.example", body=body),
            store,
            api_client=None,
        )
        assert outcome == RecoveryOutcome("ignored", None, None)
        assert store.recorded == []


class TestHasCurrencyAmount:
    """Currency detection (Finding 3): $/€/£ and ISO codes, symbol before or
    after the amount, dot- or comma-decimal. These bare tokens are the exact
    formats the old ``$``-only regex silently dropped."""

    def test_dollar_before_amount(self) -> None:
        assert _has_currency_amount("$42.00") is True

    def test_dollar_thousands_separator(self) -> None:
        assert _has_currency_amount("$1,250.00") is True

    def test_euro_symbol(self) -> None:
        assert _has_currency_amount("€42.00") is True

    def test_pound_symbol(self) -> None:
        # Verified miss from Finding 3.
        assert _has_currency_amount("£12.34") is True

    def test_iso_code_before_amount(self) -> None:
        # Verified miss from Finding 3.
        assert _has_currency_amount("EUR 42.00") is True

    def test_iso_code_after_amount(self) -> None:
        assert _has_currency_amount("42.00 CAD") is True

    def test_amount_before_symbol_comma_decimal(self) -> None:
        # Verified miss from Finding 3: amount before $, French comma decimal.
        assert _has_currency_amount("12,34 $") is True

    def test_bare_number_no_marker_false(self) -> None:
        assert _has_currency_amount("total 42.00 due") is False

    def test_empty_false(self) -> None:
        assert _has_currency_amount("") is False


class TestLooksLikeAlert:
    """Pure unit cases for the redesigned L4 deterministic screen (Findings 3+4).

    Captures iff: a currency amount ($/€/£/ISO, symbol either side, dot- or
    comma-decimal) AND a high-signal action/instrument word (purchase,
    withdrawal, e-transfer, card ending, débit, achat, retrait, virement, …)
    AND no marketing/receipt marker (/month, upgrade, invoice, thank you for
    your purchase, …). Recall is favoured (one high-signal word suffices); the
    keyword floor + negative markers are what keep receipts and subscription
    spam out of the permanent quarantine backlog.
    """

    # --- true positives: realistic alerts, English + French, $/€/£ ----------

    def test_mbna_shaped_purchase(self) -> None:
        assert _looks_like_alert("A purchase of $87.45 was made on your Mastercard card ending in 1234.") is True

    def test_rbc_shaped_withdrawal_thousands(self) -> None:
        assert _looks_like_alert("A withdrawal of $417,124.99 was debited from your bank account.") is True

    def test_simplii_shaped_etransfer_cad(self) -> None:
        assert _looks_like_alert("The $250.00 (CAD) you sent has been deposited via Interac e-Transfer.") is True

    def test_case_insensitive_high_signal(self) -> None:
        assert _looks_like_alert("PURCHASE of $5 on your CARD ENDING 0001.") is True

    def test_french_achat_comma_decimal_dollar_after(self) -> None:
        # Verified miss from Finding 3 — must now be captured.
        assert _looks_like_alert("Achat de 12,34 $ chez AMAZON") is True

    def test_french_retrait_euro_code(self) -> None:
        assert _looks_like_alert("Un retrait de EUR 42.00 a été effectué sur votre compte.") is True

    def test_gbp_purchase(self) -> None:
        # Embeds the verified £12.34 miss in a realistic alert.
        assert _looks_like_alert("A purchase of £12.34 was made on your card ending in 4321.") is True

    # --- false positives: receipts & subscription/marketing (Finding 4) -----

    def test_receipt_payment_charged_to_account_on_file_false(self) -> None:
        """Verified false positive: a card-on-file receipt with only generic
        words (payment/charged/account) and no high-signal term."""
        assert _looks_like_alert("Your payment of $16.49 was charged to the account on file.") is False

    def test_subscription_upgrade_monthly_false(self) -> None:
        """Verified false positive: subscription/marketing markers veto it."""
        assert _looks_like_alert("Upgrade your account for $9.99/month — payment is processed monthly.") is False

    def test_subscription_with_high_signal_still_vetoed(self) -> None:
        """Even with a high-signal word, marketing markers keep it out."""
        assert _looks_like_alert("Your monthly subscription purchase of $9.99 renews soon.") is False

    def test_receipt_invoice_total_false(self) -> None:
        assert _looks_like_alert("Your invoice total is $120.00. Thank you for your purchase.") is False

    def test_store_receipt_thanks_false(self) -> None:
        assert _looks_like_alert("Your total is $120.00. Thanks for your purchase.") is False

    # --- structural negatives ----------------------------------------------

    def test_generic_words_no_high_signal_false(self) -> None:
        """Currency amount + only generic words (payment/account) → dropped."""
        assert _looks_like_alert("A payment of $42.00 was applied to your account.") is False

    def test_high_signal_but_no_amount_false(self) -> None:
        assert _looks_like_alert("Your purchase and account summary is ready.") is False

    def test_bare_number_without_currency_marker_false(self) -> None:
        assert _looks_like_alert("A purchase of 42.00 was made on your account.") is False

    def test_empty_body_false(self) -> None:
        assert _looks_like_alert("") is False


# ---------------------------------------------------------------------------
# Fail-open guarantees
# ---------------------------------------------------------------------------


class TestFailOpen:
    def test_none_store_ignored(self) -> None:
        outcome = recover_or_quarantine(_email(from_email="alerts@cibc.com"), None, api_client=None)
        assert outcome == RecoveryOutcome("ignored", None, None)

    def test_store_raises_returns_ignored(self) -> None:
        """A store that raises must not propagate — the gate is fail-open."""
        store = MagicMock()
        store.record_failure.side_effect = RuntimeError("db exploded")

        # institution detected by sender → would normally quarantine
        outcome = recover_or_quarantine(_email(from_email="alerts@cibc.com"), store, api_client=None)

        assert outcome == RecoveryOutcome("ignored", None, None)

    def test_classifier_raises_returns_ignored(self) -> None:
        """email_is_transaction_alert does not guard the chat() call itself, so a
        raising client propagates into our fail-open wrapper → ignored, no raise.
        The classifier is only reached with the extraction consent on."""
        store = _RecordingStore()
        client = MagicMock()
        client.chat.side_effect = RuntimeError("api down")

        with patch("src.finance.app_config.get_config", return_value={"ai_extraction_enabled": True}):
            outcome = recover_or_quarantine(_email(), store, api_client=client)
        assert outcome == RecoveryOutcome("ignored", None, None)
        assert store.recorded == []


# ---------------------------------------------------------------------------
# Phase 2 — AI extraction fallback (recovery wiring, §2.3)
# ---------------------------------------------------------------------------


def _enable_extraction():
    """Patch the extraction consent ON so the extraction branch runs.

    The gate keys off ``ai_extraction_enabled`` — a consent distinct from
    ``ai_categorization_enabled`` (see L1). Categorization is left off here to
    prove the extraction branch no longer reads the categorization flag.
    """
    return patch(
        "src.finance.app_config.get_config",
        return_value={"ai_categorization_enabled": False, "ai_extraction_enabled": True},
    )


def _disable_extraction():
    """Patch the extraction consent OFF so extraction is skipped entirely.

    Categorization is left on to prove the gate ignores it.
    """
    return patch(
        "src.finance.app_config.get_config",
        return_value={"ai_categorization_enabled": True, "ai_extraction_enabled": False},
    )


class TestExtractionFallback:
    def test_extraction_success_recovers(self) -> None:
        """Extraction success → recovered outcome with both audits on the merged
        result and the failure row pre-marked recovered with the Phase 1 stage."""
        store = _RecordingStore()
        client = MagicMock()
        client.model = "gpt-test"
        # A real chat() is never reached: extract_transaction + categorize are mocked.

        details = _email(from_email="alerts@cibc.com", body="You spent $5.50 at Starbucks")

        with (
            _enable_extraction(),
            patch(
                "src.finance.parse_recovery.extract_transaction",
                return_value=(
                    {
                        "amount": 5.5,
                        "company": "Starbucks",
                        "transaction_type": "purchase",
                        "institution": "CIBC",
                    },
                    None,
                ),
            ) as mock_extract,
            patch(
                "src.finance.parse_recovery.categorize_transactions",
                side_effect=lambda _client, txn: (
                    txn.__setitem__("_category_audit", {"source": "ai_fallback"}) or "coffee shops"
                ),
            ),
        ):
            outcome = recover_or_quarantine(details, store, api_client=client)

        assert outcome.status == "recovered"
        assert outcome.failure_id == "pf_test123"
        merged = outcome.result
        assert merged is not None
        # Merged transaction fields.
        assert merged["amount"] == 5.5
        assert merged["company"] == "Starbucks"
        assert merged["transaction_type"] == "purchase"
        assert merged["institution"] == "CIBC"
        assert merged["category"] == "coffee shops"
        # Both provenance keys ride on the merged result.
        assert merged["_category_audit"] == {"source": "ai_fallback"}
        assert merged["_extraction_audit"]["method"] == "ai_fallback"
        assert merged["_extraction_audit"]["model"] == "gpt-test"
        # The caller's dict was not mutated with transaction fields.
        assert "amount" not in details
        # extract_transaction saw the detected institution.
        assert mock_extract.call_args.args[1]["detected_institution"] == "CIBC"
        # Failure row pre-marked recovered with the Phase 1 stage.
        assert len(store.recorded) == 1
        rec = store.recorded[0]
        assert rec["status"] == "recovered"
        assert rec["failure_stage"] == "extraction_empty"
        assert rec["detected_institution"] == "CIBC"

    def test_extraction_skipped_when_ai_disabled(self) -> None:
        """ai_extraction_enabled False (even with categorization ON) → no chat
        call, straight to quarantine. Proves the gate reads the extraction
        consent, not the categorization one."""
        store = _RecordingStore()
        client = MagicMock(name="api_client")

        details = _email(from_email="alerts@cibc.com")

        with _disable_extraction():
            outcome = recover_or_quarantine(details, store, api_client=client)

        assert outcome.status == "quarantined"
        # Extraction never ran — no AI call of any kind.
        client.chat.assert_not_called()
        rec = store.recorded[0]
        assert rec["failure_stage"] == "extraction_empty"
        assert "status" not in rec

    def test_extraction_ignores_categorization_flag_matrix(self) -> None:
        """The gate keys strictly off ai_extraction_enabled across the
        (categorization on/off) x (extraction on/off) matrix, with a client
        present. Only extraction=True runs the extractor."""
        matrix = [
            ({"ai_categorization_enabled": True, "ai_extraction_enabled": False}, False),
            ({"ai_categorization_enabled": False, "ai_extraction_enabled": True}, True),
            ({"ai_categorization_enabled": True, "ai_extraction_enabled": True}, True),
            ({"ai_categorization_enabled": False, "ai_extraction_enabled": False}, False),
        ]
        for config, should_extract in matrix:
            store = _RecordingStore()
            client = MagicMock()
            client.model = "gpt-test"
            details = _email(from_email="alerts@cibc.com", body="You spent $5.50 at Starbucks")
            with (
                patch("src.finance.app_config.get_config", return_value=config),
                patch(
                    "src.finance.parse_recovery.extract_transaction",
                    return_value=(
                        {
                            "amount": 5.5,
                            "company": "Starbucks",
                            "transaction_type": "purchase",
                            "institution": "CIBC",
                        },
                        None,
                    ),
                ) as mock_extract,
                patch("src.finance.parse_recovery.categorize_transactions", return_value="coffee shops"),
            ):
                outcome = recover_or_quarantine(details, store, api_client=client)
            if should_extract:
                assert mock_extract.called, config
                assert outcome.status == "recovered", config
            else:
                assert not mock_extract.called, config
                assert outcome.status == "quarantined", config

    def test_extraction_gate_off_with_no_client(self) -> None:
        """Extraction on but no client → no extraction attempt (client is a
        hard precondition), quarantined on the Phase 1 stage."""
        store = _RecordingStore()
        with (
            _enable_extraction(),
            patch("src.finance.parse_recovery.extract_transaction") as mock_extract,
        ):
            outcome = recover_or_quarantine(_email(from_email="alerts@cibc.com"), store, api_client=None)
        assert outcome.status == "quarantined"
        mock_extract.assert_not_called()
        assert store.recorded[0]["failure_stage"] == "extraction_empty"

    def test_validation_failure_quarantines_with_stage(self) -> None:
        """Extractor signalling ai_validation_failed → quarantined with that stage."""
        store = _RecordingStore()
        client = MagicMock()

        with (
            _enable_extraction(),
            patch(
                "src.finance.parse_recovery.extract_transaction",
                return_value=(None, "ai_validation_failed"),
            ),
        ):
            outcome = recover_or_quarantine(_email(from_email="alerts@cibc.com"), store, api_client=client)

        assert outcome.status == "quarantined"
        rec = store.recorded[0]
        assert rec["failure_stage"] == "ai_validation_failed"
        # Not pre-marked recovered.
        assert "status" not in rec

    def test_extraction_error_quarantines_with_stage(self) -> None:
        """Extractor signalling ai_extraction_failed → quarantined with that stage."""
        store = _RecordingStore()
        client = MagicMock()

        with (
            _enable_extraction(),
            patch(
                "src.finance.parse_recovery.extract_transaction",
                return_value=(None, "ai_extraction_failed"),
            ),
        ):
            outcome = recover_or_quarantine(_email(from_email="alerts@cibc.com"), store, api_client=client)

        assert outcome.status == "quarantined"
        assert store.recorded[0]["failure_stage"] == "ai_extraction_failed"


# ---------------------------------------------------------------------------
# Phase 3 — drift notification (§3.2)
# ---------------------------------------------------------------------------


class TestDriftNotification:
    """A quarantine with a detected institution emits one throttled send_raw —
    the first per institution per 24h. Recovered and unknown-sender captures
    never notify here.
    """

    def test_first_quarantine_for_institution_notifies(self) -> None:
        store = _RecordingStore(other_recent=False)
        with patch("src.finance.parse_recovery.notification_service.send_raw") as send_raw:
            outcome = recover_or_quarantine(_email(from_email="alerts@cibc.com"), store, api_client=None)

        assert outcome.status == "quarantined"
        # Throttle was consulted after the row was written.
        assert store.throttle_checks == [("CIBC", 24)]
        send_raw.assert_called_once_with(
            title="Tidings",
            body="CIBC email couldn't be parsed — captured for review",
        )

    def test_second_failure_within_24h_does_not_notify(self) -> None:
        """has_other_recent_failure True (count > 1) → throttled, no notification."""
        store = _RecordingStore(other_recent=True)
        with patch("src.finance.parse_recovery.notification_service.send_raw") as send_raw:
            outcome = recover_or_quarantine(_email(from_email="alerts@cibc.com"), store, api_client=None)

        assert outcome.status == "quarantined"
        send_raw.assert_not_called()

    def test_no_institution_does_not_notify(self) -> None:
        """A capture with no detected institution is not actionable drift."""
        store = _RecordingStore()
        # Body keyword → relevant + quarantined, but institution stays None.
        details = _email(from_email="weird@unknown.example", body="Your RBC account had activity today.")
        with patch("src.finance.parse_recovery.notification_service.send_raw") as send_raw:
            outcome = recover_or_quarantine(details, store, api_client=None)

        assert outcome.status == "quarantined"
        assert store.recorded[0]["detected_institution"] is None
        send_raw.assert_not_called()
        # Throttle is not even consulted without an institution.
        assert store.throttle_checks == []

    def test_recovered_outcome_does_not_notify(self) -> None:
        """Recovered rows notify as transactions, not via the drift path."""
        store = _RecordingStore()
        client = MagicMock()
        client.model = "gpt-test"
        details = _email(from_email="alerts@cibc.com", body="You spent $5.50 at Starbucks")

        with (
            _enable_extraction(),
            patch(
                "src.finance.parse_recovery.extract_transaction",
                return_value=(
                    {"amount": 5.5, "company": "Starbucks", "transaction_type": "purchase", "institution": "CIBC"},
                    None,
                ),
            ),
            patch("src.finance.parse_recovery.categorize_transactions", return_value="coffee shops"),
            patch("src.finance.parse_recovery.notification_service.send_raw") as send_raw,
        ):
            outcome = recover_or_quarantine(details, store, api_client=client)

        assert outcome.status == "recovered"
        send_raw.assert_not_called()
        assert store.throttle_checks == []

    def test_notification_error_does_not_break_quarantine(self) -> None:
        """send_raw is fail-open, but even a throttle-read error must not
        propagate — the quarantine outcome stands."""
        store = MagicMock()
        store.record_failure.return_value = "pf_test123"
        store.has_other_recent_failure.side_effect = RuntimeError("throttle read failed")

        outcome = recover_or_quarantine(_email(from_email="alerts@cibc.com"), store, api_client=None)

        assert outcome.status == "quarantined"
        assert outcome.failure_id == "pf_test123"


# ---------------------------------------------------------------------------
# downgrade_to_quarantined (recovered → quarantined when the DB write fails)
# ---------------------------------------------------------------------------


class TestDowngradeToQuarantined:
    def test_sets_status_quarantined(self) -> None:
        store = _RecordingStore()
        downgrade_to_quarantined(store, "pf_abc")
        assert store.status_calls == [("pf_abc", "quarantined", None)]

    def test_noop_without_store_or_id(self) -> None:
        downgrade_to_quarantined(None, "pf_abc")
        store = _RecordingStore()
        downgrade_to_quarantined(store, None)
        assert store.status_calls == []

    def test_fail_open_on_store_error(self) -> None:
        store = MagicMock()
        store.set_status.side_effect = RuntimeError("boom")
        # Must not raise.
        downgrade_to_quarantined(store, "pf_abc")


# ---------------------------------------------------------------------------
# quarantine_db_invalid
# ---------------------------------------------------------------------------


class TestQuarantineDbInvalid:
    def test_records_db_validation_failed(self) -> None:
        store = _RecordingStore()
        details = _email(institution="RBC", company="Starbucks", amount=5.5)

        failure_id = quarantine_db_invalid(store, details, api_client=None)

        assert failure_id == "pf_test123"
        rec = store.recorded[0]
        assert rec["failure_stage"] == "db_validation_failed"
        assert rec["detected_institution"] == "RBC"

    def test_none_store_returns_none(self) -> None:
        assert quarantine_db_invalid(None, _email(), api_client=None) is None

    def test_fail_open_on_store_error(self) -> None:
        store = MagicMock()
        store.record_failure.side_effect = RuntimeError("boom")
        assert quarantine_db_invalid(store, _email(institution="RBC"), api_client=None) is None


# ---------------------------------------------------------------------------
# mark_recovered
# ---------------------------------------------------------------------------


class TestMarkRecovered:
    def test_sets_status_recovered(self) -> None:
        store = _RecordingStore()
        mark_recovered(store, "pf_abc", "2026.01.15_14.30_uid.eml")
        assert store.status_calls == [("pf_abc", "recovered", "2026.01.15_14.30_uid.eml")]

    def test_noop_without_store_or_id(self) -> None:
        # Neither should raise.
        mark_recovered(None, "pf_abc", "dfn")
        store = _RecordingStore()
        mark_recovered(store, None, "dfn")
        assert store.status_calls == []

    def test_fail_open_on_store_error(self) -> None:
        store = MagicMock()
        store.set_status.side_effect = RuntimeError("boom")
        # Must not raise.
        mark_recovered(store, "pf_abc", "dfn")
