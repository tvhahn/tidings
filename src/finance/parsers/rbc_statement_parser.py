"""RBC chequing account statement PDF parser."""

import io
import logging

import pdfplumber

from src.finance.statement_parser_base import (
    StatementParser,
    StatementParseResult,
    _detect_columns,
    _extract_statement_period,
    _parse_page,
    clean_statement_description,
)

__all__ = ["RBCChequingParser"]

logger = logging.getLogger(__name__)


class RBCChequingParser(StatementParser):
    """Parser for RBC chequing account statement PDFs."""

    institution = "RBC"
    account_type = "chequing"

    def parse(self, pdf_bytes: bytes) -> StatementParseResult:
        """Parse an RBC chequing statement PDF from raw bytes."""
        error = self.validate_pdf(pdf_bytes)
        if error:
            raise ValueError(f"PDF validation failed: {error}")

        # Set up per-run logging
        log_handler = self._setup_logging()

        try:
            pdf = pdfplumber.open(io.BytesIO(pdf_bytes))

            # Detect columns from first page with a header
            cols = None
            for page in pdf.pages:
                cols = _detect_columns(page)
                if cols:
                    break
            if not cols:
                raise ValueError("Could not find transaction table header in PDF")

            # Extract statement period
            first_page_words = pdf.pages[0].extract_words()
            period_info = _extract_statement_period(first_page_words)
            years = (period_info["start_year"], period_info["end_year"])

            # Parse each page
            all_transactions = []
            for page in pdf.pages:
                page_cols = _detect_columns(page) or cols
                txns = _parse_page(page, page_cols, years)
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
