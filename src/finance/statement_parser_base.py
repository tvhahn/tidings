"""Shared base for statement PDF parsers — constants, helpers, and the parser base class.

Leaf module (no dependency on concrete bank parsers) so per-bank parsers in
``src/finance/parsers/`` can import from here without forming an import cycle. The
public orchestrator ``src.finance.statement_parser`` re-exports everything here.

Extracted from dev/spikes/statement_parser/parse_rules.py. Uses pdfplumber word positions
to map amounts to columns (Withdrawals / Deposits / Balance).
"""

import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

__all__ = [
    "AMOUNT_RE",
    "DAY_RE",
    "FULL_MONTH_MAP",
    "MONTH_MAP",
    "MONTH_NUM_TO_ABBR",
    "MONTH_NUM_TO_FULL",
    "SIMPLII_MONTH_RE",
    "StatementParseResult",
    "StatementParser",
    "_classify_amount",
    "_detect_columns",
    "_extract_statement_period",
    "_parse_page",
    "clean_statement_description",
    "validate_pdf",
]

logger = logging.getLogger(__name__)

# Maximum PDF file size (10 MB)
MAX_PDF_SIZE = 10 * 1024 * 1024

# Date pattern at start of a transaction line (e.g. "30Dec", "2Jan", "13Jan")
DATE_RE = re.compile(r"^(\d{1,2})(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)$")

# Matches monetary amounts like "1,234.56" or "45.67"
AMOUNT_RE = re.compile(r"^[\d,]+\.\d{2}$")

# Simplii date patterns — month and day are separate words
SIMPLII_MONTH_RE = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)$")
DAY_RE = re.compile(r"^\d{1,2}$")

# Month abbreviation → number
MONTH_MAP = {
    "Jan": "01",
    "Feb": "02",
    "Mar": "03",
    "Apr": "04",
    "May": "05",
    "Jun": "06",
    "Jul": "07",
    "Aug": "08",
    "Sep": "09",
    "Oct": "10",
    "Nov": "11",
    "Dec": "12",
}

# Full month name → number (for header parsing)
FULL_MONTH_MAP = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}

# Reverse maps for rendering (number → name). Used by synthetic-fixture generators.
MONTH_NUM_TO_ABBR = {int(v): k for k, v in MONTH_MAP.items()}
MONTH_NUM_TO_FULL = {v: k for k, v in FULL_MONTH_MAP.items()}

# Known prefixes to strip from statement descriptions
_STRIP_PREFIXES = [
    "BillPayment",
    "InteracPurchase",
    "PayrollDeposit",
    "ATMwithdrawal",
    "POSwithdrawal",
    "Monthlyfee",
    "Safedepositboxfee",
    "InteracetransferFrom:",
    "InteracetransferTo:",
    "DirectDeposit",
    "MiscPayment",
    "MiscCredit",
    "WWW",
    "WWWBILLPYMT",
    "BILLPYMT",
]

# Prefixes that ARE the description — display name lookup when stripping leaves nothing
_PREFIX_DISPLAY_NAMES = {
    "Monthlyfee": "Monthly fee",
    "Safedepositboxfee": "Safe deposit box fee",
}


@dataclass
class StatementParseResult:
    """Result of parsing a statement PDF."""

    transactions: list[dict[str, Any]]
    metadata: dict[str, Any]
    raw_descriptions: list[str]
    cleaned_descriptions: list[str]


def clean_statement_description(raw: str) -> str:
    """Clean a raw statement description by stripping known prefixes and CamelCase-splitting.

    Examples:
        "BillPayment WestlandUtilityCo" → "Westland Utility Co"
        "ATMwithdrawal-WD402517" → "WD402517"
        "Monthlyfee" → "Monthly fee"
        "InteracPurchase SOME STORE" → "SOME STORE"
    """
    cleaned = raw.strip()

    # Strip known prefixes
    matched_prefix = None
    for prefix in _STRIP_PREFIXES:
        if cleaned.startswith(prefix):
            matched_prefix = prefix
            cleaned = cleaned[len(prefix) :].strip()
            # Remove leading dash or colon
            if cleaned.startswith(("-", ":")):
                cleaned = cleaned[1:].strip()
            break

    if not cleaned:
        # If stripping left nothing, look up a display name for the prefix
        if matched_prefix and matched_prefix in _PREFIX_DISPLAY_NAMES:
            return _PREFIX_DISPLAY_NAMES[matched_prefix]
        # Fallback: CamelCase-split the original
        cleaned = raw.strip()

    # CamelCase split: insert space before uppercase letters preceded by lowercase
    cleaned = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", cleaned)
    # CamelCase split: insert space between consecutive uppercase + uppercase-lowercase
    cleaned = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", cleaned)

    return cleaned.strip()


def validate_pdf(pdf_bytes: bytes) -> str | None:
    """Validate PDF bytes. Returns error message or None if valid."""
    if not pdf_bytes:
        return "Empty file"
    if pdf_bytes[:5] != b"%PDF-":
        return "Not a valid PDF file"
    if len(pdf_bytes) > MAX_PDF_SIZE:
        return f"File too large ({len(pdf_bytes)} bytes, max {MAX_PDF_SIZE})"
    return None


def _detect_columns(page: Any) -> dict[str, Any] | None:
    """Find the x-coordinate boundaries for each column from the header row."""
    words = page.extract_words()
    for w in words:
        if w["text"] == "Date":
            header_top = w["top"]
            header_words = [hw for hw in words if abs(hw["top"] - header_top) < 3]
            cols: dict[str, Any] = {"date_x": w["x0"]}
            for hw in header_words:
                if hw["text"] == "Description":
                    cols["desc_x"] = hw["x0"]
                elif hw["text"].startswith("Withdrawals"):
                    cols["withdrawal_right"] = hw["x1"]
                    cols["withdrawal_left"] = hw["x0"]
                elif hw["text"].startswith("Deposits"):
                    cols["deposit_right"] = hw["x1"]
                    cols["deposit_left"] = hw["x0"]
                elif hw["text"].startswith("Balance"):
                    cols["balance_right"] = hw["x1"]
                    cols["balance_left"] = hw["x0"]
            if len(cols) >= 4:
                return cols
    return None


def _classify_amount(x0: float, cols: dict[str, Any]) -> str:
    """Classify an amount word into withdrawal, deposit, or balance based on x-position."""
    wd_right = cols.get("withdrawal_right", 373)
    dep_right = cols.get("deposit_right", 465)
    bal_left = cols.get("balance_left", 520)

    wd_dep_boundary = (wd_right + cols.get("deposit_left", wd_right + 50)) / 2
    dep_bal_boundary = (dep_right + bal_left) / 2

    if x0 < wd_dep_boundary:
        return "withdrawal"
    if x0 < dep_bal_boundary:
        return "deposit"
    return "balance"


def _extract_statement_period(words: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract the statement period from header text.

    Looks for "From <month> <day>, <year> to <month> <day>, <year>".
    Returns dict with 'start_year', 'end_year', 'period_start', 'period_end'.
    """
    full_text = " ".join(w["text"] for w in words)

    # Try full date extraction: "From December 24, 2025 to January 23, 2026"
    # Note: pdfplumber may concatenate words, so handle both spaced and concatenated forms
    month_names = "|".join(FULL_MONTH_MAP.keys())
    pattern = rf"From\s*({month_names})\s*(\d{{1,2}}),?\s*(\d{{4}})\s*to\s*({month_names})\s*(\d{{1,2}}),?\s*(\d{{4}})"
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

    # Fallback: just years from concatenated text like "2025to...2026"
    m = re.search(r"(\d{4})to\w+\d{1,2},(\d{4})", full_text)
    if m:
        return {
            "start_year": int(m.group(1)),
            "end_year": int(m.group(2)),
            "period_start": None,
            "period_end": None,
        }

    m = re.search(r"(\d{4})", full_text)
    if m:
        year = int(m.group(1))
        return {
            "start_year": year,
            "end_year": year,
            "period_start": None,
            "period_end": None,
        }

    return {
        "start_year": 2026,
        "end_year": 2026,
        "period_start": None,
        "period_end": None,
    }


def _parse_page(page: Any, cols: dict[str, Any], years: tuple[int, int]) -> list[dict[str, Any]]:
    """Parse one page of transactions using word positions."""
    words = page.extract_words()

    lines = defaultdict(list)
    for w in words:
        lines[round(w["top"], 0)].append(w)

    transactions = []
    current_date = None
    current_desc_parts = []
    pending_continuation = []
    current_withdrawal = None
    current_deposit = None
    current_balance = None

    def _flush():
        nonlocal current_date, current_desc_parts, pending_continuation
        nonlocal current_withdrawal, current_deposit, current_balance
        if current_date and (current_withdrawal is not None or current_deposit is not None):
            all_parts = current_desc_parts + pending_continuation
            desc = " ".join(all_parts).strip()
            if current_withdrawal is not None:
                txn_type = "withdrawal"
                amount = current_withdrawal
            else:
                txn_type = "deposit"
                amount = current_deposit
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
        pending_continuation = []
        current_withdrawal = None
        current_deposit = None
        current_balance = None

    header_y = None
    for y in sorted(lines.keys()):
        line_words = lines[y]
        if any(w["text"] == "Date" for w in line_words):
            header_y = y
            break

    for y in sorted(lines.keys()):
        if header_y is not None and y <= header_y:
            continue

        line_words = sorted(lines[y], key=lambda w: w["x0"])
        line_words = [w for w in line_words if w["x0"] >= cols.get("date_x", 15) - 5]
        if not line_words:
            continue

        first = line_words[0]["text"]

        if first == "OpeningBalance":
            continue
        if first == "ClosingBalance":
            break
        if first.startswith("$"):
            continue
        if first.startswith("Importantinformation"):
            break

        date_match = DATE_RE.match(first)

        desc_words = []
        amounts = {}
        for w in line_words:
            if w["text"] == first and date_match:
                continue
            if AMOUNT_RE.match(w["text"]):
                cls = _classify_amount(w["x0"], cols)
                amounts[cls] = float(w["text"].replace(",", ""))
            else:
                if w["x0"] < cols.get("withdrawal_left", 300):
                    desc_words.append(w["text"])

        if date_match:
            _flush()

            day = int(date_match.group(1))
            month_abbr = date_match.group(2)
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
            if amounts.get("withdrawal") is not None or amounts.get("deposit") is not None:
                saved_continuation = pending_continuation[:]
                pending_continuation.clear()
                if current_withdrawal is not None or current_deposit is not None:
                    # Current transaction already has amounts — flush it as a sub-transaction
                    _flush()
                    current_desc_parts = saved_continuation + desc_words
                else:
                    # Date line had no amounts — this line provides them. Keep desc_parts.
                    current_desc_parts = current_desc_parts + saved_continuation + desc_words
                current_withdrawal = amounts.get("withdrawal")
                current_deposit = amounts.get("deposit")
                current_balance = amounts.get("balance")
            elif desc_words:
                pending_continuation.extend(desc_words)

    _flush()
    return transactions


class StatementParser:
    """Base class for statement parsers."""

    institution: str = ""
    account_type: str = ""

    def parse(self, pdf_bytes: bytes) -> StatementParseResult:
        raise NotImplementedError

    def validate_pdf(self, pdf_bytes: bytes) -> str | None:
        return validate_pdf(pdf_bytes)

    def _setup_logging(self) -> logging.FileHandler | None:
        """Set up per-run file logging. Returns the handler or None."""
        try:
            logs_dir = Path("logs/statements")
            logs_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005 — per-run log filename, server-local wall clock is fine
            log_file = logs_dir / f"{self.institution}_{self.account_type}_{timestamp}.log"
            fmt = "%(asctime)s %(levelname)-8s %(name)s — %(message)s"
            handler = logging.FileHandler(log_file)
            handler.setFormatter(logging.Formatter(fmt))
            handler.setLevel(logging.DEBUG)
            logging.getLogger(__name__).addHandler(handler)
            return handler
        except Exception:
            logger.debug("Could not set up per-run logging", exc_info=True)
            return None
