"""Tests for statement import dedup fix — same-day duplicate transactions."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.finance.statement_parser import select_parser
from src.finance.transaction_db import TransactionsDB

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "test_data" / "simplii"
PDF_PATH = FIXTURE_DIR / "Simplii_Chequing_2025-02-27_to_2025-03-30.pdf"
EXPECTED_PATH = FIXTURE_DIR / "Simplii_Chequing_2025-02-27_to_2025-03-30.json"


@pytest.fixture(scope="module")
def pdf_bytes() -> bytes:
    return PDF_PATH.read_bytes()


@pytest.fixture(scope="module")
def parse_result(pdf_bytes: bytes) -> Any:
    parser = select_parser(pdf_bytes)
    return parser.parse(pdf_bytes)


@pytest.fixture(scope="module")
def expected() -> dict[str, Any]:
    return json.loads(EXPECTED_PATH.read_text())


@pytest.fixture
def db() -> TransactionsDB:
    dyn = MagicMock()
    return TransactionsDB(dyn)


@pytest.fixture
def base_txn() -> dict[str, Any]:
    return {
        "forwarded_to": "test@example.com",
        "date": "2025-03-10",
        "amount": 200.00,
        "company": "Northside Sports Club",
        "institution": "Simplii",
        "transaction_type": "withdrawal",
        "category": "charitable giving",
        "statement_source": "Simplii_Chequing_2025-03",
        "raw_description": "INTERAC E-TRANSFER SEND Northside Sports Club",
    }


# ---------------------------------------------------------------------------
# TestSimpliiPdfFixture — Parser correctness against real PDF
# ---------------------------------------------------------------------------
class TestSimpliiPdfFixture:
    def test_transaction_count(self, parse_result: Any, expected: dict[str, Any]) -> None:
        assert len(parse_result.transactions) == expected["metadata"]["transaction_count"]

    def test_metadata(self, parse_result: Any, expected: dict[str, Any]) -> None:
        m = parse_result.metadata
        e = expected["metadata"]
        assert m["institution"] == e["institution"]
        assert m["account_type"] == e["account_type"]
        assert m["period_start"] == e["period_start"]
        assert m["period_end"] == e["period_end"]

    def test_duplicate_etransfers_both_parsed(self, parse_result: Any) -> None:
        """Both $200 e-transfers to the same recipient appear with different balances."""
        recipient_txns = [t for t in parse_result.transactions if "Northside Sports Club" in t.get("description", "")]
        assert len(recipient_txns) == 2
        assert recipient_txns[0]["amount"] == 200.00
        assert recipient_txns[1]["amount"] == 200.00
        # Different running balances prove they're distinct transactions
        assert recipient_txns[0]["balance"] != recipient_txns[1]["balance"]

    def test_all_transactions_match_expected(self, parse_result: Any, expected: dict[str, Any]) -> None:
        for i, (actual, exp) in enumerate(zip(parse_result.transactions, expected["transactions"], strict=True)):
            assert actual["date"] == exp["date"], f"tx[{i}] date mismatch"
            assert actual["amount"] == pytest.approx(exp["amount"]), f"tx[{i}] amount"
            assert actual["type"] == exp["type"], f"tx[{i}] type mismatch"
            assert actual["balance"] == pytest.approx(exp["balance"]), f"tx[{i}] balance"

    def test_total_funds_in_and_out(self, parse_result: Any, expected: dict[str, Any]) -> None:
        withdrawals = sum(t["amount"] for t in parse_result.transactions if t["type"] == "withdrawal")
        deposits = sum(t["amount"] for t in parse_result.transactions if t["type"] == "deposit")
        assert withdrawals == pytest.approx(expected["totals"]["funds_out"])
        assert deposits == pytest.approx(expected["totals"]["funds_in"])


# ---------------------------------------------------------------------------
# TestRbcPdfFixture — Parser correctness against synthetic RBC PDF
# ---------------------------------------------------------------------------
RBC_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "test_data" / "rbc"
RBC_PDF_PATH = RBC_FIXTURE_DIR / "Rbc_Chequing_2025-02-24_to_2025-03-24.pdf"
RBC_EXPECTED_PATH = RBC_FIXTURE_DIR / "Rbc_Chequing_2025-02-24_to_2025-03-24.json"


@pytest.fixture(scope="module")
def rbc_pdf_bytes() -> bytes:
    return RBC_PDF_PATH.read_bytes()


@pytest.fixture(scope="module")
def rbc_parse_result(rbc_pdf_bytes: bytes) -> Any:
    parser = select_parser(rbc_pdf_bytes)
    return parser.parse(rbc_pdf_bytes)


@pytest.fixture(scope="module")
def rbc_expected() -> dict[str, Any]:
    return json.loads(RBC_EXPECTED_PATH.read_text())


class TestRbcPdfFixture:
    def test_transaction_count(self, rbc_parse_result: Any, rbc_expected: dict[str, Any]) -> None:
        assert len(rbc_parse_result.transactions) == rbc_expected["metadata"]["transaction_count"]

    def test_metadata(self, rbc_parse_result: Any, rbc_expected: dict[str, Any]) -> None:
        m = rbc_parse_result.metadata
        e = rbc_expected["metadata"]
        assert m["institution"] == e["institution"]
        assert m["account_type"] == e["account_type"]
        assert m["period_start"] == e["period_start"]
        assert m["period_end"] == e["period_end"]

    def test_all_transactions_match_expected(self, rbc_parse_result: Any, rbc_expected: dict[str, Any]) -> None:
        for i, (actual, exp) in enumerate(
            zip(rbc_parse_result.transactions, rbc_expected["transactions"], strict=True)
        ):
            assert actual["date"] == exp["date"], f"tx[{i}] date mismatch"
            assert actual["amount"] == pytest.approx(exp["amount"]), f"tx[{i}] amount"
            assert actual["type"] == exp["type"], f"tx[{i}] type mismatch"
            assert actual["balance"] == pytest.approx(exp["balance"]), f"tx[{i}] balance"

    def test_total_funds_in_and_out(self, rbc_parse_result: Any, rbc_expected: dict[str, Any]) -> None:
        withdrawals = sum(t["amount"] for t in rbc_parse_result.transactions if t["type"] == "withdrawal")
        deposits = sum(t["amount"] for t in rbc_parse_result.transactions if t["type"] == "deposit")
        assert withdrawals == pytest.approx(rbc_expected["totals"]["funds_out"])
        assert deposits == pytest.approx(rbc_expected["totals"]["funds_in"])

    def test_select_parser_routes_to_rbc(self, rbc_pdf_bytes: bytes) -> None:
        from src.finance.statement_parser import RBCChequingParser

        parser = select_parser(rbc_pdf_bytes)
        assert isinstance(parser, RBCChequingParser)


# ---------------------------------------------------------------------------
# Private fixtures — optional integration tests against real (uncommitted)
# statements. See tests/test_data/_private/README.md.
# ---------------------------------------------------------------------------
PRIVATE_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "test_data" / "_private"
PRIVATE_RBC_PDF = PRIVATE_FIXTURE_DIR / "RBC_Chequing_2026-02-24_to_2026-03-24.pdf"
PRIVATE_SIMPLII_PDF = PRIVATE_FIXTURE_DIR / "Simplii_Chequing_2025-02-27_to_2025-03-30.pdf"


@pytest.mark.private_fixtures
class TestRbcPdfFixturePrivate:
    """Coarse integration test against a real RBC statement."""

    @pytest.fixture(scope="class")
    def real_pdf_bytes(self) -> bytes:
        if not PRIVATE_RBC_PDF.exists():
            pytest.skip(f"Private fixture not present at {PRIVATE_RBC_PDF}")
        return PRIVATE_RBC_PDF.read_bytes()

    def test_parses_without_error(self, real_pdf_bytes: bytes) -> None:
        parser = select_parser(real_pdf_bytes)
        result = parser.parse(real_pdf_bytes)
        assert len(result.transactions) > 0
        assert result.metadata["institution"] == "RBC"
        assert result.metadata["account_type"] == "chequing"

    def test_amounts_sum_to_positive(self, real_pdf_bytes: bytes) -> None:
        parser = select_parser(real_pdf_bytes)
        result = parser.parse(real_pdf_bytes)
        total = sum(t["amount"] for t in result.transactions)
        assert total > 0


@pytest.mark.private_fixtures
class TestSimpliiPdfFixturePrivate:
    """Coarse integration test against a real Simplii statement."""

    @pytest.fixture(scope="class")
    def real_pdf_bytes(self) -> bytes:
        if not PRIVATE_SIMPLII_PDF.exists():
            pytest.skip(f"Private fixture not present at {PRIVATE_SIMPLII_PDF}")
        return PRIVATE_SIMPLII_PDF.read_bytes()

    def test_parses_without_error(self, real_pdf_bytes: bytes) -> None:
        parser = select_parser(real_pdf_bytes)
        result = parser.parse(real_pdf_bytes)
        assert len(result.transactions) > 0
        assert result.metadata["institution"] == "Simplii"
        assert result.metadata["account_type"] == "chequing"

    def test_amounts_sum_to_positive(self, real_pdf_bytes: bytes) -> None:
        parser = select_parser(real_pdf_bytes)
        result = parser.parse(real_pdf_bytes)
        total = sum(t["amount"] for t in result.transactions)
        assert total > 0


# ---------------------------------------------------------------------------
# TestDuplicateHashUniqueness — Verifies the occurrence-based fix
# ---------------------------------------------------------------------------
class TestDuplicateHashUniqueness:
    def test_different_occurrences_produce_different_hashes(self, db: TransactionsDB, base_txn: dict[str, Any]) -> None:
        table = MagicMock(name="dynamodb_table")
        db.dyn_resource.Table.return_value = table
        table.query.return_value = {"Count": 0, "Items": []}

        # occurrence 0 is the first write
        txn0 = {**base_txn, "occurrence": 0}
        result0 = db.add_statement_transaction(txn0)
        item0 = table.put_item.call_args[1]["Item"]
        hash0 = item0["TransactionHash"]

        # occurrence 1 is the second write
        txn1 = {**base_txn, "occurrence": 1}
        result1 = db.add_statement_transaction(txn1)
        item1 = table.put_item.call_args[1]["Item"]
        hash1 = item1["TransactionHash"]

        assert hash0 != hash1
        assert result0 is not None
        assert result1 is not None

    def test_different_occurrences_produce_different_date_file_names(
        self, db: TransactionsDB, base_txn: dict[str, Any]
    ) -> None:
        table = MagicMock()
        db.dyn_resource.Table.return_value = table
        table.query.return_value = {"Count": 0, "Items": []}

        txn0 = {**base_txn, "occurrence": 0}
        dfn0 = db.add_statement_transaction(txn0)

        txn1 = {**base_txn, "occurrence": 1}
        dfn1 = db.add_statement_transaction(txn1)

        assert dfn0 != dfn1
        # Both should be valid DateFileName format
        assert isinstance(dfn0, str)
        assert isinstance(dfn1, str)
        assert dfn0.startswith("2025.03.10_00.00_stmt_Simplii_")
        assert dfn1.startswith("2025.03.10_00.00_stmt_Simplii_")

    def test_occurrence_zero_matches_default(self, db: TransactionsDB, base_txn: dict[str, Any]) -> None:
        """occurrence=0 produces the same hash as omitting the field (backward compat)."""
        table = MagicMock(name="dynamodb_table")
        db.dyn_resource.Table.return_value = table
        table.query.return_value = {"Count": 0, "Items": []}

        # With occurrence=0
        txn_with = {**base_txn, "occurrence": 0}
        db.add_statement_transaction(txn_with)
        hash_with = table.put_item.call_args[1]["Item"]["TransactionHash"]

        # Without occurrence field
        txn_without = {k: v for k, v in base_txn.items() if k != "occurrence"}
        db.add_statement_transaction(txn_without)
        hash_without = table.put_item.call_args[1]["Item"]["TransactionHash"]

        assert hash_with == hash_without

    def test_both_duplicates_written_successfully(self, db: TransactionsDB, base_txn: dict[str, Any]) -> None:
        table = MagicMock(name="dynamodb_table")
        db.dyn_resource.Table.return_value = table
        table.query.return_value = {"Count": 0, "Items": []}

        txn0 = {**base_txn, "occurrence": 0}
        txn1 = {**base_txn, "occurrence": 1}

        r0 = db.add_statement_transaction(txn0)
        r1 = db.add_statement_transaction(txn1)

        assert r0 is not None
        assert r0 is not False
        assert r1 is not None
        assert r1 is not False
        assert table.put_item.call_count == 2


# ---------------------------------------------------------------------------
# TestImportPipelineDedup — Full parse → import pipeline (mocked DynamoDB)
# ---------------------------------------------------------------------------
class TestImportPipelineDedup:
    def test_full_pipeline_both_duplicates_survive(self, pdf_bytes: bytes, db: TransactionsDB) -> None:
        """Parse PDF, compute occurrences as the import endpoint does, verify unique writes."""
        parser = select_parser(pdf_bytes)
        result = parser.parse(pdf_bytes)

        table = MagicMock(name="dynamodb_table")
        db.dyn_resource.Table.return_value = table
        table.query.return_value = {"Count": 0, "Items": []}

        # Replicate the import endpoint's occurrence-counting logic
        import_hash_counter: dict[tuple[Any, ...], int] = {}
        date_file_names = []
        hashes = []

        for txn in result.transactions:
            raw_desc = txn.get("description", "")
            hash_key = (txn["date"], txn["amount"], raw_desc, txn.get("type", "withdrawal"))
            occurrence = import_hash_counter.get(hash_key, 0)
            import_hash_counter[hash_key] = occurrence + 1

            txn_data = {
                "forwarded_to": "test@example.com",
                "date": txn["date"],
                "amount": txn["amount"],
                "company": raw_desc,
                "institution": "Simplii",
                "transaction_type": txn.get("type", "withdrawal"),
                "category": "miscellaneous",
                "statement_source": "Simplii_Chequing_2025-03",
                "raw_description": raw_desc,
                "occurrence": occurrence,
            }
            dfn = db.add_statement_transaction(txn_data)
            assert dfn is not None
            assert dfn is not False

            item = table.put_item.call_args[1]["Item"]
            date_file_names.append(dfn)
            hashes.append(item["TransactionHash"])

        # All 15 transactions should have been written
        assert table.put_item.call_count == 15

        # All DateFileNames and hashes must be unique
        assert len(set(date_file_names)) == 15, f"Duplicate DateFileNames: {date_file_names}"
        assert len(set(hashes)) == 15, f"Duplicate hashes: {hashes}"
