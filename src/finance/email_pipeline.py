# src/finance/email_pipeline.py

import logging
from typing import TYPE_CHECKING, Any

from src.finance import notification_service
from src.finance.ai_client import AIProviderClient
from src.finance.app_timezone import now_local
from src.finance.categorizer import categorize_transactions
from src.finance.email_parser import (
    extract_basic_details,
    extract_email_body,
    extract_forwarded_message_details,
    finalize_email_details,
    init_parse_email,
)
from src.finance.parsers.cibc_parser import CIBCParser
from src.finance.parsers.mbna_parser import MBNAParser
from src.finance.parsers.pc_financial_parser import PCFinancialParser
from src.finance.parsers.rbc_parser import RBCParser
from src.finance.parsers.simplii_parser import SimpliiParser
from src.finance.protocols import IParseFailureStore, ITransactionsDB
from src.finance.transaction_context import TransactionContextEnricher

if TYPE_CHECKING:
    from src.finance.parser_base import TransactionParser

logger = logging.getLogger(__name__)

# `_detect_institution_by_sender` is a sender-to-institution classifier reused by
# `parse_recovery` (and its dedicated test); the underscore keeps it out of the
# module's general interface while marking the cross-module use as intentional.
__all__ = ["_detect_institution_by_sender"]

# The parser keys, in the order body-text detection scans for them. This is the
# single source of truth for "which institution names can appear in an email
# body" — used both by ``parse_email_body``'s phase-2 fallback loop and by
# ``parse_recovery`` when deciding whether an unparsed email is even relevant.
PARSER_KEYS: tuple[str, ...] = ("CIBC", "RBC", "MBNA", "Simplii", "PC Financial")


def build_parsers() -> dict[str, "TransactionParser"]:
    """Construct the institution -> parser instance dispatch table.

    Single source of truth for which bank parsers participate in live email
    dispatch. ``tests/property/test_parser_invariants.py`` asserts its parser
    classes match ``PARSERS`` so a newly registered parser can't silently
    escape the shared invariants.
    """
    return {
        "CIBC": CIBCParser(),
        "RBC": RBCParser(),
        "MBNA": MBNAParser(),
        "Simplii": SimpliiParser(),
        "PC Financial": PCFinancialParser(),
    }


def extract_raw_email_details(raw_email: bytes) -> dict[str, Any]:
    """
    Extracts all relevant details from an email file.

    Parameters:
    path (str): The path to the file containing the raw email.

    Returns:
    dict: A dictionary containing all extracted details from the email.
    """
    parsed_email = init_parse_email(raw_email)
    basic_details = extract_basic_details(parsed_email)

    # Extract the body and details from forwarded messages, if any
    body = extract_email_body(parsed_email)
    forwarded_details = extract_forwarded_message_details(body)

    # Combine all details into a final comprehensive dictionary
    return finalize_email_details(basic_details, body, forwarded_details)


def _detect_institution_by_sender(from_email: str | None) -> str | None:
    """
    Detect the financial institution from the sender email domain.

    Returns the institution key (e.g. "CIBC") or None if unrecognized.
    Interac e-transfers (payments.interac.ca) return None to fall through
    to body-text detection, since multiple institutions use Interac.
    """
    if not from_email:
        return None

    domain_map = {
        "cibc.com": "CIBC",
        "alerts.rbc.com": "RBC",
        "mbna.ca": "MBNA",
        "pcfinancial.ca": "PC Financial",
        # payments.interac.ca is intentionally omitted — fall through to body text
    }

    from_email_lower = from_email.lower()
    for domain, institution in domain_map.items():
        if domain in from_email_lower:
            return institution

    return None


def parse_email_body(
    email_body_text: str, email_details: dict[str, Any], api_client: AIProviderClient | None = None
) -> dict[str, Any]:
    """
    Parses the email body text to extract transaction details.

    Detection strategy:
    1. If email_details contains a from_email, try sender-domain matching first.
    2. For Interac e-transfers or unknown senders, fall back to body-text matching.

    Parameters:
    email_body_text (str): The text content of the email body.
    email_details (dict): A dictionary containing details extracted from the email.

    Returns:
    dict: A dictionary containing the parsed transaction details.
    """
    parsers = build_parsers()

    # Phase 1: Detect institution by sender email domain
    from_email = email_details.get("from_email", "")
    institution = _detect_institution_by_sender(from_email)

    if institution and institution in parsers:
        logger.debug("Institution detected by sender domain: %s", institution)
        all_details = parsers[institution].parse_email(email_body_text, email_details)
        if all_details.get("amount") and all_details.get("company") and api_client:
            transaction = {
                "amount": all_details["amount"],
                "company": all_details["company"],
            }
            category = categorize_transactions(api_client, transaction)
            all_details["category"] = category
            if "_category_audit" in transaction:
                all_details["_category_audit"] = transaction["_category_audit"]
        return all_details

    # Phase 2: Fall back to body-text matching (Interac, missing from_email, etc.)
    for key in PARSER_KEYS:
        parser = parsers[key]
        if key in email_body_text:
            logger.debug("Institution detected by body text: %s", key)
            all_details = parser.parse_email(email_body_text, email_details)
            if all_details.get("amount") and all_details.get("company") and api_client:
                transaction = {
                    "amount": all_details["amount"],
                    "company": all_details["company"],
                }
                category = categorize_transactions(api_client, transaction)
                all_details["category"] = category
                if "_category_audit" in transaction:
                    all_details["_category_audit"] = transaction["_category_audit"]
            return all_details

    return email_details


def parse_email(
    raw_email: bytes, file_name: str | None = None, api_client: AIProviderClient | None = None
) -> dict[str, Any]:
    email_details = extract_raw_email_details(raw_email)

    if file_name:
        email_details["file_name"] = file_name

    email_body_text = email_details.get("body", "")

    if email_body_text:
        email_details = parse_email_body(email_body_text, email_details, api_client)
    return email_details


# ---------------------------------------------------------------------------
# Per-message processing (mirrors lambda_function.py handler flow)
# ---------------------------------------------------------------------------


def process_message(
    raw_bytes: bytes,
    uid: bytes | str,
    transactions_db: ITransactionsDB,
    context_enricher: TransactionContextEnricher,
    api_client: AIProviderClient | None = None,
    parse_failure_store: IParseFailureStore | None = None,
) -> str:
    """Process a single email message through the transaction pipeline.

    Returns "new", "duplicate", "invalid", "quarantined", "skipped", or "error".
    """
    # Imported lazily: ``parse_recovery`` imports this module at load time
    # (``PARSER_KEYS`` / ``_detect_institution_by_sender``), so a module-level
    # import here would be a circular dependency.
    from src.finance.parse_recovery import (
        downgrade_to_quarantined,
        mark_recovered,
        quarantine_db_invalid,
        recover_or_quarantine,
    )

    now = now_local()
    file_name = f"imap/{now.year}/{now.month:02d}/uid-{uid}.eml"

    try:
        result = parse_email(raw_bytes, file_name, api_client)
    except Exception:
        logger.exception("Failed to parse email uid=%s", uid)
        return "error"

    # recovered_failure_id is set only on the Phase 2 "recovered" arm — used to
    # flip the quarantine row to "recovered" once the transaction is stored.
    recovered_failure_id: str | None = None

    # No transaction_type means no bank sub-parser actually extracted a transaction
    # (Google security alerts, promotional mail, even bank balance-alert emails where
    # `institution` is set but no purchase/withdrawal/e-transfer regex matched).
    # Hand it to the recovery gate: relevant emails are quarantined for review,
    # irrelevant ones are dropped as before.
    if not result.get("transaction_type"):
        outcome = recover_or_quarantine(result, parse_failure_store, api_client)
        if outcome.status == "quarantined":
            logger.info(
                "uid=%s: parse failed but captured for review (failure_id=%s, from=%s, subject=%r)",
                uid,
                outcome.failure_id,
                result.get("from_email"),
                result.get("subject"),
            )
            return "quarantined"
        if outcome.status == "recovered" and outcome.result is not None:
            # Phase 2: extraction reconstructed a transaction — continue into the
            # normal add flow below with the enriched result.
            result = outcome.result
            recovered_failure_id = outcome.failure_id
        else:
            logger.info(
                "uid=%s: no parser matched (from=%s, institution=%s, subject=%r), skipping",
                uid,
                result.get("from_email"),
                result.get("institution"),
                result.get("subject"),
            )
            return "skipped"

    # Pop BOTH provenance keys — neither may reach the DB as a literal field.
    extraction_audit = result.pop("_extraction_audit", None)
    category_audit = result.pop("_category_audit", None)
    date_file_name = transactions_db.add_transaction(
        result, category_audit=category_audit, extraction_audit=extraction_audit
    )

    if date_file_name is None:
        if recovered_failure_id is not None:
            # Extraction recovered a transaction but the DB rejected it — downgrade
            # the pre-marked "recovered" row rather than lose the capture.
            logger.info("uid=%s: recovered transaction failed DB validation, downgrading to quarantined", uid)
            downgrade_to_quarantined(parse_failure_store, recovered_failure_id)
            return "invalid"
        logger.info("uid=%s: validation failure (missing required fields), capturing for review", uid)
        quarantine_db_invalid(parse_failure_store, result, api_client)
        return "invalid"

    if date_file_name is False:
        logger.info("uid=%s: duplicate transaction, skipping", uid)
        return "duplicate"

    # add_transaction returns str | False | None; the two non-str cases are
    # handled above, so this is always str here.
    assert isinstance(date_file_name, str)  # noqa: S101 — type-narrowing; False/None cases handled above

    # A recovered transaction landed — flip its quarantine row to "recovered".
    if recovered_failure_id is not None:
        mark_recovered(parse_failure_store, recovered_failure_id, date_file_name)

    # Enrich with month-to-date spending context
    context = context_enricher.enrich(result)
    if context:
        transactions_db.update_context(result["forwarded_to"], date_file_name, context)

    notification_service.send(result, context=context)

    logger.info("uid=%s: new transaction stored as %s", uid, date_file_name)
    return "new"
