"""Simplii Financial chequing account statement PDF parser."""

import io
import logging
import re
from collections import defaultdict
from typing import Any

import pdfplumber

from src.finance.statement_parser_base import (
    AMOUNT_RE,
    DAY_RE,
    FULL_MONTH_MAP,
    MONTH_MAP,
    SIMPLII_MONTH_RE,
    StatementParser,
    StatementParseResult,
    _classify_amount,
    clean_statement_description,
)

# The `_simplii_*` page-level helpers are re-exported through the
# `statement_parser` aggregator and exercised directly by the parser test suite;
# the underscore keeps them out of the general parser interface.
__all__ = [
    "SimpliiChequingParser",
    "_simplii_detect_columns",
    "_simplii_extract_period",
    "_simplii_parse_page",
]

logger = logging.getLogger(__name__)


def _simplii_detect_columns(page: Any) -> dict[str, Any] | None:
    """Find column boundaries from Simplii header row.

    Simplii headers use: trans. | eff. | transaction | funds out | funds in | balance
    spread across two sub-lines (main header + "date" / "date" below).
    """
    words = page.extract_words()
    for w in words:
        if w["text"] == "trans.":
            header_top = w["top"]
            # Header spans ~2 lines (trans./eff./transaction at top, funds/out/in/balance ~1pt below)
            header_words = [hw for hw in words if abs(hw["top"] - header_top) < 3]
            cols: dict[str, Any] = {"trans_date_x": w["x0"]}

            for hw in header_words:
                if hw["text"] == "eff.":
                    cols["eff_date_x"] = hw["x0"]
                elif hw["text"] == "transaction":
                    cols["desc_x"] = hw["x0"]
                elif hw["text"] == "balance" and hw["x0"] > 500:
                    cols["balance_left"] = hw["x0"]
                    cols["balance_right"] = hw["x1"]

            # Pair "funds" words with "out" / "in" to identify withdrawal / deposit columns
            funds_words = sorted(
                [hw for hw in header_words if hw["text"] == "funds"],
                key=lambda h: h["x0"],
            )
            out_word = next((hw for hw in header_words if hw["text"] == "out"), None)
            in_word = next(
                (hw for hw in header_words if hw["text"] == "in" and hw["x0"] > 450),
                None,
            )

            if len(funds_words) >= 2 and out_word:
                cols["withdrawal_left"] = funds_words[0]["x0"]
                cols["withdrawal_right"] = out_word["x1"]
            if len(funds_words) >= 2 and in_word:
                cols["deposit_left"] = funds_words[1]["x0"]
                cols["deposit_right"] = in_word["x1"]

            # Determine header_bottom from "date" sub-header line
            date_words = [hw for hw in words if hw["text"] == "date" and 0 < hw["top"] - header_top < 15]
            if date_words:
                cols["header_bottom"] = max(hw["top"] for hw in date_words)
            else:
                cols["header_bottom"] = header_top

            if len(cols) >= 7:  # trans_date_x, eff_date_x, desc_x, wd l/r, dep l/r, bal l/r, header_bottom
                return cols
    return None


def _simplii_extract_period(words: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse Simplii period: 'statement period: November 27, 2025 - December 29, 2025'."""
    full_text = " ".join(w["text"] for w in words)
    month_names = "|".join(FULL_MONTH_MAP.keys())
    pattern = (
        rf"statement\s+period:\s*({month_names})\s+(\d{{1,2}}),?\s+(\d{{4}})"
        rf"\s*-\s*({month_names})\s+(\d{{1,2}}),?\s+(\d{{4}})"
    )
    m = re.search(pattern, full_text, re.IGNORECASE)
    if m:
        start_month = FULL_MONTH_MAP[m.group(1)]
        start_day = int(m.group(2))
        start_year = int(m.group(3))
        end_month = FULL_MONTH_MAP[m.group(4)]
        end_day = int(m.group(5))
        end_year = int(m.group(6))
        return {
            "start_year": start_year,
            "end_year": end_year,
            "period_start": f"{start_year}-{start_month:02d}-{start_day:02d}",
            "period_end": f"{end_year}-{end_month:02d}-{end_day:02d}",
        }

    # Fallback: extract any year
    m = re.search(r"(\d{4})", full_text)
    if m:
        year = int(m.group(1))
        return {"start_year": year, "end_year": year, "period_start": None, "period_end": None}
    return {"start_year": 2026, "end_year": 2026, "period_start": None, "period_end": None}


def _simplii_parse_page(page: Any, cols: dict[str, Any], years: tuple[int, int]) -> list[dict[str, Any]]:
    """Parse one page of Simplii transactions using word positions."""
    words = page.extract_words()

    # Group words by top position, merging lines within 3pt tolerance.
    # Simplii PDFs render amounts ~1pt above/below the text on the same visual line.
    raw_lines: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for w in words:
        raw_lines[round(w["top"], 0)].append(w)

    lines: dict[float, list[dict[str, Any]]] = {}
    for top in sorted(raw_lines.keys()):
        merged = False
        for existing_top in sorted(lines.keys()):
            if abs(top - existing_top) <= 3:
                lines[existing_top].extend(raw_lines[top])
                merged = True
                break
        if not merged:
            lines[top] = list(raw_lines[top])

    eff_date_x = cols["eff_date_x"]
    desc_x = cols["desc_x"]
    header_bottom = cols.get("header_bottom", 0)

    # Column boundaries
    eff_boundary = eff_date_x - 5
    desc_boundary = desc_x - 5
    amount_boundary = cols.get("withdrawal_left", 400) - 10

    transactions: list[dict[str, Any]] = []
    current_date: str | None = None
    current_desc_parts: list[str] = []
    current_withdrawal: float | None = None
    current_deposit: float | None = None
    current_balance: float | None = None

    def _flush():
        nonlocal current_date, current_desc_parts
        nonlocal current_withdrawal, current_deposit, current_balance
        if current_date and (current_withdrawal is not None or current_deposit is not None):
            desc = " ".join(current_desc_parts).strip()
            if current_withdrawal is not None:
                txn_type = "withdrawal"
                amount = current_withdrawal
            else:
                txn_type = "deposit"
                amount = current_deposit  # type: ignore[assignment]
            transactions.append(
                {
                    "date": current_date,
                    "description": desc,
                    "amount": amount,
                    "type": txn_type,
                    "balance": current_balance,
                }
            )
        current_desc_parts = []
        current_withdrawal = None
        current_deposit = None
        current_balance = None

    for y in sorted(lines.keys()):
        if y <= header_bottom:
            continue

        line_words = sorted(lines[y], key=lambda w: w["x0"])
        if not line_words:
            continue

        # Skip / stop patterns
        line_text_lower = " ".join(w["text"].lower() for w in line_words)

        if "balance forward" in line_text_lower:
            continue
        if "end of transactions" in line_text_lower:
            _flush()
            break
        if "transactions continue" in line_text_lower:
            _flush()
            break

        first_word_lower = line_words[0]["text"].lower()
        if first_word_lower in ("total", "closing", "page"):
            _flush()
            break

        # Classify words by column position
        eff_date_words: list[str] = []
        desc_words: list[str] = []
        amounts: dict[str, float] = {}

        for w in line_words:
            x0 = w["x0"]
            text = w["text"]

            if AMOUNT_RE.match(text):
                cls = _classify_amount(x0, cols)
                amounts[cls] = float(text.replace(",", ""))
            elif x0 < eff_boundary:
                pass  # trans. date — ignored, we use eff. date
            elif x0 < desc_boundary:
                eff_date_words.append(text)
            elif x0 < amount_boundary:
                desc_words.append(text)

        # Check for new transaction (eff. date pattern: month + day)
        has_date = (
            len(eff_date_words) >= 2 and SIMPLII_MONTH_RE.match(eff_date_words[0]) and DAY_RE.match(eff_date_words[1])
        )

        if has_date:
            _flush()

            month_abbr = eff_date_words[0]
            day = int(eff_date_words[1])
            month_num = int(MONTH_MAP[month_abbr])

            start_year, end_year = years
            if start_year != end_year and month_num >= 10:
                year = start_year
            else:
                year = end_year

            current_date = f"{year}-{month_num:02d}-{day:02d}"
            current_desc_parts = desc_words
            current_withdrawal = amounts.get("withdrawal")
            current_deposit = amounts.get("deposit")
            current_balance = amounts.get("balance")
        else:
            # Continuation line
            if desc_words:
                current_desc_parts.extend(desc_words)
            if amounts.get("withdrawal") is not None and current_withdrawal is None:
                current_withdrawal = amounts["withdrawal"]
            if amounts.get("deposit") is not None and current_deposit is None:
                current_deposit = amounts["deposit"]
            if amounts.get("balance") is not None:
                current_balance = amounts["balance"]

    _flush()
    return transactions


class SimpliiChequingParser(StatementParser):
    """Parser for Simplii Financial chequing account statement PDFs."""

    institution = "Simplii"
    account_type = "chequing"

    def parse(self, pdf_bytes: bytes) -> StatementParseResult:
        """Parse a Simplii chequing statement PDF from raw bytes."""
        error = self.validate_pdf(pdf_bytes)
        if error:
            raise ValueError(f"PDF validation failed: {error}")

        log_handler = self._setup_logging()

        try:
            pdf = pdfplumber.open(io.BytesIO(pdf_bytes))

            # Detect columns from first page with a Simplii header
            cols = None
            for page in pdf.pages:
                cols = _simplii_detect_columns(page)
                if cols:
                    break
            if not cols:
                raise ValueError("Could not find Simplii transaction table header in PDF")

            # Extract statement period
            first_page_words = pdf.pages[0].extract_words()
            period_info = _simplii_extract_period(first_page_words)
            years = (period_info["start_year"], period_info["end_year"])

            # Parse each page
            all_transactions: list[dict[str, Any]] = []
            for page in pdf.pages:
                page_cols = _simplii_detect_columns(page) or cols
                txns = _simplii_parse_page(page, page_cols, years)
                all_transactions.extend(txns)

            pdf.close()

            # Build raw and cleaned descriptions
            raw_descriptions = [t["description"] for t in all_transactions]
            cleaned_descriptions = [clean_statement_description(d) for d in raw_descriptions]

            metadata = {
                "institution": self.institution,
                "account_type": self.account_type,
                "period_start": period_info.get("period_start"),
                "period_end": period_info.get("period_end"),
                "transaction_count": len(all_transactions),
            }

            logger.info(
                "Parsed %d transactions from %s %s statement (period: %s to %s)",
                len(all_transactions),
                self.institution,
                self.account_type,
                period_info.get("period_start"),
                period_info.get("period_end"),
            )

            return StatementParseResult(
                transactions=all_transactions,
                metadata=metadata,
                raw_descriptions=raw_descriptions,
                cleaned_descriptions=cleaned_descriptions,
            )
        finally:
            if log_handler:
                logging.getLogger(__name__).removeHandler(log_handler)
                log_handler.close()
