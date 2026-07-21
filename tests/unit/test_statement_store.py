"""Tests for StatementStore SQLite persistence layer."""

import json
from pathlib import Path
from typing import Any

import pytest

from src.finance.statement_store import StatementStore


@pytest.fixture
def store(tmp_path: Path) -> StatementStore:
    """Create a StatementStore backed by a temp directory."""
    db_path = tmp_path / "test.db"
    return StatementStore(db_path=db_path)


def _make_statement(sid: str = "abc123", filename: str = "stmt.pdf") -> dict[str, Any]:
    return {
        "id": sid,
        "filename": filename,
        "institution": "RBC",
        "account_type": "Chequing",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "pdf_path": "/data/raw/statements/RBC/stmt.pdf",
        "total_parsed": 10,
        "matched_count": 5,
        "ambiguous_count": 2,
        "new_count": 2,
        "previously_imported_count": 1,
    }


def _make_tx_rows(count: int = 3, tiers: list[str] | None = None) -> list[dict[str, Any]]:
    """Generate transaction rows for different tiers."""
    if tiers is None:
        tiers = ["new", "matched", "previously_imported"]
    rows = []
    for i in range(count):
        tier = tiers[i % len(tiers)]
        row = {
            "tx_index": i,
            "reconcile_tier": tier,
            "date": "2026-01-15",
            "raw_description": f"Test Transaction {i}",
            "cleaned_description": f"Test Transaction {i}",
            "amount": 10.0 + i,
            "type": "withdrawal",
        }
        if tier in ("matched", "previously_imported"):
            row["db_forwarded_to"] = "test@example.com"
            row["db_date_file_name"] = f"2026.01.15_10.00_test_{i}.eml"
            row["db_company"] = f"DB Company {i}"
            row["db_amount"] = 10.0 + i
            row["db_category"] = "groceries"
        if tier == "matched":
            row["company_differs"] = True
        if tier == "ambiguous":
            row["enrichable"] = True
            row["reason"] = "date off by 1 day(s)"
            row["candidates_json"] = json.dumps([{"forwarded_to": "t@e.com", "company": "A"}])
        rows.append(row)
    return rows


class TestSchemaCreation:
    def test_creates_database(self, store: StatementStore) -> None:
        conn = store._connect()
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        table_names = [t["name"] for t in tables]
        assert "statements" in table_names
        assert "statement_transactions" in table_names
        assert "schema_version" in table_names
        conn.close()

    def test_wal_mode(self, store: StatementStore) -> None:
        conn = store._connect()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
        conn.close()

    def test_busy_timeout_set(self, store: StatementStore) -> None:
        conn = store._connect()
        try:
            row = conn.execute("PRAGMA busy_timeout").fetchone()
            assert row[0] == 5000
        finally:
            conn.close()

    def test_schema_version_set(self, store: StatementStore) -> None:
        conn = store._connect()
        row = conn.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
        assert row["version"] == 1
        conn.close()


class TestGenerateStatementId:
    def test_deterministic(self) -> None:
        id1 = StatementStore.generate_statement_id("RBC", "Chequing", "2026-01", "2026-02", "stmt.pdf")
        id2 = StatementStore.generate_statement_id("RBC", "Chequing", "2026-01", "2026-02", "stmt.pdf")
        assert id1 == id2

    def test_different_inputs_different_ids(self) -> None:
        id1 = StatementStore.generate_statement_id("RBC", "Chequing", "2026-01", "2026-02", "stmt.pdf")
        id2 = StatementStore.generate_statement_id("CIBC", "Chequing", "2026-01", "2026-02", "stmt.pdf")
        assert id1 != id2

    def test_length_16(self) -> None:
        sid = StatementStore.generate_statement_id("RBC", "Chequing", "2026-01", "2026-02", "stmt.pdf")
        assert len(sid) == 16

    def test_none_period_handled(self) -> None:
        sid = StatementStore.generate_statement_id("RBC", "Chequing", None, None, "stmt.pdf")
        assert len(sid) == 16


class TestSaveAndGet:
    def test_save_and_get_statement(self, store: StatementStore) -> None:
        stmt = _make_statement()
        rows = _make_tx_rows()
        store.save_statement(stmt, rows)

        result = store.get_statement("abc123")
        assert result is not None
        assert result["filename"] == "stmt.pdf"
        assert result["institution"] == "RBC"
        assert result["total_parsed"] == 10
        assert result["status"] == "pending_review"
        assert result["uploaded_at"] is not None

    def test_get_nonexistent_returns_none(self, store: StatementStore) -> None:
        assert store.get_statement("missing") is None

    def test_save_and_get_transactions(self, store: StatementStore) -> None:
        stmt = _make_statement()
        rows = _make_tx_rows()
        store.save_statement(stmt, rows)

        txns = store.get_transactions("abc123")
        assert len(txns) == 3
        assert txns[0]["tx_index"] == 0
        assert txns[1]["tx_index"] == 1
        assert txns[2]["tx_index"] == 2

    def test_idempotent_re_upload(self, store: StatementStore) -> None:
        stmt = _make_statement()
        rows = _make_tx_rows(2, ["new", "matched"])
        store.save_statement(stmt, rows)

        # Re-upload with different rows
        new_rows = _make_tx_rows(1, ["new"])
        store.save_statement(stmt, new_rows)

        txns = store.get_transactions("abc123")
        assert len(txns) == 1  # Old rows replaced

    def test_uploaded_at_preserved_on_reupload(self, store: StatementStore) -> None:
        stmt = _make_statement()
        store.save_statement(stmt, _make_tx_rows(1, ["new"]))
        first = store.get_statement("abc123")
        assert first is not None
        original_uploaded = first["uploaded_at"]

        # Re-upload
        store.save_statement(stmt, _make_tx_rows(1, ["new"]))
        second = store.get_statement("abc123")
        assert second is not None
        assert second["uploaded_at"] == original_uploaded


class TestAllTiers:
    def test_all_four_tiers(self, store: StatementStore) -> None:
        stmt = _make_statement()
        rows = _make_tx_rows(4, ["new", "matched", "ambiguous", "previously_imported"])
        store.save_statement(stmt, rows)

        txns = store.get_transactions("abc123")
        tiers = [t["reconcile_tier"] for t in txns]
        assert "new" in tiers
        assert "matched" in tiers
        assert "ambiguous" in tiers
        assert "previously_imported" in tiers

    def test_candidates_json_stored(self, store: StatementStore) -> None:
        stmt = _make_statement()
        rows = _make_tx_rows(4, ["new", "matched", "ambiguous", "previously_imported"])
        store.save_statement(stmt, rows)

        txns = store.get_transactions("abc123")
        ambiguous = next(t for t in txns if t["reconcile_tier"] == "ambiguous")
        candidates = json.loads(ambiguous["candidates_json"])
        assert len(candidates) == 1
        assert candidates[0]["company"] == "A"


class TestDefaultActions:
    def test_new_defaults_to_import(self, store: StatementStore) -> None:
        stmt = _make_statement()
        rows = _make_tx_rows(1, ["new"])
        store.save_statement(stmt, rows)
        txns = store.get_transactions("abc123")
        assert txns[0]["action"] == "import"

    def test_matched_company_differs_defaults_to_enrich(self, store: StatementStore) -> None:
        stmt = _make_statement()
        rows = [
            {"tx_index": 0, "reconcile_tier": "matched", "date": "2026-01-15", "amount": 10.0, "company_differs": True}
        ]
        store.save_statement(stmt, rows)
        txns = store.get_transactions("abc123")
        assert txns[0]["action"] == "enrich"

    def test_matched_no_company_diff_defaults_to_skip(self, store: StatementStore) -> None:
        stmt = _make_statement()
        rows = [
            {"tx_index": 0, "reconcile_tier": "matched", "date": "2026-01-15", "amount": 10.0, "company_differs": False}
        ]
        store.save_statement(stmt, rows)
        txns = store.get_transactions("abc123")
        assert txns[0]["action"] == "skip"

    def test_ambiguous_enrichable_defaults_to_enrich(self, store: StatementStore) -> None:
        stmt = _make_statement()
        rows = [
            {"tx_index": 0, "reconcile_tier": "ambiguous", "date": "2026-01-15", "amount": 10.0, "enrichable": True}
        ]
        store.save_statement(stmt, rows)
        txns = store.get_transactions("abc123")
        assert txns[0]["action"] == "enrich"

    def test_ambiguous_not_enrichable_defaults_to_skip(self, store: StatementStore) -> None:
        stmt = _make_statement()
        rows = [
            {"tx_index": 0, "reconcile_tier": "ambiguous", "date": "2026-01-15", "amount": 10.0, "enrichable": False}
        ]
        store.save_statement(stmt, rows)
        txns = store.get_transactions("abc123")
        assert txns[0]["action"] == "skip"

    def test_previously_imported_defaults_to_skip(self, store: StatementStore) -> None:
        stmt = _make_statement()
        rows = [{"tx_index": 0, "reconcile_tier": "previously_imported", "date": "2026-01-15", "amount": 10.0}]
        store.save_statement(stmt, rows)
        txns = store.get_transactions("abc123")
        assert txns[0]["action"] == "skip"


def _cap_row(tx_index: int, tier: str, tx_type: str = "withdrawal") -> dict[str, Any]:
    return {
        "tx_index": tx_index,
        "reconcile_tier": tier,
        "date": "2026-01-15",
        "amount": 10.0 + tx_index,
        "type": tx_type,
    }


class TestCaptureSummary:
    def test_empty_returns_none(self, store: StatementStore) -> None:
        assert store.capture_summary() is None

    def test_only_excluded_tiers_returns_none(self, store: StatementStore) -> None:
        # ambiguous + suspected_duplicate are excluded from both sides, so a
        # statement made only of them has zero counted rows → None.
        rows = [_cap_row(0, "ambiguous"), _cap_row(1, "suspected_duplicate")]
        store.save_statement(_make_statement(), rows)
        assert store.capture_summary() is None

    def test_tier_arithmetic_and_exclusions(self, store: StatementStore) -> None:
        # caught = matched (2); missed = new (1) + previously_imported (1) = 2;
        # ambiguous + suspected_duplicate excluded entirely. total = 4.
        rows = [
            _cap_row(0, "matched"),
            _cap_row(1, "matched"),
            _cap_row(2, "new"),
            _cap_row(3, "previously_imported"),
            _cap_row(4, "ambiguous"),
            _cap_row(5, "suspected_duplicate"),
        ]
        store.save_statement(_make_statement(), rows)
        summary = store.capture_summary()
        assert summary is not None
        assert summary["overall"] == {"caught": 2, "total": 4, "rate": 0.5}

    def test_by_type_grouping_and_sorting(self, store: StatementStore) -> None:
        rows = [
            _cap_row(0, "matched", "deposit"),
            _cap_row(1, "new", "deposit"),
            _cap_row(2, "matched", "withdrawal"),
            _cap_row(3, "matched", "withdrawal"),
        ]
        store.save_statement(_make_statement(), rows)
        summary = store.capture_summary()
        assert summary is not None
        # Sorted alphabetically: deposit before withdrawal.
        assert summary["by_type"] == [
            {"type": "deposit", "caught": 1, "total": 2, "rate": 0.5},
            {"type": "withdrawal", "caught": 2, "total": 2, "rate": 1.0},
        ]

    def test_by_institution_grouping_and_sorting_multi_statement(self, store: StatementStore) -> None:
        # CIBC statement: 1 matched, 1 new.
        store.save_statement(
            _make_statement("cibc1", "cibc.pdf") | {"institution": "CIBC"},
            [_cap_row(0, "matched"), _cap_row(1, "new")],
        )
        # RBC statement: 3 matched, 1 new.
        store.save_statement(
            _make_statement("rbc1", "rbc.pdf") | {"institution": "RBC"},
            [_cap_row(0, "matched"), _cap_row(1, "matched"), _cap_row(2, "matched"), _cap_row(3, "new")],
        )
        summary = store.capture_summary()
        assert summary is not None
        # Overall aggregates across both statements: caught 4 of 6.
        assert summary["overall"] == {"caught": 4, "total": 6, "rate": 4 / 6}
        # Alphabetical: CIBC before RBC.
        assert summary["by_institution"] == [
            {"institution": "CIBC", "caught": 1, "total": 2, "rate": 0.5},
            {"institution": "RBC", "caught": 3, "total": 4, "rate": 0.75},
        ]


class TestListStatements:
    def test_list_empty(self, store: StatementStore) -> None:
        assert store.list_statements() == []

    def test_list_ordered_by_uploaded_at_desc(self, store: StatementStore) -> None:
        store.save_statement(_make_statement("s1", "first.pdf"), [])
        store.save_statement(_make_statement("s2", "second.pdf"), [])

        stmts = store.list_statements()
        assert len(stmts) == 2
        # Most recent first
        assert stmts[0]["id"] == "s2"
        assert stmts[1]["id"] == "s1"


class TestDeleteStatement:
    def test_delete_existing(self, store: StatementStore) -> None:
        store.save_statement(_make_statement(), _make_tx_rows(2, ["new", "matched"]))
        assert store.delete_statement("abc123") is True
        assert store.get_statement("abc123") is None

    def test_delete_nonexistent(self, store: StatementStore) -> None:
        assert store.delete_statement("missing") is False

    def test_cascading_delete(self, store: StatementStore) -> None:
        store.save_statement(_make_statement(), _make_tx_rows(3))
        store.delete_statement("abc123")
        assert store.get_transactions("abc123") == []


class TestUpdateTransactionAction:
    def test_update_action(self, store: StatementStore) -> None:
        store.save_statement(_make_statement(), _make_tx_rows(1, ["new"]))
        result = store.update_transaction_action("abc123", 0, "skip")
        assert result is True
        txns = store.get_transactions("abc123")
        assert txns[0]["action"] == "skip"

    def test_update_with_company_and_category(self, store: StatementStore) -> None:
        store.save_statement(_make_statement(), _make_tx_rows(1, ["new"]))
        store.update_transaction_action("abc123", 0, "import", company="Walmart", category="groceries")
        txns = store.get_transactions("abc123")
        assert txns[0]["edited_company"] == "Walmart"
        assert txns[0]["edited_category"] == "groceries"

    def test_update_nonexistent_returns_false(self, store: StatementStore) -> None:
        store.save_statement(_make_statement(), [])
        result = store.update_transaction_action("abc123", 99, "skip")
        assert result is False


class TestBulkUpdate:
    def test_bulk_update(self, store: StatementStore) -> None:
        store.save_statement(_make_statement(), _make_tx_rows(3))
        count = store.bulk_update_actions(
            "abc123",
            [
                {"tx_index": 0, "action": "skip"},
                {"tx_index": 1, "action": "import", "company": "Costco"},
            ],
        )
        assert count == 2
        txns = store.get_transactions("abc123")
        assert txns[0]["action"] == "skip"
        assert txns[1]["action"] == "import"
        assert txns[1]["edited_company"] == "Costco"


class TestRecordImportResults:
    def test_record_results(self, store: StatementStore) -> None:
        store.save_statement(_make_statement(), _make_tx_rows(2, ["new", "new"]))
        store.record_import_results(
            "abc123",
            [
                {"tx_index": 0, "action_result": "imported"},
                {"tx_index": 1, "action_result": "duplicate"},
            ],
        )
        txns = store.get_transactions("abc123")
        assert txns[0]["action_result"] == "imported"
        assert txns[0]["acted_at"] is not None
        assert txns[1]["action_result"] == "duplicate"

    def test_status_transitions_to_complete(self, store: StatementStore) -> None:
        """All actions resolved → status becomes complete."""
        rows = [
            {"tx_index": 0, "reconcile_tier": "new", "date": "2026-01-15", "amount": 10.0},
            {
                "tx_index": 1,
                "reconcile_tier": "matched",
                "date": "2026-01-15",
                "amount": 20.0,
                "company_differs": False,
            },
        ]
        store.save_statement(_make_statement(), rows)

        # tx_index 1 is "skip" by default (matched, no company_differs)
        # tx_index 0 is "import" by default
        store.record_import_results(
            "abc123",
            [
                {"tx_index": 0, "action_result": "imported"},
            ],
        )
        stmt = store.get_statement("abc123")
        assert stmt is not None
        assert stmt["status"] == "complete"
        assert stmt["completed_at"] is not None

    def test_status_in_progress(self, store: StatementStore) -> None:
        """Some actions resolved, some pending → in_progress."""
        rows = [
            {"tx_index": 0, "reconcile_tier": "new", "date": "2026-01-15", "amount": 10.0},
            {"tx_index": 1, "reconcile_tier": "new", "date": "2026-01-16", "amount": 20.0},
        ]
        store.save_statement(_make_statement(), rows)
        store.record_import_results(
            "abc123",
            [
                {"tx_index": 0, "action_result": "imported"},
            ],
        )
        stmt = store.get_statement("abc123")
        assert stmt is not None
        assert stmt["status"] == "in_progress"

    def test_status_pending_review_initially(self, store: StatementStore) -> None:
        store.save_statement(_make_statement(), _make_tx_rows(2, ["new", "new"]))
        stmt = store.get_statement("abc123")
        assert stmt is not None
        assert stmt["status"] == "pending_review"
