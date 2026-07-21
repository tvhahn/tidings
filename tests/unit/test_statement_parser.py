"""Tests for the statement PDF parser."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.finance.statement_parser import (
    RBCChequingParser,
    SimpliiChequingParser,
    _parse_page,
    _simplii_detect_columns,
    _simplii_extract_period,
    _simplii_parse_page,
    clean_statement_description,
    select_parser,
    validate_pdf,
)

# Minimal valid PDF bytes (just the header magic bytes + enough content)
MINIMAL_PDF = b"%PDF-1.4 minimal"

# ---------------------------------------------------------------------------
# Private-fixture expectations sidecar
#
# The committed test code below is deliberately value-free: it asserts only
# structural invariants (field presence, types, ISO date format, list-length
# parity, institution/account_type strings). Every REAL figure from the
# developer's own statements — PDF filenames, period boundaries, transaction
# counts, and individual amounts/dates — lives OUTSIDE the repo in a gitignored
# sidecar so nothing identifiable ships in the public release.
#
# The sidecar is ``data/raw/sample_statements/expected.json`` (the whole
# ``data/`` tree is gitignored). It is opt-in: absent on CI and on any machine
# without the real PDFs, in which case the private-fixture classes skip cleanly.
#
# Schema (recreate the file from your own statements to re-enable private runs).
# The block below is illustrative documentation of the sidecar shape, not
# executable code:
"""
{
  "<key>": {                       # key ∈ {rbc_chequing, simplii_dec, simplii_jan}
    "pdf": "<filename relative to data/raw/sample_statements/>",
    "metadata": {                  # any value may be null → assertion skipped
      "period_start": "YYYY-MM-DD" | null,
      "period_end":   "YYYY-MM-DD" | null,
      "transaction_count": <int>  | null
    },
    "spot_checks": [
      {
        "select": {"index": <int>} | {"description_contains": "<substr>"},
        "expect": {"date": "YYYY-MM-DD", "amount": <float>, "type": "deposit"|"withdrawal"},
        "expect_unique": true | false   # description_contains must match exactly one
      }
    ]
  }
}
"""
# ---------------------------------------------------------------------------

_SAMPLE_STATEMENTS_DIR = Path("data/raw/sample_statements")
_EXPECTED_SIDECAR = _SAMPLE_STATEMENTS_DIR / "expected.json"


def _load_expected() -> dict[str, Any]:
    """Load the gitignored sidecar of real expected values.

    Missing or malformed file → empty dict, so the private-fixture classes below
    skip cleanly (preserving skip-by-default behavior wherever the private data
    is absent, including CI).
    """
    try:
        return json.loads(_EXPECTED_SIDECAR.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


_EXPECTED = _load_expected()


def _expected_entry(key: str) -> dict[str, Any]:
    """Return the sidecar entry for ``key`` (``{}`` if absent)."""
    return _EXPECTED.get(key, {})


def _expected_pdf_path(key: str) -> Path | None:
    """Absolute-relative path to the private PDF for ``key``, or None if unknown."""
    pdf = _expected_entry(key).get("pdf")
    return _SAMPLE_STATEMENTS_DIR / pdf if pdf else None


def _private_fixture_missing(key: str) -> bool:
    """True when the sidecar entry or its PDF is absent → skip the private class."""
    path = _expected_pdf_path(key)
    return path is None or not path.exists()


def _assert_expected_metadata(parsed: Any, entry: dict[str, Any]) -> None:
    """Assert each non-null metadata value declared in the sidecar entry."""
    for field, value in entry.get("metadata", {}).items():
        if value is not None:
            assert parsed.metadata[field] == value, (
                f"metadata[{field!r}] expected {value!r}, got {parsed.metadata.get(field)!r}"
            )


def _run_spot_checks(parsed: Any, entry: dict[str, Any]) -> None:
    """Run the sidecar's data-driven per-transaction spot checks.

    Each check selects a transaction (by index or description substring) and
    asserts the expected fields. Failure messages carry the select criteria so a
    maintainer can tell which spot check broke.
    """
    for check in entry.get("spot_checks", []):
        select = check["select"]
        if "index" in select:
            criteria = f"index={select['index']}"
            matches = [parsed.transactions[select["index"]]]
        else:
            needle = select["description_contains"]
            criteria = f"description_contains={needle!r}"
            matches = [t for t in parsed.transactions if needle in t["description"]]

        if check.get("expect_unique"):
            assert len(matches) == 1, f"spot-check {criteria}: expected exactly one matching txn, got {len(matches)}"
        else:
            assert matches, f"spot-check {criteria}: expected at least one matching txn"

        txn = matches[0]
        for field, value in check["expect"].items():
            assert txn[field] == value, f"spot-check {criteria}: {field} expected {value!r}, got {txn.get(field)!r}"


class TestValidatePdf:
    def test_reject_empty(self) -> None:
        assert validate_pdf(b"") is not None

    def test_reject_non_pdf(self) -> None:
        assert validate_pdf(b"not a pdf file") is not None

    def test_reject_too_large(self) -> None:
        big = b"%PDF-" + b"\x00" * (10 * 1024 * 1024 + 1)
        result = validate_pdf(big)
        assert result is not None
        assert "too large" in result.lower() or "large" in result.lower()

    def test_accept_valid_pdf_header(self) -> None:
        assert validate_pdf(MINIMAL_PDF) is None


class TestCleanDescription:
    def test_bill_payment(self):
        assert clean_statement_description("BillPayment WestlandUtilityCo") == "Westland Utility Co"

    def test_atm_withdrawal(self):
        assert clean_statement_description("ATMwithdrawal-WD402517") == "WD402517"

    def test_monthly_fee(self):
        assert clean_statement_description("Monthlyfee") == "Monthly fee"

    def test_interac_purchase(self):
        assert clean_statement_description("InteracPurchase SOME STORE") == "SOME STORE"

    def test_payroll_deposit(self):
        assert clean_statement_description("PayrollDeposit EMPLOYER INC") == "EMPLOYER INC"

    def test_no_prefix(self):
        assert clean_statement_description("WALMART #1234") == "WALMART #1234"

    def test_camel_case_split(self):
        assert clean_statement_description("BillPayment WestlandUtilityCo") == "Westland Utility Co"

    def test_interac_etransfer_from(self):
        assert clean_statement_description("InteracetransferFrom: John Doe") == "John Doe"

    def test_interac_etransfer_to(self):
        assert clean_statement_description("InteracetransferTo: Jane Smith") == "Jane Smith"

    def test_preserves_all_caps(self):
        result = clean_statement_description("COSTCO WHOLESALE")
        assert result == "COSTCO WHOLESALE"

    def test_empty_after_strip_uses_original(self):
        # "Monthlyfee" with nothing after prefix → CamelCase split the original
        assert clean_statement_description("Monthlyfee") == "Monthly fee"

    def test_www_prefix(self):
        assert clean_statement_description("WWW SOME ONLINE STORE") == "SOME ONLINE STORE"


# ---------------------------------------------------------------------------
# Committed-fixture parser tests (always run — including CI)
#
# These parse the sanitized sample statements checked into tests/test_data/, so
# a parser regression is caught for everyone. Contrast the ``private_fixtures``
# classes further down, which parse the developer's real (uncommitted)
# statements under ``data/raw/`` and only run with RUN_PRIVATE_FIXTURES=1.
# Assertions favour stable sanitized facts + structural invariants over brittle
# per-line values.
# ---------------------------------------------------------------------------

_COMMITTED_DATA_DIR = Path(__file__).resolve().parent.parent / "test_data"
_RBC_STATEMENT_PDF = _COMMITTED_DATA_DIR / "rbc" / "Rbc_Chequing_2025-02-24_to_2025-03-24.pdf"
_SIMPLII_STATEMENT_PDF = _COMMITTED_DATA_DIR / "simplii" / "Simplii_Chequing_2025-02-27_to_2025-03-30.pdf"


def _assert_txn_shape(txn: dict[str, Any]) -> None:
    """A parsed statement transaction must carry these fields with sane types."""
    assert set(txn) >= {"date", "description", "amount", "type"}
    assert isinstance(txn["amount"], float)
    # Magnitude is always positive; direction is carried by ``type``.
    assert txn["amount"] > 0
    assert txn["type"] in ("withdrawal", "deposit")
    datetime.strptime(txn["date"], "%Y-%m-%d")  # noqa: DTZ007 — ISO date-format validity check, result discarded
    assert txn["description"].strip()


class TestRBCCommittedFixture:
    @pytest.fixture(scope="class")
    def parsed(self) -> Any:
        return RBCChequingParser().parse(_RBC_STATEMENT_PDF.read_bytes())

    def test_select_parser_autodetects_rbc(self) -> None:
        assert isinstance(select_parser(_RBC_STATEMENT_PDF.read_bytes()), RBCChequingParser)

    def test_transaction_count(self, parsed: Any) -> None:
        assert len(parsed.transactions) == 11

    def test_metadata(self, parsed: Any) -> None:
        assert parsed.metadata["institution"] == "RBC"
        assert parsed.metadata["account_type"] == "chequing"
        assert parsed.metadata["period_start"] == "2025-02-24"
        assert parsed.metadata["period_end"] == "2025-03-24"

    def test_every_transaction_is_well_formed(self, parsed: Any) -> None:
        for txn in parsed.transactions:
            _assert_txn_shape(txn)

    def test_has_both_deposits_and_withdrawals(self, parsed: Any) -> None:
        assert {t["type"] for t in parsed.transactions} == {"deposit", "withdrawal"}

    def test_first_transaction_is_the_payroll_deposit(self, parsed: Any) -> None:
        first = parsed.transactions[0]
        assert first["date"] == "2025-02-27"
        assert first["type"] == "deposit"
        assert first["amount"] == 1425.0


class TestSimpliiCommittedFixture:
    @pytest.fixture(scope="class")
    def parsed(self) -> Any:
        return SimpliiChequingParser().parse(_SIMPLII_STATEMENT_PDF.read_bytes())

    def test_select_parser_autodetects_simplii(self) -> None:
        assert isinstance(select_parser(_SIMPLII_STATEMENT_PDF.read_bytes()), SimpliiChequingParser)

    def test_transaction_count(self, parsed: Any) -> None:
        assert len(parsed.transactions) == 15

    def test_metadata(self, parsed: Any) -> None:
        assert parsed.metadata["institution"] == "Simplii"
        assert parsed.metadata["account_type"] == "chequing"
        assert parsed.metadata["period_start"] == "2025-02-27"
        assert parsed.metadata["period_end"] == "2025-03-30"

    def test_every_transaction_is_well_formed(self, parsed: Any) -> None:
        for txn in parsed.transactions:
            _assert_txn_shape(txn)

    def test_has_both_deposits_and_withdrawals(self, parsed: Any) -> None:
        assert {t["type"] for t in parsed.transactions} == {"deposit", "withdrawal"}

    def test_first_transaction_is_the_etransfer_deposit(self, parsed: Any) -> None:
        first = parsed.transactions[0]
        assert first["date"] == "2025-02-28"
        assert first["type"] == "deposit"
        assert first["amount"] == 820.0


@pytest.mark.private_fixtures
@pytest.mark.skipif(
    _private_fixture_missing("rbc_chequing"),
    reason="sidecar entry or RBC sample PDF missing",
)
class TestRBCChequingParser:
    KEY = "rbc_chequing"

    @pytest.fixture(scope="class")
    def entry(self) -> dict[str, Any]:
        return _expected_entry(self.KEY)

    @pytest.fixture(scope="class")
    def parsed(self, entry: dict[str, Any]) -> Any:
        pdf = _SAMPLE_STATEMENTS_DIR / entry["pdf"]
        return RBCChequingParser().parse(pdf.read_bytes())

    def test_parse_returns_result(self, parsed: Any) -> None:
        assert parsed is not None
        assert len(parsed.transactions) > 0

    def test_every_transaction_is_well_formed(self, parsed: Any) -> None:
        for txn in parsed.transactions:
            _assert_txn_shape(txn)

    def test_metadata(self, parsed: Any, entry: dict[str, Any]) -> None:
        assert parsed.metadata["institution"] == "RBC"
        assert parsed.metadata["account_type"] == "chequing"
        assert parsed.metadata["transaction_count"] == len(parsed.transactions)
        assert parsed.metadata["period_start"] is not None
        assert parsed.metadata["period_end"] is not None
        _assert_expected_metadata(parsed, entry)

    def test_descriptions_lists(self, parsed: Any) -> None:
        assert len(parsed.raw_descriptions) == len(parsed.transactions)
        assert len(parsed.cleaned_descriptions) == len(parsed.transactions)

    def test_spot_checks(self, parsed: Any, entry: dict[str, Any]) -> None:
        _run_spot_checks(parsed, entry)


class TestMultilineDescription:
    """Tests for multi-line description parsing where date+desc are on one line
    and the amount is on the NEXT line."""

    def _make_word(self, text: str, x0: float, top: float) -> dict[str, Any]:
        """Helper to create a pdfplumber word dict."""
        return {"text": text, "x0": x0, "x1": x0 + len(text) * 6, "top": top, "bottom": top + 10}

    def _make_page(self, words: list[dict[str, Any]]) -> MagicMock:
        """Create a mock pdfplumber page with extract_words returning given words."""
        page = MagicMock()
        page.extract_words.return_value = words
        return page

    def test_multiline_description_amount_on_separate_line(self) -> None:
        """When date+desc on line 1 and amount on line 2, both descriptions are preserved."""
        cols = {
            "date_x": 45,
            "desc_x": 90,
            "withdrawal_left": 300,
            "withdrawal_right": 373,
            "deposit_left": 410,
            "deposit_right": 465,
            "balance_left": 520,
            "balance_right": 600,
        }
        words = [
            # Header line
            self._make_word("Date", 45, 100),
            self._make_word("Description", 90, 100),
            self._make_word("Withdrawals", 300, 100),
            # Line 1: date + description, NO amount
            self._make_word("26Nov", 45, 200),
            self._make_word("e-Transfersent", 90, 200),
            self._make_word("WestlandHeating", 151, 200),
            # Line 2: continuation desc + amount
            self._make_word("K7QT2P", 98, 210),
            self._make_word("312.45", 346, 210),
            self._make_word("35395.44", 553, 210),
            # Another transaction: single line (date + desc + amount)
            self._make_word("27Nov", 45, 230),
            self._make_word("InteracPurchase", 90, 230),
            self._make_word("SOMESTORE", 160, 230),
            self._make_word("50.00", 346, 230),
            self._make_word("35345.44", 553, 230),
        ]

        page = self._make_page(words)
        txns = _parse_page(page, cols, (2025, 2025))

        assert len(txns) == 2

        # First transaction should have description from BOTH lines
        assert "e-Transfersent" in txns[0]["description"]
        assert "WestlandHeating" in txns[0]["description"]
        assert "K7QT2P" in txns[0]["description"]
        assert txns[0]["amount"] == 312.45
        assert txns[0]["date"] == "2025-11-26"
        assert txns[0]["type"] == "withdrawal"

        # Second transaction should be normal single-line
        assert "InteracPurchase" in txns[1]["description"]
        assert "SOMESTORE" in txns[1]["description"]
        assert txns[1]["amount"] == 50.0

    def test_single_line_transaction_still_works(self) -> None:
        """Regression: single-line transactions (date+desc+amount on same line) remain correct."""
        cols = {
            "date_x": 45,
            "desc_x": 90,
            "withdrawal_left": 300,
            "withdrawal_right": 373,
            "deposit_left": 410,
            "deposit_right": 465,
            "balance_left": 520,
            "balance_right": 600,
        }
        words = [
            self._make_word("Date", 45, 100),
            self._make_word("Description", 90, 100),
            self._make_word("Withdrawals", 300, 100),
            # Single line transaction
            self._make_word("15Jan", 45, 200),
            self._make_word("BillPayment", 90, 200),
            self._make_word("WestlandUtilityCo", 150, 200),
            self._make_word("98.75", 346, 200),
            self._make_word("41793.95", 553, 200),
        ]

        page = self._make_page(words)
        txns = _parse_page(page, cols, (2026, 2026))

        assert len(txns) == 1
        assert "BillPayment" in txns[0]["description"]
        assert "WestlandUtilityCo" in txns[0]["description"]
        assert txns[0]["amount"] == 98.75
        assert txns[0]["date"] == "2026-01-15"

    def test_multiline_deposit(self) -> None:
        """Multi-line deposit: date+desc on line 1, amount in deposit column on line 2."""
        cols = {
            "date_x": 45,
            "desc_x": 90,
            "withdrawal_left": 300,
            "withdrawal_right": 373,
            "deposit_left": 410,
            "deposit_right": 465,
            "balance_left": 520,
            "balance_right": 600,
        }
        words = [
            self._make_word("Date", 45, 100),
            self._make_word("Description", 90, 100),
            self._make_word("Deposits", 410, 100),
            # Line 1: date + description
            self._make_word("5Dec", 45, 200),
            self._make_word("PayrollDeposit", 90, 200),
            self._make_word("EMPLOYER", 160, 200),
            # Line 2: continuation + amount in deposit column
            self._make_word("INC", 98, 210),
            self._make_word("2500.00", 420, 210),
            self._make_word("37895.44", 553, 210),
        ]

        page = self._make_page(words)
        txns = _parse_page(page, cols, (2025, 2025))

        assert len(txns) == 1
        assert "PayrollDeposit" in txns[0]["description"]
        assert "EMPLOYER" in txns[0]["description"]
        assert "INC" in txns[0]["description"]
        assert txns[0]["amount"] == 2500.0
        assert txns[0]["type"] == "deposit"


class TestRBCChequingParserValidation:
    def test_reject_non_pdf(self) -> None:
        parser = RBCChequingParser()
        with pytest.raises(ValueError, match="PDF validation failed"):
            parser.parse(b"not a pdf")

    def test_reject_empty(self) -> None:
        parser = RBCChequingParser()
        with pytest.raises(ValueError, match="PDF validation failed"):
            parser.parse(b"")


# ---------------------------------------------------------------------------
# Simplii Financial parser tests
#
# The private-fixture Simplii classes (further down) resolve their PDF paths and
# expected values from the gitignored sidecar; there are no real-statement
# filename constants in committed code.
# ---------------------------------------------------------------------------


def _make_word(text: str, x0: float, top: float) -> dict[str, Any]:
    """Helper to create a pdfplumber word dict."""
    return {"text": text, "x0": x0, "x1": x0 + len(text) * 6, "top": top, "bottom": top + 10}


def _make_page(words: list[dict[str, Any]]) -> MagicMock:
    """Create a mock pdfplumber page with extract_words returning given words."""
    page = MagicMock()
    page.extract_words.return_value = words
    return page


def _simplii_header_words(top: float = 220.5) -> list[dict[str, Any]]:
    """Build standard Simplii header words for mock pages."""
    return [
        _make_word("trans.", 16, top),
        _make_word("eff.", 66, top),
        _make_word("transaction", 116, top),
        _make_word("funds", 410, top + 1),
        _make_word("out", 437, top + 1),
        _make_word("funds", 495, top + 1),
        _make_word("in", 522, top + 1),
        _make_word("balance", 568, top + 1),
        _make_word("date", 16, top + 11.5),
        _make_word("date", 66, top + 11.5),
    ]


def _simplii_cols() -> dict[str, float]:
    """Standard column dict matching the Simplii header."""
    return {
        "trans_date_x": 16,
        "eff_date_x": 66,
        "desc_x": 116,
        "withdrawal_left": 410,
        "withdrawal_right": 451,
        "deposit_left": 495,
        "deposit_right": 530,
        "balance_left": 568,
        "balance_right": 603,
        "header_bottom": 232,
    }


class TestSimpliiColumnDetection:
    def test_detect_simplii_columns(self):
        words = _simplii_header_words()
        page = _make_page(words)
        cols = _simplii_detect_columns(page)
        assert cols is not None
        assert cols["trans_date_x"] == 16
        assert cols["eff_date_x"] == 66
        assert cols["desc_x"] == 116
        assert "withdrawal_left" in cols
        assert "withdrawal_right" in cols
        assert "deposit_left" in cols
        assert "deposit_right" in cols
        assert "balance_left" in cols

    def test_returns_none_for_rbc_page(self):
        words = [
            _make_word("Date", 45, 100),
            _make_word("Description", 90, 100),
            _make_word("Withdrawals", 300, 100),
        ]
        page = _make_page(words)
        cols = _simplii_detect_columns(page)
        assert cols is None

    def test_header_bottom_from_date_subheader(self):
        words = _simplii_header_words(top=120.5)
        page = _make_page(words)
        cols = _simplii_detect_columns(page)
        assert cols is not None
        assert cols["header_bottom"] == 132.0


class TestSimpliiPeriodExtraction:
    def test_standard_period(self):
        words = [
            {"text": "statement"},
            {"text": "period:"},
            {"text": "September"},
            {"text": "15,"},
            {"text": "2025"},
            {"text": "-"},
            {"text": "October"},
            {"text": "14,"},
            {"text": "2025"},
        ]
        result = _simplii_extract_period(words)
        assert result["start_year"] == 2025
        assert result["end_year"] == 2025
        assert result["period_start"] == "2025-09-15"
        assert result["period_end"] == "2025-10-14"

    def test_cross_year_period(self):
        words = [
            {"text": "statement"},
            {"text": "period:"},
            {"text": "December"},
            {"text": "06,"},
            {"text": "2025"},
            {"text": "-"},
            {"text": "January"},
            {"text": "05,"},
            {"text": "2026"},
        ]
        result = _simplii_extract_period(words)
        assert result["start_year"] == 2025
        assert result["end_year"] == 2026
        assert result["period_start"] == "2025-12-06"
        assert result["period_end"] == "2026-01-05"

    def test_fallback_year_only(self):
        words = [{"text": "foo"}, {"text": "2025"}, {"text": "bar"}]
        result = _simplii_extract_period(words)
        assert result["start_year"] == 2025
        assert result["end_year"] == 2025
        assert result["period_start"] is None


class TestSimpliiPageParsing:
    def test_basic_withdrawal(self):
        cols = _simplii_cols()
        words = [
            *_simplii_header_words(),
            # Transaction: Dec 01 (eff: Nov 20) withdrawal 94.20
            _make_word("Dec", 16, 300),
            _make_word("01", 37, 300),
            _make_word("Nov", 66, 300),
            _make_word("20", 87, 300),
            _make_word("SOME", 116, 300),
            _make_word("STORE", 150, 300),
            _make_word("94.20", 426, 301),
            _make_word("48,006.64", 559, 299),
        ]
        page = _make_page(words)
        txns = _simplii_parse_page(page, cols, (2025, 2025))
        assert len(txns) == 1
        assert txns[0]["date"] == "2025-11-20"  # Uses eff. date
        assert txns[0]["description"] == "SOME STORE"
        assert txns[0]["amount"] == 94.20
        assert txns[0]["type"] == "withdrawal"
        assert txns[0]["balance"] == 48006.64

    def test_basic_deposit(self):
        cols = _simplii_cols()
        words = [
            *_simplii_header_words(),
            _make_word("Nov", 16, 300),
            _make_word("15", 37, 300),
            _make_word("Nov", 66, 300),
            _make_word("15", 87, 300),
            _make_word("NORTHWIND", 116, 300),
            _make_word("CONSULTING", 180, 300),
            _make_word("3,200.00", 489, 300),
            _make_word("48,100.84", 559, 299),
        ]
        page = _make_page(words)
        txns = _simplii_parse_page(page, cols, (2025, 2025))
        assert len(txns) == 1
        assert txns[0]["date"] == "2025-11-15"
        assert txns[0]["description"] == "NORTHWIND CONSULTING"
        assert txns[0]["amount"] == 3200.00
        assert txns[0]["type"] == "deposit"

    def test_skip_balance_forward(self):
        cols = _simplii_cols()
        words = [
            *_simplii_header_words(),
            # BALANCE FORWARD line (should be skipped)
            _make_word("Nov", 16, 250),
            _make_word("27", 37, 250),
            _make_word("Nov", 66, 250),
            _make_word("27", 87, 250),
            _make_word("BALANCE", 116, 250),
            _make_word("FORWARD", 165, 250),
            _make_word("40,349.07", 559, 249),
            # Real transaction
            _make_word("Nov", 16, 300),
            _make_word("28", 37, 300),
            _make_word("Nov", 66, 300),
            _make_word("28", 87, 300),
            _make_word("TEST", 116, 300),
            _make_word("50.00", 503, 300),
            _make_word("40,399.07", 559, 299),
        ]
        page = _make_page(words)
        txns = _simplii_parse_page(page, cols, (2025, 2025))
        assert len(txns) == 1
        assert txns[0]["description"] == "TEST"

    def test_stop_at_end_of_transactions(self):
        cols = _simplii_cols()
        words = [
            *_simplii_header_words(),
            # Transaction
            _make_word("Dec", 16, 300),
            _make_word("01", 37, 300),
            _make_word("Dec", 66, 300),
            _make_word("01", 87, 300),
            _make_word("STORE", 116, 300),
            _make_word("50.00", 426, 301),
            _make_word("1,000.00", 559, 299),
            # End of transactions
            _make_word("end", 264, 380),
            _make_word("of", 284, 380),
            _make_word("transactions", 295, 380),
            # Total funds (should not be parsed)
            _make_word("total", 15, 393),
            _make_word("funds", 37, 393),
            _make_word("out", 64, 393),
            _make_word("50.00", 412, 393),
        ]
        page = _make_page(words)
        txns = _simplii_parse_page(page, cols, (2025, 2025))
        assert len(txns) == 1

    def test_skip_total_closing_page_lines(self):
        cols = _simplii_cols()
        words = [
            *_simplii_header_words(),
            _make_word("Dec", 16, 300),
            _make_word("01", 37, 300),
            _make_word("Dec", 66, 300),
            _make_word("01", 87, 300),
            _make_word("STORE", 116, 300),
            _make_word("50.00", 426, 301),
            _make_word("1,000.00", 559, 299),
            # continuation line (should be skipped)
            _make_word("transactions", 213, 744),
            _make_word("continue", 270, 744),
            _make_word("in", 311, 744),
            _make_word("the", 321, 744),
            _make_word("next", 338, 744),
            _make_word("page", 359, 744),
            # page line
            _make_word("page", 15, 755),
            _make_word("1", 46, 755),
            _make_word("of", 71, 755),
            _make_word("3", 88, 755),
        ]
        page = _make_page(words)
        txns = _simplii_parse_page(page, cols, (2025, 2025))
        assert len(txns) == 1
        assert txns[0]["description"] == "STORE"

    def test_etransfer_receive_as_deposit(self):
        cols = _simplii_cols()
        words = [
            *_simplii_header_words(),
            _make_word("Dec", 16, 300),
            _make_word("08", 37, 300),
            _make_word("Dec", 66, 300),
            _make_word("08", 87, 300),
            _make_word("INTERAC", 116, 300),
            _make_word("E-TRANSFER", 163, 300),
            _make_word("RECEIVE", 229, 300),
            _make_word("SAM", 276, 300),
            _make_word("WHITTAKER", 305, 300),
            _make_word("50.00", 503, 300),
            _make_word("43,611.41", 559, 299),
        ]
        page = _make_page(words)
        txns = _simplii_parse_page(page, cols, (2025, 2025))
        assert len(txns) == 1
        assert txns[0]["type"] == "deposit"
        assert txns[0]["amount"] == 50.0
        assert txns[0]["description"] == "INTERAC E-TRANSFER RECEIVE SAM WHITTAKER"

    def test_etransfer_send_as_withdrawal(self):
        cols = _simplii_cols()
        words = [
            *_simplii_header_words(),
            _make_word("Dec", 16, 300),
            _make_word("31", 37, 300),
            _make_word("Dec", 66, 300),
            _make_word("31", 87, 300),
            _make_word("INTERAC", 116, 300),
            _make_word("E-TRANSFER", 163, 300),
            _make_word("SEND", 229, 300),
            _make_word("Maggie", 260, 300),
            _make_word("Lee", 298, 300),
            _make_word("120.00", 426, 301),
            _make_word("55,654.11", 559, 299),
        ]
        page = _make_page(words)
        txns = _simplii_parse_page(page, cols, (2025, 2025))
        assert len(txns) == 1
        assert txns[0]["type"] == "withdrawal"
        assert txns[0]["amount"] == 120.0

    def test_cross_year_date_assignment(self):
        """In a cross-year statement, Oct/Nov/Dec dates use start_year, Jan dates use end_year."""
        cols = _simplii_cols()
        words = [
            *_simplii_header_words(),
            # Dec 12 → should use start_year (2025)
            _make_word("Dec", 16, 300),
            _make_word("13", 37, 300),
            _make_word("Dec", 66, 300),
            _make_word("12", 87, 300),
            _make_word("STORE", 116, 300),
            _make_word("43.10", 426, 301),
            _make_word("55,729.11", 559, 299),
            # Jan 02 → should use end_year (2026)
            _make_word("Jan", 16, 350),
            _make_word("02", 37, 350),
            _make_word("Jan", 66, 350),
            _make_word("02", 87, 350),
            _make_word("ANOTHER", 116, 350),
            _make_word("0.01", 432, 351),
            _make_word("55,654.10", 559, 349),
        ]
        page = _make_page(words)
        txns = _simplii_parse_page(page, cols, (2025, 2026))
        assert len(txns) == 2
        assert txns[0]["date"] == "2025-12-12"
        assert txns[1]["date"] == "2026-01-02"

    def test_uses_eff_date_not_trans_date(self):
        """Parser should use the eff. date column, not the trans. date column."""
        cols = _simplii_cols()
        words = [
            *_simplii_header_words(),
            # trans. date: Dec 02, eff. date: Dec 01
            _make_word("Dec", 16, 300),
            _make_word("02", 37, 300),
            _make_word("Dec", 66, 300),
            _make_word("01", 87, 300),
            _make_word("STORE", 116, 300),
            _make_word("390.00", 420, 301),
            _make_word("47,620.09", 559, 299),
        ]
        page = _make_page(words)
        txns = _simplii_parse_page(page, cols, (2025, 2025))
        assert len(txns) == 1
        assert txns[0]["date"] == "2025-12-01"  # eff. date, not trans. date


@pytest.mark.private_fixtures
@pytest.mark.skipif(
    _private_fixture_missing("simplii_dec"),
    reason="sidecar entry or Simplii Dec sample PDF missing",
)
class TestSimpliiChequingParserDec:
    KEY = "simplii_dec"

    @pytest.fixture(scope="class")
    def entry(self) -> dict[str, Any]:
        return _expected_entry(self.KEY)

    @pytest.fixture(scope="class")
    def parsed(self, entry: dict[str, Any]) -> Any:
        pdf = _SAMPLE_STATEMENTS_DIR / entry["pdf"]
        return SimpliiChequingParser().parse(pdf.read_bytes())

    def test_transaction_count(self, parsed: Any, entry: dict[str, Any]) -> None:
        expected = entry.get("metadata", {}).get("transaction_count")
        if expected is None:
            pytest.skip("no expected transaction_count in sidecar")
        assert len(parsed.transactions) == expected

    def test_every_transaction_is_well_formed(self, parsed: Any) -> None:
        for txn in parsed.transactions:
            _assert_txn_shape(txn)

    def test_metadata(self, parsed: Any, entry: dict[str, Any]) -> None:
        assert parsed.metadata["institution"] == "Simplii"
        assert parsed.metadata["account_type"] == "chequing"
        _assert_expected_metadata(parsed, entry)

    def test_descriptions_lists(self, parsed: Any) -> None:
        assert len(parsed.raw_descriptions) == len(parsed.transactions)
        assert len(parsed.cleaned_descriptions) == len(parsed.transactions)

    def test_etransfer_receive_is_a_deposit(self, parsed: Any) -> None:
        """Structural: every E-transfer receive is classified as a deposit."""
        etransfers = [t for t in parsed.transactions if "E-TRANSFER RECEIVE" in t["description"]]
        assert etransfers
        for et in etransfers:
            assert et["type"] == "deposit"

    def test_spot_checks(self, parsed: Any, entry: dict[str, Any]) -> None:
        _run_spot_checks(parsed, entry)


@pytest.mark.private_fixtures
@pytest.mark.skipif(
    _private_fixture_missing("simplii_jan"),
    reason="sidecar entry or Simplii Jan sample PDF missing",
)
class TestSimpliiChequingParserJan:
    KEY = "simplii_jan"

    @pytest.fixture(scope="class")
    def entry(self) -> dict[str, Any]:
        return _expected_entry(self.KEY)

    @pytest.fixture(scope="class")
    def parsed(self, entry: dict[str, Any]) -> Any:
        pdf = _SAMPLE_STATEMENTS_DIR / entry["pdf"]
        return SimpliiChequingParser().parse(pdf.read_bytes())

    def test_transaction_count(self, parsed: Any, entry: dict[str, Any]) -> None:
        expected = entry.get("metadata", {}).get("transaction_count")
        if expected is None:
            pytest.skip("no expected transaction_count in sidecar")
        assert len(parsed.transactions) == expected

    def test_metadata_cross_year(self, parsed: Any, entry: dict[str, Any]) -> None:
        assert parsed.metadata["institution"] == "Simplii"
        _assert_expected_metadata(parsed, entry)

    def test_dec_dates_use_2025(self, parsed: Any) -> None:
        """Dec dates in a Dec 2025 - Jan 2026 statement should use year 2025."""
        dec_txns = [t for t in parsed.transactions if t["date"].startswith("2025-12")]
        assert len(dec_txns) >= 1

    def test_jan_dates_use_2026(self, parsed: Any) -> None:
        """Jan dates in a Dec 2025 - Jan 2026 statement should use year 2026."""
        jan_txns = [t for t in parsed.transactions if t["date"].startswith("2026-01")]
        assert len(jan_txns) >= 1

    def test_etransfer_send_is_a_withdrawal(self, parsed: Any) -> None:
        """Structural: every E-transfer send is classified as a withdrawal."""
        sends = [t for t in parsed.transactions if "E-TRANSFER SEND" in t["description"]]
        assert sends
        for send in sends:
            assert send["type"] == "withdrawal"

    def test_spot_checks(self, parsed: Any, entry: dict[str, Any]) -> None:
        _run_spot_checks(parsed, entry)


class TestSelectParser:
    def test_simplii_pdf_returns_simplii_parser(self):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "your no fee chequing account\nSimplii Financial"
        mock_page.extract_words.return_value = []

        with patch("src.finance.statement_parser.pdfplumber") as mock_pdfplumber:
            mock_pdf = MagicMock()
            mock_pdf.pages = [mock_page]
            mock_pdfplumber.open.return_value = mock_pdf
            parser = select_parser(b"%PDF-1.4 test")
            assert isinstance(parser, SimpliiChequingParser)

    def test_non_simplii_returns_rbc(self):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Royal Bank of Canada"
        mock_page.extract_words.return_value = [
            {"text": "Date", "x0": 45, "top": 100},
        ]

        with patch("src.finance.statement_parser.pdfplumber") as mock_pdfplumber:
            mock_pdf = MagicMock()
            mock_pdf.pages = [mock_page]
            mock_pdfplumber.open.return_value = mock_pdf
            parser = select_parser(b"%PDF-1.4 test")
            assert isinstance(parser, RBCChequingParser)

    def test_error_returns_rbc(self):
        with patch("src.finance.statement_parser.pdfplumber") as mock_pdfplumber:
            mock_pdfplumber.open.side_effect = Exception("bad pdf")
            parser = select_parser(b"garbage")
            assert isinstance(parser, RBCChequingParser)

    def test_trans_dot_header_detected(self):
        """Simplii header with 'trans.' word triggers Simplii parser."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "some other text"
        mock_page.extract_words.return_value = [
            {"text": "trans.", "x0": 16, "top": 220},
        ]

        with patch("src.finance.statement_parser.pdfplumber") as mock_pdfplumber:
            mock_pdf = MagicMock()
            mock_pdf.pages = [mock_page]
            mock_pdfplumber.open.return_value = mock_pdf
            parser = select_parser(b"%PDF-1.4 test")
            assert isinstance(parser, SimpliiChequingParser)
