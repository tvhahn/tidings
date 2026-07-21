"""AI receipt parser: turn a receipt photo or text-PDF into structured line items.

Mirrors ``statement_parser_ai`` in shape and discipline — an explicit consent key
(``ai_receipt_parsing_enabled``, gated in the router), the provider the user
already picked in Settings (via the *reused* ``resolve_ai_statement_provider``),
forced-JSON output, fence-tolerant parsing, and fail-closed validation. The total
is never trusted blindly: a text-PDF's total must render verbatim in the extracted
text, and the receipt matcher (``receipt_matcher``) is the backstop for image
receipts, which have no text oracle.

This is the first vision path in the codebase (L6). The provider matrix:

- **PDF with text** (>= ``_MIN_TEXT_CHARS`` via pdfplumber): a text prompt, all
  four providers. The openai path pins ``document_parsing_model`` or
  ``DEFAULT_OPENAI_CHAT_MODEL`` (the injected client's default is an embedding
  model, which the chat endpoint rejects).
- **Scanned PDF** (no extractable text): rejected with a calm message advising a
  photo instead (pdf->image rendering is deferred, L17).
- **Image + openai**: one multimodal chat message (base64 data URL) through
  ``OpenAIClient.chat``, pinned to the same resolved chat model.
- **Image + codex / claude_cli**: ``run_cli_provider`` with ``image_paths``.
- **Image + gemini_cli**: rejected (deferred, L17).

The provider, model, and reasoning-effort all come from the shared
``document_parsing_*`` config keys (statement parsing uses the same three).
"""

from __future__ import annotations

import asyncio
import base64
import io
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pdfplumber

from src.finance.ai_cli import DEFAULT_OPENAI_CHAT_MODEL, extract_json, invoke_text_provider, run_cli_provider
from src.finance.app_config import get_config
from src.finance.statement_parser_ai import (
    _MIN_TEXT_CHARS,
    _amount_in_text,
    resolve_ai_statement_provider,
)

if TYPE_CHECKING:
    from src.finance.openai_client import OpenAIClient

# Line items are advisory: if the parts don't add up to the total within this
# tolerance, we drop the items and keep merchant/date/total (L7).
LINE_ITEM_SUM_TOL = 0.05

_SCHEMA_VERSION = 1

# CLI providers get the same generous window statement parsing uses.
_RECEIPT_PARSE_TIMEOUT_SECONDS = 300

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_SCHEMA_BLOCK = """{
  "merchant": "<store name>",
  "date": "YYYY-MM-DD",
  "total": 12.34,
  "subtotal": 10.00,
  "tax": 1.30,
  "tip": 1.04,
  "line_items": [
    {"description": "<item>", "qty": 1, "unit_price": 10.00, "amount": 10.00}
  ],
  "confidence": 0.9
}"""

_PROMPT_INTRO = (
    "You are a receipt extraction engine. Read the receipt and reply with ONLY a "
    "JSON object (no markdown fence, no prose) with this exact shape:\n\n"
    f"{_SCHEMA_BLOCK}\n\n"
    "Rules:\n"
    '- "merchant" is the store or restaurant name.\n'
    '- "date" is the purchase date in YYYY-MM-DD.\n'
    '- "total" is the final amount charged, including tax and tip.\n'
    '- "subtotal", "tax", "tip" and "line_items" are optional — omit any you '
    "cannot read.\n"
    '- Each line item\'s "amount" is its line total. Amounts are positive numbers.\n'
    "- Do not invent values; extract only what the receipt shows."
)

# Concatenated (not str.format-ed): _PROMPT_INTRO embeds the JSON _SCHEMA_BLOCK,
# whose literal braces would make ``.format`` raise KeyError. Append the receipt
# text directly instead.
_TEXT_PROMPT_PREFIX = _PROMPT_INTRO + "\n\nReceipt text:\n"

_IMAGE_PROMPT = _PROMPT_INTRO + "\n\nThe receipt is provided as an image."


class ReceiptAIError(Exception):
    """AI receipt parsing failed (provider unavailable, bad output, or validation)."""


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract all text from a PDF; raises ``ReceiptAIError`` on failure."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as doc:
            return "\n".join(page.extract_text() or "" for page in doc.pages)
    except Exception as e:
        raise ReceiptAIError(f"Could not read the PDF: {e}") from e


def _coerce_amount(value: Any) -> float | None:
    """Best-effort positive-float coercion; None when unusable."""
    try:
        amount = round(float(value), 2)
    except (TypeError, ValueError):
        return None
    return amount


def _validate_line_items(raw_items: Any, total: float, tax: float, tip: float) -> list[dict[str, Any]] | None:
    """Return normalized line items only when they reconcile with the total.

    Line items are advisory (L7): if any item is malformed or the sum of item
    amounts plus tax and tip strays from the total by more than
    ``LINE_ITEM_SUM_TOL``, drop them entirely and keep merchant/date/total.
    """
    if not isinstance(raw_items, list) or not raw_items:
        return None
    normalized: list[dict[str, Any]] = []
    running = 0.0
    for item in raw_items:
        if not isinstance(item, dict):
            return None
        amount = _coerce_amount(item.get("amount"))
        if amount is None:
            return None
        description = item.get("description")
        if not isinstance(description, str) or not description.strip():
            return None
        entry: dict[str, Any] = {"description": description.strip(), "amount": amount}
        qty = _coerce_amount(item.get("qty"))
        if qty is not None:
            entry["qty"] = qty
        unit_price = _coerce_amount(item.get("unit_price"))
        if unit_price is not None:
            entry["unit_price"] = unit_price
        normalized.append(entry)
        running += amount
    if abs(running + tax + tip - total) > LINE_ITEM_SUM_TOL:
        return None
    return normalized


def validate_receipt_parse(data: dict[str, Any], pdf_text: str | None) -> dict[str, Any]:
    """Fail-closed validation of a model's receipt output (pure).

    Requires a non-empty merchant, a ``%Y-%m-%d`` date, and a positive total. Line
    items are advisory and dropped when they don't reconcile (see
    ``_validate_line_items``). For a text-PDF (``pdf_text`` given) the total must
    render verbatim in the extracted text (the ``_amount_in_text`` anti-hallucination
    precedent); image receipts have no text oracle and skip that check.

    Raises ``ReceiptAIError`` on any hard failure; never returns partial data.
    """
    merchant = data.get("merchant")
    if not isinstance(merchant, str) or not merchant.strip():
        raise ReceiptAIError("The receipt has no readable merchant name")

    date = data.get("date")
    if not isinstance(date, str) or not _DATE_RE.match(date):
        raise ReceiptAIError(f"The receipt date is missing or not YYYY-MM-DD: {date!r}")
    try:
        datetime.strptime(date, "%Y-%m-%d")  # noqa: DTZ007 — validity check only, result discarded
    except ValueError as e:
        raise ReceiptAIError(f"The receipt date is not a real date: {date!r}") from e

    total = _coerce_amount(data.get("total"))
    if total is None:
        raise ReceiptAIError(f"The receipt total is not a number: {data.get('total')!r}")
    if total <= 0:
        raise ReceiptAIError(f"The receipt total must be positive, got {total}")

    if pdf_text is not None and not _amount_in_text(total, pdf_text):
        raise ReceiptAIError(
            "The receipt total does not appear in the PDF text, so it can't be trusted. Nothing was saved."
        )

    result: dict[str, Any] = {
        "merchant": merchant.strip(),
        "date": date,
        "total": total,
    }
    for optional_key in ("subtotal", "tax", "tip"):
        value = _coerce_amount(data.get(optional_key))
        if value is not None:
            result[optional_key] = value

    tax = result.get("tax", 0.0)
    tip = result.get("tip", 0.0)
    line_items = _validate_line_items(data.get("line_items"), total, tax, tip)
    if line_items is not None:
        result["line_items"] = line_items

    confidence = data.get("confidence")
    if isinstance(confidence, (int, float)):
        result["confidence"] = float(confidence)

    return result


def _stamp_provenance(result: dict[str, Any], provider: str, model: str) -> dict[str, Any]:
    """Attach a provenance record to a validated parse (kin to ``build_extraction_audit``)."""
    result["provenance"] = {
        "method": "ai_receipt",
        "provider": provider,
        "model": model,
        "parsed_at": datetime.now(UTC).isoformat(),
        "schema_version": _SCHEMA_VERSION,
    }
    return result


async def _invoke_image_provider(
    provider: str,
    prompt: str,
    file_path: str,
    content_type: str,
    image_bytes: bytes,
    openai_client: OpenAIClient | None,
    model: str | None,
    reasoning_effort: str | None,
) -> str:
    """Run an image prompt through the chosen provider (L6 image matrix).

    ``model`` / ``reasoning_effort`` (``None`` = provider default) come from the
    ``document_parsing_*`` config keys; the openai path resolves the model to
    ``DEFAULT_OPENAI_CHAT_MODEL`` when unset.
    """
    if provider == "openai":
        if openai_client is None:
            raise ReceiptAIError("OpenAI is selected as the AI provider but no API key is configured")
        data_url = f"data:{content_type};base64,{base64.b64encode(image_bytes).decode()}"
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ]
        return await _openai_chat(
            openai_client, messages, model=model or DEFAULT_OPENAI_CHAT_MODEL, reasoning_effort=reasoning_effort
        )

    try:
        return await run_cli_provider(
            provider,
            prompt,
            timeout=_RECEIPT_PARSE_TIMEOUT_SECONDS,
            image_paths=[file_path],
            model=model,
            reasoning_effort=reasoning_effort,
        )
    except RuntimeError as e:
        raise ReceiptAIError(str(e)) from e


async def _openai_chat(
    openai_client: OpenAIClient,
    messages: list[dict[str, Any]],
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> str:
    """Call ``OpenAIClient.chat`` off-thread, optionally pinning the model for this call.

    The injected singleton client defaults to an embedding model, which the chat
    endpoint rejects, so receipt requests pass ``model`` through to ``chat`` as a
    per-call override. That override (and ``reasoning_effort``) touches no
    instance state — the shared client stays untouched, so a concurrent chat
    caller isn't affected.
    """
    response = await asyncio.to_thread(openai_client.chat, messages, model=model, reasoning_effort=reasoning_effort)
    if response is None:
        raise ReceiptAIError(f"The OpenAI request failed: {openai_client.last_error}")
    content = response.choices[0].message.content
    if not content:
        raise ReceiptAIError("The OpenAI reply was empty")
    return content


async def parse_receipt(
    file_path: str,
    content_type: str,
    openai_client: OpenAIClient | None = None,
) -> dict[str, Any]:
    """Parse a receipt file into validated, provenance-stamped structured data.

    Routes text-PDF vs image per the L6 matrix, resolves the provider via the
    reused ``resolve_ai_statement_provider``, and fail-closed-validates the result.
    Raises ``ReceiptAIError`` (user-presentable) on any failure.
    """
    provider = resolve_ai_statement_provider()
    if provider is None:
        raise ReceiptAIError(
            "No AI provider is available for receipt parsing — pick and connect one in Settings → Intelligence."
        )

    config = get_config()
    model = config.get("document_parsing_model")
    reasoning_effort = config.get("document_parsing_reasoning_effort")
    openai_model = model or DEFAULT_OPENAI_CHAT_MODEL

    raw = await asyncio.to_thread(_read_bytes, file_path)

    if content_type == "application/pdf":
        pdf_text = await asyncio.to_thread(_extract_pdf_text, raw)
        if len(pdf_text.strip()) < _MIN_TEXT_CHARS:
            raise ReceiptAIError(
                "This PDF has no extractable text (it may be a scan), so it can't be parsed with AI yet — "
                "take a photo of the receipt instead."
            )
        reply = await invoke_text_provider(
            provider,
            _TEXT_PROMPT_PREFIX + pdf_text,
            openai_client,
            error_cls=ReceiptAIError,
            timeout=_RECEIPT_PARSE_TIMEOUT_SECONDS,
            model=model,
            reasoning_effort=reasoning_effort,
        )
        data = extract_json(reply, error_cls=ReceiptAIError)
        result = validate_receipt_parse(data, pdf_text)
    else:
        reply = await _invoke_image_provider(
            provider, _IMAGE_PROMPT, file_path, content_type, raw, openai_client, model, reasoning_effort
        )
        data = extract_json(reply, error_cls=ReceiptAIError)
        result = validate_receipt_parse(data, None)

    # Provenance records the resolved openai chat model, else the CLI provider name.
    return _stamp_provenance(result, provider, openai_model if provider == "openai" else provider)


def _read_bytes(file_path: str) -> bytes:
    try:
        with open(file_path, "rb") as fh:
            return fh.read()
    except OSError as e:
        raise ReceiptAIError(f"Could not read the receipt file: {e}") from e
