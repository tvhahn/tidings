"""Transaction categorization — OpenAI-based classification with override support."""

import json
import logging
from typing import Any

from openai import APIError, AuthenticationError, PermissionDeniedError, RateLimitError

from src.finance.ai_client import AIProviderClient
from src.finance.app_config import get_config
from src.finance.category_audit import build_audit
from src.finance.category_resolver import resolve_override
from src.finance.config_loader import get_category_list, get_override_context

__all__ = [
    "categorize_transactions",
    "email_is_transaction_alert",
    "extract_function_call_args",
]

logger = logging.getLogger(__name__)


def _classify_ai_error(exc: BaseException | None) -> str:
    """Map a failed AI categorization call to a specific audit ``fallback_reason``.

    Returns ``"empty_completion"`` for ``None`` (no captured error — the model
    genuinely returned nothing usable). Provider clients that don't raise
    OpenAI SDK exceptions (the Codex subprocess path) attach a pre-classified
    ``reason``; otherwise OpenAI SDK error types are mapped here. A real
    ``insufficient_quota`` 429 becomes ``"quota_exceeded"`` rather than being
    lost as a generic empty completion.
    """
    # Only a real captured exception classifies as a transport/provider error;
    # anything else (None, or a stray non-exception value) means the client
    # simply returned nothing usable.
    if not isinstance(exc, BaseException):
        return "empty_completion"

    reason = getattr(exc, "reason", None)
    if isinstance(reason, str) and reason:
        return reason

    if isinstance(exc, RateLimitError):
        code = str(getattr(exc, "code", "") or "")
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                code = f"{code} {err.get('code') or ''} {err.get('type') or ''}"
        return "quota_exceeded" if "insufficient_quota" in code else "rate_limited"
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return "auth_error"
    if isinstance(exc, APIError):
        return "api_error"
    return "api_error"


def email_is_transaction_alert(api_client: AIProviderClient | None, history: list[dict[str, Any]]) -> bool | None:
    """
    Determines whether an email content sent via history is about a bank or credit card transaction alert.

    Returns True if the email is identified as a transaction alert, False if not, or None on error.
    """
    if api_client is None:
        return None

    tools = [
        {
            "type": "function",
            "function": {
                "name": "detect_if_transaction_alert",
                "description": "Detect if the email is a bank or credit card transaction alert.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "true_or_false": {
                            "type": "string",
                            "enum": ["True", "False"],
                            "description": "True if email is a transaction alert. False otherwise",
                        }
                    },
                    "required": ["true_or_false"],
                },
            },
        }
    ]

    tool_choice = {
        "type": "function",
        "function": {"name": "detect_if_transaction_alert"},
    }
    completion = api_client.chat(history, tools=tools, tool_choice=tool_choice)
    try:
        function_call_arguments = extract_function_call_args(completion)
        if function_call_arguments:
            val = function_call_arguments.get("true_or_false", "").lower()
            if val == "true":
                return True
            if val == "false":
                return False
            raise ValueError(f"Unexpected boolean value: {val}")
        return None
    except Exception:
        logger.exception("Error processing transaction alert check")
        return None


def categorize_transactions(
    api_client: AIProviderClient | None, transaction: dict[str, Any], categories: list[str] | None = None
) -> str:
    """
    Categorizes a transaction based on the amount and company name using the OpenAI API.

    First checks category_overrides.json for a case-insensitive match.
    If no override, calls OpenAI with function calling constrained to predefined categories.
    On any error, returns "Miscellaneous".
    """

    if categories is None:
        # Use the active vocabulary from storage (the user's customized list), not the
        # bundled seed — keeps AI categories consistent with their overrides. Falls back
        # to the seed JSON automatically when storage is empty.
        categories = get_category_list()

    company = transaction.get("company", "")
    overrides, aliases = get_override_context()
    match = resolve_override(company, overrides, aliases=aliases)
    if match:
        logger.info(
            "Tier %s override for '%s': '%s' (matched=%s)",
            match.tier,
            company,
            match.category,
            match.matched_rule,
        )
        transaction["_category_audit"] = build_audit(
            "override",
            tier=match.tier,
            matched_rule=match.matched_rule,
            confidence=match.confidence,
        )
        return match.category

    model = getattr(api_client, "model", None)

    # Privacy opt-out — user disabled AI categorization (overrides still work above)
    if not get_config().get("ai_categorization_enabled", False):
        logger.info(
            "AI categorization disabled (privacy setting), defaulting to Miscellaneous for '%s'",
            company,
        )
        transaction["_category_audit"] = build_audit("ai_fallback", fallback_reason="disabled", model=model)
        return "Miscellaneous"

    # No OpenAI client — fall back to Miscellaneous (overrides still work above)
    if api_client is None:
        logger.info("No OpenAI client configured, defaulting to Miscellaneous for '%s'", company)
        transaction["_category_audit"] = build_audit("ai_fallback", fallback_reason="no_client")
        return "Miscellaneous"

    tools = [
        {
            "type": "function",
            "function": {
                "name": "categorize_transaction",
                "description": "Categorize a transaction based on the amount and company name.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": categories,
                            "description": "The category of the transaction.",
                        }
                    },
                    "required": ["category"],
                },
            },
        }
    ]

    history = [
        {
            "role": "system",
            "content": "You are an expert in categorizing transaction data based on the amount and company name.",
        },
        {
            "role": "user",
            "content": (
                f"Here is a transaction: {transaction}. Categorize it into one of the"
                " predefined categories. If you are uncertain, categorize the"
                " transaction as 'Miscellaneous'."
            ),
        },
    ]

    tool_choice = {"type": "function", "function": {"name": "categorize_transaction"}}

    # 1) Try the API call. Clients swallow errors and return None (callers stay
    #    crash-free) but record the exception on `last_error`; we still guard
    #    against a client that raises directly.
    try:
        completion = api_client.chat(history, tools=tools, tool_choice=tool_choice)
    except Exception as exc:
        reason = _classify_ai_error(exc)
        logger.exception("AI categorization call raised (%s), defaulting to Miscellaneous", reason)
        transaction["_category_audit"] = build_audit("ai_fallback", fallback_reason=reason, model=model)
        return "Miscellaneous"

    # 2) Bail out if the client wrapper returned None. Recover the real reason
    #    (e.g. quota_exceeded, auth_error, codex_timeout) from the client's
    #    last_error so the audit reflects *why* — not a blanket empty_completion.
    if not completion or not hasattr(completion, "choices"):
        reason = _classify_ai_error(getattr(api_client, "last_error", None))
        logger.error("AI categorization returned no completion (%s); defaulting to Miscellaneous", reason)
        transaction["_category_audit"] = build_audit("ai_fallback", fallback_reason=reason, model=model)
        return "Miscellaneous"

    # 3) Try extracting the function arguments
    try:
        args = extract_function_call_args(completion) or {}
        category = args.get("category")
    except Exception:
        logger.exception("Failed to parse categorization response, defaulting to Miscellaneous")
        transaction["_category_audit"] = build_audit("ai_fallback", fallback_reason="parse_error", model=model)
        return "Miscellaneous"

    # 4) Finally, ensure a non-empty string
    if category:
        transaction["_category_audit"] = build_audit("ai", model=model)
        return category
    transaction["_category_audit"] = build_audit("ai_fallback", fallback_reason="empty_completion", model=model)
    return "Miscellaneous"


def extract_function_call_args(completion: Any) -> dict[str, Any] | None:
    try:
        tool_calls = completion.choices[0].message.tool_calls
        if tool_calls:
            function_call_args_json = tool_calls[0].function.arguments
            return json.loads(function_call_args_json)
    except Exception:
        logger.exception("Failed to extract function call arguments")
        raise
