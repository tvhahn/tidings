"""AI extraction fallback — constrained LLM recovery for unparseable bank emails.

When the deterministic parsers fail to read a transaction-alert email, the
quarantine pipeline calls :func:`extract_transaction` as a last resort. The
model is forced through a single tool call and its output is run through a
strict verbatim-validation contract (:func:`validate_extraction`) before it is
trusted — the model may only surface an amount/company that is literally
present in the email body, never a hallucination.

Mirrors the structure of :func:`src.finance.categorizer.categorize_transactions`:
forced tool call, layered fallbacks, each failure logged.
"""

import logging
from typing import Any

from src.finance.ai_client import AIProviderClient
from src.finance.categorizer import extract_function_call_args

__all__ = [
    "extract_transaction",
    "validate_extraction",
]

logger = logging.getLogger(__name__)

# Stages reported to the caller on failure. Mirror the failure_stage taxonomy in
# the implementation plan (§1.2).
_STAGE_EXTRACTION_FAILED = "ai_extraction_failed"
_STAGE_VALIDATION_FAILED = "ai_validation_failed"

_TRANSACTION_TYPES = ["purchase", "withdrawal", "preauth", "e-transfer", "deposit"]


def validate_extraction(amount_str: str, company: str, body: str) -> bool:
    """Anti-hallucination contract: the extracted amount and company must be
    literally present in the email body.

    Pure helper — no I/O, no clock, deterministic.

    Amount: parsed to ``float`` (``$`` and ``,`` stripped first). Rejected when
    non-positive or unparseable. The parsed value must then render to at least
    one string that is a verbatim substring of ``body`` — the raw model string,
    ``f"{v:,.2f}"``, ``f"{v:.2f}"``, or the integer forms when ``v == int(v)``
    (``f"{int(v):,}"`` / ``str(int(v))``) — each tried with and without a ``$``
    prefix.

    Company: case-insensitive substring of ``body`` after collapsing runs of
    whitespace in both haystack and needle. Empty/whitespace company is rejected.
    """
    # --- Amount: parse then require a verbatim rendering in the body ---------
    cleaned = amount_str.strip().lstrip("$").replace(",", "")
    try:
        value = float(cleaned)
    except (ValueError, TypeError):
        return False
    if value <= 0:
        return False

    candidates: set[str] = {
        amount_str.strip(),
        f"{value:,.2f}",
        f"{value:.2f}",
    }
    if value == int(value):
        candidates.add(f"{int(value):,}")
        candidates.add(str(int(value)))

    # Each candidate counts with and without a leading "$".
    rendered = {c for c in candidates if c}
    rendered |= {f"${c}" for c in list(rendered)}

    if not any(c in body for c in rendered):
        return False

    # --- Company: whitespace-collapsed case-insensitive substring -----------
    needle = " ".join(company.split())
    if not needle:
        return False
    haystack = " ".join(body.split())
    return needle.casefold() in haystack.casefold()


def extract_transaction(
    api_client: AIProviderClient | None, email_details: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    """Attempt to recover a transaction from an unparseable bank-alert email.

    Returns ``(result, None)`` on success, where ``result`` is a transaction
    dict ready for ``add_transaction`` (provenance/audit stamping is the
    caller's job). On failure returns ``(None, stage)`` where ``stage`` is:

    - ``"ai_extraction_failed"`` — no client, api error, empty completion, or a
      parse error: the model produced nothing usable.
    - ``"ai_validation_failed"`` — the model returned values that failed the
      verbatim anti-hallucination checks.
    """
    if api_client is None:
        logger.error("No AI client configured for extraction; cannot recover email")
        return None, _STAGE_EXTRACTION_FAILED

    subject = email_details.get("subject", "") or ""
    body = email_details.get("body", "") or ""

    tools = [
        {
            "type": "function",
            "function": {
                "name": "extract_transaction",
                "description": "Extract the transaction details from a bank or credit-card alert email.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "amount": {
                            "type": "string",
                            "description": (
                                "the transaction amount exactly as it appears in the email, "
                                "digits and decimal only, no currency symbol"
                            ),
                        },
                        "company": {
                            "type": "string",
                            "description": "merchant or counterparty name exactly as written in the email",
                        },
                        "transaction_type": {
                            "type": "string",
                            "enum": _TRANSACTION_TYPES,
                            "description": "the kind of transaction the email describes",
                        },
                    },
                    "required": ["amount", "company", "transaction_type"],
                },
            },
        }
    ]

    history = [
        {
            "role": "system",
            "content": "You are an expert at reading bank and credit-card alert emails.",
        },
        {
            "role": "user",
            "content": (f"Subject: {subject}\n\n{body}\n\nExtract only what is literally present; do not guess."),
        },
    ]

    tool_choice = {"type": "function", "function": {"name": "extract_transaction"}}

    # 1) Try the API call
    try:
        completion = api_client.chat(history, tools=tools, tool_choice=tool_choice)
    except Exception:
        logger.exception("AI API call failed during extraction")
        return None, _STAGE_EXTRACTION_FAILED

    # 2) Bail out if the client wrapper returned None / no choices
    if not completion or not hasattr(completion, "choices"):
        logger.error("Empty or invalid completion returned by AI chat during extraction (None or no choices)")
        return None, _STAGE_EXTRACTION_FAILED

    # 3) Try extracting the function arguments
    try:
        args = extract_function_call_args(completion) or {}
    except Exception:
        logger.exception("Failed to parse extraction response")
        return None, _STAGE_EXTRACTION_FAILED

    amount_str = args.get("amount")
    company = args.get("company")
    transaction_type = args.get("transaction_type")

    if not amount_str or not company or not transaction_type:
        logger.error("Extraction returned incomplete fields: %r", args)
        return None, _STAGE_EXTRACTION_FAILED

    # 4) Anti-hallucination validation against the literal body
    if not validate_extraction(amount_str, company, body):
        logger.error(
            "Extraction failed verbatim validation (amount=%r company=%r)",
            amount_str,
            company,
        )
        return None, _STAGE_VALIDATION_FAILED

    amount = float(amount_str.strip().lstrip("$").replace(",", ""))
    result = {
        "amount": amount,
        "company": company,
        "transaction_type": transaction_type,
        "institution": email_details.get("detected_institution") or "Other",
    }
    return result, None
