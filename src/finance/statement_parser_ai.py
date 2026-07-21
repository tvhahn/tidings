"""AI fallback parser for bank-statement PDFs from banks without a built-in parser.

Mirrors the email "rescue with AI" flow (``parse_recovery`` + ``extractor``):
an explicit consent key (``ai_statement_parsing_enabled``), the document-parsing
provider the user picked in Settings (``document_parsing_provider``), and
fail-closed validation of everything the model returns — every transaction amount must
appear verbatim in the PDF's extracted text, so the model cannot invent money
movements. Output is a ``StatementParseResult``, so the AI path feeds the
existing reconcile → review → import pipeline unchanged.

Deterministic parsers stay the preferred path: this module is only invoked
when ``select_parser``'s choice raises (no recognizable transaction table).
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import shutil
from datetime import datetime
from typing import TYPE_CHECKING, Any

import pdfplumber

from src.finance.ai_cli import extract_json, invoke_text_provider
from src.finance.app_config import get_config
from src.finance.statement_parser_base import StatementParseResult, clean_statement_description

if TYPE_CHECKING:
    from src.finance.openai_client import OpenAIClient

logger = logging.getLogger(__name__)

# `_MIN_TEXT_CHARS` (scan threshold) and `_amount_in_text` (verbatim-total guard)
# are reused by the AI receipt parser and its test suite; the underscore keeps
# them out of the general statement-parser interface.
__all__ = ["_MIN_TEXT_CHARS", "_amount_in_text", "resolve_ai_statement_provider"]

# CLI providers get longer than the 180s summary default: a dense statement is
# a bigger extraction job than a day summary.
AI_PARSE_TIMEOUT_SECONDS = 300

# A text-layer PDF of a real statement yields far more than this; below it the
# PDF is almost certainly a scan with no extractable text.
_MIN_TEXT_CHARS = 200

# Backstop against a runaway/looping model response.
_MAX_TRANSACTIONS = 2000

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INSTITUTION_ALLOWED_RE = re.compile(r"[^A-Za-z0-9 &-]")

_PROMPT_TEMPLATE = """You are a bank-statement extraction engine. Below is the text of a bank \
statement PDF, extracted page by page with pdfplumber (spaces inside words may be missing — \
that is an extraction artifact, not the real text).

Extract every transaction and reply with ONLY a JSON object (no markdown fence, no prose) \
with this exact shape:

{{
  "institution": "<bank name, e.g. RBC, Simplii, CIBC>",
  "account_type": "<chequing|savings|credit>",
  "period_start": "YYYY-MM-DD",
  "period_end": "YYYY-MM-DD",
  "transactions": [
    {{"date": "YYYY-MM-DD", "description": "<verbatim description>",
      "amount": 45.67, "type": "withdrawal", "balance": 1234.56}}
  ]
}}

Rules:
- "type" is "withdrawal" (money out) or "deposit" (money in). Use the column the amount \
appears in, or the running balance direction, to decide.
- "amount" is always positive. "balance" is the running balance if shown on that row, else null.
- Skip opening/closing balance rows — they are not transactions.
- When a row shows two date columns (e.g. "trans." and "eff."), use the date adjacent to the \
description — the effective date, when the money actually moved — not the first-printed date.
- A row with an amount but no date belongs to the most recent date above it.
- Join multi-line descriptions into one string.
- Do not invent transactions; extract only what is present in the text.

Statement text:
{text}"""


class StatementAIError(Exception):
    """AI statement parsing failed (provider unavailable, bad output, or validation)."""


def resolve_ai_statement_provider() -> str | None:
    """Return the usable provider name for AI document parsing, or None.

    Follows the document-parsing provider selection from Settings → Intelligence
    (``document_parsing_provider``, shared by statement and receipt parsing) and
    requires the matching CLI/key to actually be available, mirroring the
    detection in ``app_config.get_config_with_features``.
    """
    provider = get_config().get("document_parsing_provider", "disabled")
    if provider == "claude_cli" and shutil.which("claude"):
        return provider
    if provider == "codex":
        from src.finance import chatgpt_oauth

        if shutil.which("codex") and chatgpt_oauth.auth_json_path().exists():
            return provider
    if provider == "gemini_cli":
        from src.finance.app_config import _has_gemini_cli

        if _has_gemini_cli():
            return provider
    if provider == "openai":
        from src.finance.app_config import _has_openai_key

        if _has_openai_key():
            return provider
    return None


def _extract_pages_text(pdf_bytes: bytes) -> list[str]:
    """Extract per-page text with pdfplumber; raises StatementAIError on failure."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as doc:
            return [page.extract_text() or "" for page in doc.pages]
    except Exception as e:
        raise StatementAIError(f"Could not read the PDF: {e}") from e


def build_prompt(pages: list[str]) -> str:
    joined = "\n\n".join(f"--- page {i} ---\n{text}" for i, text in enumerate(pages, 1))
    return _PROMPT_TEMPLATE.format(text=joined)


def _sanitize_institution(name: Any) -> str:
    """Reduce the model-reported bank name to a filesystem/statement-source-safe label."""
    if not isinstance(name, str):
        return "Unknown"
    cleaned = _INSTITUTION_ALLOWED_RE.sub("", name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)[:40]
    return cleaned or "Unknown"


def _sanitize_account_type(value: Any) -> str:
    if isinstance(value, str) and value.strip().lower() in ("chequing", "savings", "credit"):
        return value.strip().lower()
    return "chequing"


def _valid_date(value: Any) -> str | None:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")  # noqa: DTZ007 — validity check only, returns the original string
    except ValueError:
        return None
    return value


def _amount_in_text(amount: float, text: str) -> bool:
    """Check that an amount renders verbatim somewhere in the extracted text.

    Anti-hallucination gate, analogous to ``extractor.validate_extraction``:
    banks print amounts with two decimals, with or without thousands commas.
    """
    return f"{amount:,.2f}" in text or f"{amount:.2f}" in text


def _validate_transactions(data: dict[str, Any], full_text: str) -> list[dict[str, Any]]:
    """Fail-closed validation of the model's transaction list."""
    raw_txns = data.get("transactions")
    if not isinstance(raw_txns, list) or not raw_txns:
        raise StatementAIError("The AI found no transactions in this statement")
    if len(raw_txns) > _MAX_TRANSACTIONS:
        raise StatementAIError(f"The AI returned an implausible number of transactions ({len(raw_txns)})")

    txns: list[dict[str, Any]] = []
    unverified: list[str] = []
    for i, t in enumerate(raw_txns):
        if not isinstance(t, dict):
            raise StatementAIError(f"Transaction {i + 1} is not an object")
        date = _valid_date(t.get("date"))
        if date is None:
            raise StatementAIError(f"Transaction {i + 1} has an invalid date: {t.get('date')!r}")
        description = t.get("description")
        if not isinstance(description, str) or not description.strip():
            raise StatementAIError(f"Transaction {i + 1} has no description")
        txn_type = t.get("type")
        if txn_type not in ("withdrawal", "deposit"):
            raise StatementAIError(f"Transaction {i + 1} has an invalid type: {txn_type!r}")
        try:
            amount = round(float(t.get("amount")), 2)  # type: ignore[arg-type]
        except (TypeError, ValueError) as e:
            raise StatementAIError(f"Transaction {i + 1} has an invalid amount: {t.get('amount')!r}") from e
        if amount <= 0:
            raise StatementAIError(f"Transaction {i + 1} has a non-positive amount: {amount}")
        if not _amount_in_text(amount, full_text):
            unverified.append(f"{date} {amount:.2f}")
        balance: float | None = None
        raw_balance = t.get("balance")
        if raw_balance is not None:
            try:
                balance = round(float(raw_balance), 2)
            except (TypeError, ValueError):
                balance = None
            # A balance the PDF never printed is a fabrication; drop the value
            # rather than the row (balance is advisory, amount is not).
            if balance is not None and not _amount_in_text(abs(balance), full_text):
                balance = None
        txns.append(
            {
                "date": date,
                "description": re.sub(r"\s+", " ", description).strip(),
                "amount": amount,
                "type": txn_type,
                "balance": balance,
            }
        )

    if unverified:
        raise StatementAIError(
            "The AI reported amounts that do not appear in the statement text "
            f"({len(unverified)} of {len(raw_txns)}: {', '.join(unverified[:5])}"
            f"{', …' if len(unverified) > 5 else ''}). Nothing was saved."
        )
    return txns


async def parse_statement_with_ai(
    pdf_bytes: bytes,
    openai_client: OpenAIClient | None = None,
) -> StatementParseResult:
    """Parse a statement PDF with the configured AI provider.

    Raises ``StatementAIError`` with a user-presentable message on any failure;
    never returns a partially-validated result.
    """
    provider = resolve_ai_statement_provider()
    if provider is None:
        raise StatementAIError(
            "No AI provider is available for statement parsing — pick and connect one in Settings → Intelligence."
        )

    pages = await asyncio.to_thread(_extract_pages_text, pdf_bytes)
    full_text = "\n".join(pages)
    if len(full_text.strip()) < _MIN_TEXT_CHARS:
        raise StatementAIError(
            "This PDF has no extractable text (it may be a scanned image), so it can't be parsed with AI yet."
        )

    config = get_config()
    model = config.get("document_parsing_model")
    reasoning_effort = config.get("document_parsing_reasoning_effort")
    logger.info("AI statement parsing via %s (%d pages)", provider, len(pages))
    reply = await invoke_text_provider(
        provider,
        build_prompt(pages),
        openai_client,
        error_cls=StatementAIError,
        timeout=AI_PARSE_TIMEOUT_SECONDS,
        model=model,
        reasoning_effort=reasoning_effort,
    )
    data = extract_json(reply, error_cls=StatementAIError)
    transactions = _validate_transactions(data, full_text)

    raw_descriptions = [t["description"] for t in transactions]
    metadata = {
        "institution": _sanitize_institution(data.get("institution")),
        "account_type": _sanitize_account_type(data.get("account_type")),
        "period_start": _valid_date(data.get("period_start")),
        "period_end": _valid_date(data.get("period_end")),
        "transaction_count": len(transactions),
        "parsed_with_ai": True,
    }
    return StatementParseResult(
        transactions=transactions,
        metadata=metadata,
        raw_descriptions=raw_descriptions,
        cleaned_descriptions=[clean_statement_description(d) for d in raw_descriptions],
    )
