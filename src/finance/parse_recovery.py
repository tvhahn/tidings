"""Shared parse-failure recovery / quarantine logic.

One module that all three ingestion transports (IMAP poller, AWS Lambda, the
``upload-eml`` API) share so the "what do we do with an email no parser could
read?" decision lives in exactly one place.

Phase 1 (this module's current scope) implements *capture*: an email that the
deterministic parsers could not turn into a transaction is either

* **quarantined** — persisted to the dead-letter store with the full
  ``email_details`` dict so it can be retried later, or
* **ignored** — dropped as today, because it is almost certainly not a
  transaction alert (a newsletter, a security notice, …).

Phase 2 inserts a constrained-LLM extraction attempt between the relevance
gate and the quarantine write, producing the third outcome — **recovered** —
where the transaction is reconstructed and flows into the normal add path. The
entry points branch on ``recovered`` and pop the ``_extraction_audit`` /
``_category_audit`` provenance off the merged result before storing it.

**Fail-open contract.** ``recover_or_quarantine`` and ``quarantine_db_invalid``
never raise: a bug in quarantine handling must never break ingestion. Any
internal error is logged via ``logger.exception`` and degrades to ``ignored`` /
``None`` (the pre-quarantine behaviour) — mirroring ``notification_service.send``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.finance import notification_service
from src.finance.categorizer import categorize_transactions, email_is_transaction_alert
from src.finance.category_audit import build_extraction_audit
from src.finance.email_pipeline import PARSER_KEYS, _detect_institution_by_sender
from src.finance.extractor import extract_transaction

if TYPE_CHECKING:
    from src.finance.ai_client import AIProviderClient
    from src.finance.protocols import IParseFailureStore

logger = logging.getLogger(__name__)

# Deterministic relevance screen (L4): when we cannot ask the AI classifier
# (no client, or the extraction consent is off) we decide whether an unparsed
# email looks like a bank/credit-card transaction alert using only the text.
#
# Locale: the home market is Canada, so the screen accepts English *and* French
# alerts and the three currencies a Canadian sees ($, €, £) plus the ISO codes
# (EUR/CAD/USD/GBP). The repo guide (add-a-parser.md) is explicit: "don't assume
# English in shared helpers." A $-only, English-only screen silently dropped the
# exact class this feature exists to capture.

# An amount token: thousands-grouped (1,250.00) OR a plain integer/decimal with
# EITHER a dot or comma decimal separator (12.34 / 12,34) — French uses a comma.
_AMOUNT = r"\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+(?:[.,]\d{1,2})?"
# A currency marker: symbol ($ € £) or ISO code (EUR/CAD/USD/GBP), adjacent to
# an amount on EITHER side ("$42.00", "EUR 42.00", "12,34 $", "42.00 CAD").
_CURRENCY_MARKER = r"[$€£]|\b(?:EUR|CAD|USD|GBP)\b"
_CURRENCY_AMOUNT_RE = re.compile(
    rf"(?:{_CURRENCY_MARKER})\s?(?:{_AMOUNT})|(?:{_AMOUNT})\s?(?:{_CURRENCY_MARKER})",
    re.IGNORECASE,
)

# High-signal keywords: the *action/instrument* words that mark a transaction
# alert as opposed to a receipt or newsletter. At least one must be present —
# this is what keeps ordinary "payment of $X charged to your account" receipts,
# which carry only generic words, out of the permanent quarantine backlog.
_HIGH_SIGNAL_KEYWORDS = (
    # English
    "purchase",
    "withdrawal",
    "withdrawn",
    "withdrew",
    "deposit",
    "spent",
    "e-transfer",
    "etransfer",
    "interac",
    "card ending",
    "debited",
    "credited",
    # French-Canadian keywords
    "achat",
    "retrait",
    "dépôt",
    "depot",
    "virement",
    "débit",
    "carte",
)

# Negative markers: subscription / marketing / receipt language. Their presence
# vetoes capture even when an amount and a high-signal word are present — this
# is how "$9.99/month, upgrade your account" and "invoice total … thank you for
# your purchase" stay out.
_NEGATIVE_MARKERS = (
    "/month",
    "/mo",
    "per month",
    "monthly",
    "/year",
    "/yr",
    "subscription",
    "subscribe",
    "unsubscribe",
    "upgrade",
    "free trial",
    "renew",
    "newsletter",
    "invoice",
    "your total",
    "thank you for your purchase",
    "thanks for your purchase",
    "on file",
)


def _has_currency_amount(body: str) -> bool:
    """Whether the body carries a currency amount ($/€/£/EUR/CAD/USD/GBP).

    Pure. Accepts the symbol before or after the amount and both dot- and
    comma-decimal notation, so French and non-``$`` alerts are detected.
    """
    return bool(_CURRENCY_AMOUNT_RE.search(body))


def _looks_like_alert(body: str) -> bool:
    """Deterministic screen for an unknown-bank transaction alert.

    Pure and case-insensitive. Used when the AI classifier is unavailable (no
    client, or the ``ai_extraction_enabled`` consent is off) to decide between
    capturing an unparseable email for review and dropping it.

    Captures iff the body has **all three**:

    1. a currency amount (``$`` ``€`` ``£`` or an ISO code, symbol before or
       after the number, dot- or comma-decimal — English *and* French / EUR /
       GBP alerts qualify);
    2. at least one high-signal action/instrument word (purchase, withdrawal,
       e-transfer, card ending, débit, achat, retrait, virement, …); and
    3. no subscription / marketing / receipt marker (``/month``, ``upgrade``,
       ``invoice``, ``thank you for your purchase``, …).

    Trade-off: the repo's bias is capture-over-loss, so recall is favoured — a
    single high-signal word is enough and generic receipts are only excluded via
    the negative markers, not by demanding a keyword quorum. Requirement (2) is
    the deliberate precision floor: a receipt carrying only generic words
    ("payment … charged to your account") is dropped rather than quarantined
    forever (deterministic retry can never clear it). A genuinely context-free
    amount ("EUR 42.00" with no surrounding words) is likewise dropped; the
    currency-format fix is exercised directly via ``_has_currency_amount``.
    """
    if not _has_currency_amount(body):
        return False
    lowered = body.lower()
    if any(marker in lowered for marker in _NEGATIVE_MARKERS):
        return False
    return any(keyword in lowered for keyword in _HIGH_SIGNAL_KEYWORDS)


@dataclass(frozen=True)
class RecoveryOutcome:
    """Result of running an unparsed email through the recovery gate.

    ``status`` is one of ``"recovered"`` | ``"quarantined"`` | ``"ignored"``.
    ``result`` carries the enriched ``email_details`` when recovered (Phase 2);
    it is ``None`` for quarantine/ignore. ``failure_id`` is the dead-letter row
    id when one was written, else ``None``.
    """

    status: str
    result: dict[str, Any] | None
    failure_id: str | None


def _body_mentions_parser(body: str) -> bool:
    """Whether any known institution name appears verbatim in the email body."""
    return any(key in body for key in PARSER_KEYS)


def _classifier_history(email_details: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the message history for ``email_is_transaction_alert``.

    Matches ``categorizer.py``'s message style: a system message giving the
    classifier its role and a user message carrying the subject + body.
    """
    subject = email_details.get("subject") or ""
    body = email_details.get("body") or ""
    return [
        {
            "role": "system",
            "content": (
                "You are an expert at deciding whether an email is a bank or "
                "credit-card transaction alert (a notice of a purchase, "
                "withdrawal, e-transfer, or deposit) as opposed to a "
                "newsletter, statement summary, security notice, or other "
                "non-transaction message."
            ),
        },
        {
            "role": "user",
            "content": f"Subject: {subject}\n\n{body}",
        },
    ]


def _attempt_extraction(
    email_details: dict[str, Any],
    institution: str | None,
    api_client: AIProviderClient,
) -> tuple[dict[str, Any] | None, str | None]:
    """Run the AI extraction fallback and, on success, build the merged result.

    Returns ``(merged, None)`` when the extraction recovered a transaction —
    ``merged`` is a *copy* of ``email_details`` with ``amount`` / ``company`` /
    ``transaction_type`` / ``institution`` filled in, a ``category`` from
    ``categorize_transactions`` (carrying its ``_category_audit``), and an
    ``_extraction_audit`` provenance stamp. Returns ``(None, stage)`` on
    extraction or validation failure, where ``stage`` is the extractor's
    ``ai_extraction_failed`` / ``ai_validation_failed``.

    ``extract_transaction`` reads ``detected_institution`` off the email dict,
    so we hand it a copy carrying the institution we detected in the relevance
    gate rather than mutating the caller's dict.
    """
    extract_input = dict(email_details)
    if institution is not None:
        extract_input["detected_institution"] = institution

    result, stage = extract_transaction(api_client, extract_input)
    if result is None:
        return None, stage

    merged = dict(email_details)
    merged["amount"] = result["amount"]
    merged["company"] = result["company"]
    merged["transaction_type"] = result["transaction_type"]
    merged["institution"] = result["institution"]

    # Categorize exactly as ``parse_email_body`` does: the audit lands on the
    # small transaction dict we pass in, so copy it onto the merged result.
    transaction = {"amount": result["amount"], "company": result["company"]}
    category = categorize_transactions(api_client, transaction)
    merged["category"] = category
    if "_category_audit" in transaction:
        merged["_category_audit"] = transaction["_category_audit"]

    merged["_extraction_audit"] = build_extraction_audit(getattr(api_client, "model", None))
    return merged, None


def _notify_drift(store: IParseFailureStore, institution: str | None) -> None:
    """Send a throttled drift notification for a fresh quarantine.

    Fires once per institution per 24h: only when an institution was detected
    (an unknown-sender capture is not actionable drift) and this is the *first*
    quarantined failure for that institution in the window.

    ``has_other_recent_failure`` uses count > 1 semantics, so it must be called
    *after* the row is written — by the time we reach here the just-recorded
    row is already in the store. ``send_raw`` is itself fail-open, but the whole
    check is wrapped so a notification (or throttle-read) error can never break
    quarantine.
    """
    if not institution:
        return
    try:
        if store.has_other_recent_failure(institution, hours=24):
            return
        notification_service.send_raw(
            title="Tidings",
            body=f"{institution} email couldn't be parsed — captured for review",
        )
    except Exception:
        logger.exception("drift notification failed for institution=%s (fail-open)", institution)


def recover_or_quarantine(
    email_details: dict[str, Any],
    store: IParseFailureStore | None,
    api_client: AIProviderClient | None,
) -> RecoveryOutcome:
    """Decide what to do with an email the parsers could not read.

    Relevance gate:

    1. If ``_detect_institution_by_sender`` matches the sender domain, or a
       known parser name appears in the body, the email is *relevant* and we
       capture it (``alert_classifier_result`` stays ``None`` — the AI gate was
       not consulted).
    2. Otherwise, if an ``api_client`` is available **and** ``ai_extraction_
       enabled`` is set, ask ``email_is_transaction_alert`` (which sends the
       subject+body to the AI). ``True`` → relevant; ``False`` → ``ignored``
       (drop, as today); ``None`` (classifier error) → treat as relevant,
       biasing toward capture rather than silent loss. The classifier is gated
       on the *same* extraction consent as the fallback below: an opted-out
       user's email bodies never reach the AI, even for the yes/no relevance
       question.
    3. Otherwise (no client, or a client but the extraction consent is off) we
       do not call the AI at all and fall back to the deterministic relevance
       screen (``_looks_like_alert``): capture only when the body carries a
       currency amount, a high-signal alert word, and no marketing/receipt
       marker, else ``ignored``. This captures an unknown bank's alerts —
       English or French, ``$``/``€``/``£`` — for review without an AI call,
       while keeping newsletters, subscriptions, and receipts out.

    Extraction fallback (Phase 2): once an email is deemed relevant, if an
    ``api_client`` is present **and** ``ai_extraction_enabled`` is set (a consent
    distinct from categorization — a user may keep AI categories on while opting
    out of sending unparseable bodies to the AI, or vice versa), attempt a
    constrained-LLM extraction:

    * Success → the failure row is recorded immediately with ``status=
      "recovered"`` (its ``failure_stage`` is the Phase 1 stage — what *would*
      have been quarantined), and ``RecoveryOutcome("recovered", merged,
      failure_id)`` is returned so the caller can store the reconstructed
      transaction and ``mark_recovered`` it.
    * Failure → quarantine, but with the extractor's stage
      (``ai_extraction_failed`` / ``ai_validation_failed``) instead of the
      Phase 1 stage.

    When AI is disabled / no client, extraction is skipped entirely (no ``chat``
    call) and the email goes straight to quarantine with the Phase 1 stage.

    Relevant-and-quarantined → ``RecoveryOutcome("quarantined", None,
    failure_id)``. The Phase 1 ``failure_stage`` is ``"extraction_empty"`` when
    an institution was detected (a parser matched but produced no fields —
    template drift, the high-signal case) and ``"no_parser_match"`` otherwise.

    Drift signal (Phase 3): a quarantine with a *detected institution* emits one
    throttled ``send_raw`` notification — the first such failure per institution
    per 24h (recovered rows notify as transactions instead, and unknown-sender
    captures are not actionable drift, so neither notifies here).

    Fail-open: ``store is None`` or any internal error logs and returns
    ``ignored`` — quarantine must never break ingestion.
    """
    try:
        if store is None:
            logger.warning("recover_or_quarantine called with no store; ignoring email")
            return RecoveryOutcome("ignored", None, None)

        from_email = email_details.get("from_email") or ""
        body = email_details.get("body") or ""

        # The AI extraction consent gates *every* AI call in this gate — both the
        # relevance classifier below and the extraction fallback later. Only read
        # config when a client exists (keeps the no-client path side-effect free).
        ai_enabled = False
        if api_client is not None:
            from src.finance.app_config import get_config

            ai_enabled = bool(get_config().get("ai_extraction_enabled", False))
        use_ai = api_client is not None and ai_enabled

        institution = _detect_institution_by_sender(from_email)
        classifier_result: bool | None = None

        if institution is not None:
            relevant = True
        elif _body_mentions_parser(body):
            # A parser name in the body is as strong a signal as a sender match.
            relevant = True
        elif use_ai:
            # A client AND the extraction consent: ask the AI classifier (it
            # sends subject+body to the provider). Gated on ai_extraction_enabled
            # so an opted-out user's email bodies never reach the AI.
            classifier_result = email_is_transaction_alert(api_client, _classifier_history(email_details))
            if classifier_result is False:
                return RecoveryOutcome("ignored", None, None)
            # True or None (classifier error) → relevant, biasing toward capture.
            relevant = True
        else:
            # No AI available (no client, or the extraction consent is off): fall
            # back to the deterministic relevance screen (L4) — no AI call is
            # made. Capture only when the body looks like a transaction alert;
            # otherwise drop it as today.
            if _looks_like_alert(body):
                relevant = True
            else:
                return RecoveryOutcome("ignored", None, None)

        if not relevant:  # pragma: no cover - defensive; every branch above decided
            return RecoveryOutcome("ignored", None, None)

        # Phase 1 stage — what we would quarantine as if extraction never ran.
        phase1_stage = "extraction_empty" if institution is not None else "no_parser_match"

        # Phase 2 — AI extraction fallback. Respects the same extraction consent
        # (distinct from categorization): only runs with a client AND
        # ai_extraction_enabled. When skipped, no ``chat`` call is made and we
        # fall through to the quarantine write. (``use_ai`` already implies a
        # non-None client; the explicit check also narrows the type for pyright.)
        if use_ai and api_client is not None:
            merged, extraction_stage = _attempt_extraction(email_details, institution, api_client)
            if merged is not None:
                # Recovered: record the row up-front as "recovered" with the
                # Phase 1 stage (what would have failed), then hand the merged
                # transaction back for the caller to store + mark_recovered.
                failure_id = store.record_failure(
                    {
                        "email_details": email_details,
                        "detected_institution": institution,
                        "failure_stage": phase1_stage,
                        "alert_classifier_result": classifier_result,
                        "status": "recovered",
                    }
                )
                return RecoveryOutcome("recovered", merged, failure_id)
            # Extraction failed → quarantine with the extractor's stage.
            failure_id = store.record_failure(
                {
                    "email_details": email_details,
                    "detected_institution": institution,
                    "failure_stage": extraction_stage,
                    "alert_classifier_result": classifier_result,
                }
            )
            _notify_drift(store, institution)
            return RecoveryOutcome("quarantined", None, failure_id)

        # AI disabled / no client → straight to quarantine with the Phase 1 stage.
        failure_id = store.record_failure(
            {
                "email_details": email_details,
                "detected_institution": institution,
                "failure_stage": phase1_stage,
                "alert_classifier_result": classifier_result,
            }
        )
        _notify_drift(store, institution)
        return RecoveryOutcome("quarantined", None, failure_id)
    except Exception:
        logger.exception("recover_or_quarantine failed; ignoring email (fail-open)")
        return RecoveryOutcome("ignored", None, None)


def mark_recovered(store: IParseFailureStore | None, failure_id: str | None, date_file_name: str) -> None:
    """Flip a quarantined row to ``recovered`` after its transaction landed.

    No-op (logged) when there is no store or no failure id, or on any error —
    a bookkeeping failure must not undo a successfully stored transaction.
    """
    if store is None or not failure_id:
        return
    try:
        store.set_status(failure_id, "recovered", recovered_date_file_name=date_file_name)
    except Exception:
        logger.exception("mark_recovered failed for failure_id=%s (fail-open)", failure_id)


def downgrade_to_quarantined(store: IParseFailureStore | None, failure_id: str | None) -> None:
    """Flip a pre-marked ``recovered`` row back to ``quarantined``.

    Used when a recovered result's ``add_transaction`` returned ``None`` (e.g. a
    required field was missing): the extraction succeeded but the transaction
    could not be stored, so we downgrade the row rather than lose the capture.
    No-op (logged) without a store or id, and fail-open on any error.
    """
    if store is None or not failure_id:
        return
    try:
        store.set_status(failure_id, "quarantined")
    except Exception:
        logger.exception("downgrade_to_quarantined failed for failure_id=%s (fail-open)", failure_id)


def quarantine_db_invalid(
    store: IParseFailureStore | None,
    email_details: dict[str, Any],
    api_client: AIProviderClient | None,
) -> str | None:
    """Quarantine an email whose parsed fields failed DB validation.

    Used when ``add_transaction`` returned ``None`` (e.g. a required field was
    missing) — the parse produced *something* but it could not be persisted, so
    we capture it for review with stage ``"db_validation_failed"``. Returns the
    failure id, or ``None`` (fail-open) when there is no store or on error.

    ``api_client`` is accepted for signature symmetry with
    ``recover_or_quarantine`` (and forward-compatibility) but is not consulted:
    a row that parsed far enough to attempt a DB write is relevant by
    definition, so no relevance gate is run here.
    """
    if store is None:
        return None
    try:
        institution = email_details.get("institution") or _detect_institution_by_sender(
            email_details.get("from_email") or ""
        )
        return store.record_failure(
            {
                "email_details": email_details,
                "detected_institution": institution,
                "failure_stage": "db_validation_failed",
            }
        )
    except Exception:
        logger.exception("quarantine_db_invalid failed (fail-open)")
        return None
