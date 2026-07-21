"""Statement PDF parser — public entry point.

Re-exports the shared base (constants, helpers, ``StatementParser``,
``StatementParseResult``) from :mod:`src.finance.statement_parser_base` and the
concrete per-bank parsers from :mod:`src.finance.parsers`, and provides
``select_parser`` for institution auto-detection. Importing from here keeps the
historical public surface (``from src.finance.statement_parser import ...``)
stable while the modules underneath stay free of import cycles.
"""

import io
import logging

import pdfplumber

# Concrete per-bank parsers (import the base above; no cycle back to this module).
from src.finance.parsers.rbc_statement_parser import RBCChequingParser
from src.finance.parsers.simplii_statement_parser import (
    SimpliiChequingParser,
    _simplii_detect_columns,
    _simplii_extract_period,
    _simplii_parse_page,
)

# Shared base (leaf module — no dependency on concrete parsers).
from src.finance.statement_parser_base import (
    AMOUNT_RE,
    DATE_RE,
    DAY_RE,
    FULL_MONTH_MAP,
    MAX_PDF_SIZE,
    MONTH_MAP,
    MONTH_NUM_TO_ABBR,
    MONTH_NUM_TO_FULL,
    SIMPLII_MONTH_RE,
    StatementParser,
    StatementParseResult,
    _classify_amount,
    _detect_columns,
    _extract_statement_period,
    _parse_page,
    clean_statement_description,
    validate_pdf,
)

__all__ = [
    "AMOUNT_RE",
    "DATE_RE",
    "DAY_RE",
    "FULL_MONTH_MAP",
    "MAX_PDF_SIZE",
    "MONTH_MAP",
    "MONTH_NUM_TO_ABBR",
    "MONTH_NUM_TO_FULL",
    "SIMPLII_MONTH_RE",
    "RBCChequingParser",
    "SimpliiChequingParser",
    "StatementParseResult",
    "StatementParser",
    "_classify_amount",
    "_detect_columns",
    "_extract_statement_period",
    "_parse_page",
    "_simplii_detect_columns",
    "_simplii_extract_period",
    "_simplii_parse_page",
    "clean_statement_description",
    "select_parser",
    "validate_pdf",
]

logger = logging.getLogger(__name__)


def select_parser(pdf_bytes: bytes) -> StatementParser:
    """Auto-detect the institution from PDF content and return the appropriate parser.

    Checks for Simplii markers (text or header words) in the first 2 pages.
    Defaults to RBCChequingParser if no Simplii markers are found or on error.
    """
    try:
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
        for page in pdf.pages[:2]:
            text = page.extract_text() or ""
            if "simplii" in text.lower():
                pdf.close()
                return SimpliiChequingParser()
            words = page.extract_words()
            if any(w["text"] == "trans." for w in words):
                pdf.close()
                return SimpliiChequingParser()
        pdf.close()
    except Exception:
        logger.warning("parser detection failed; defaulting to RBC chequing", exc_info=True)
    return RBCChequingParser()
