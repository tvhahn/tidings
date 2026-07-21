"""Stability + contract tests for the row_id-keyed statements PATCH.

Spec: docs/specs/01_backend-as-platform/2026-04-30-statements-stable-row-ids/.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from src.finance.statement_store import StatementStore, _assign_row_ids, row_id_for

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def store(tmp_path: Path) -> StatementStore:
    return StatementStore(db_path=tmp_path / "statements.db")


def _row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "tx_index": 0,
        "reconcile_tier": "new",
        "date": "2026-04-15",
        "raw_description": "STARBUCKS COFFEE",
        "cleaned_description": "Starbucks Coffee",
        "amount": 4.85,
        "type": "withdrawal",
        "balance": None,
        "company_differs": False,
        "enrichable": False,
        "candidates_json": None,
    }
    base.update(overrides)
    return base


def _stmt(sid: str = "stmt1") -> dict[str, object]:
    return {
        "id": sid,
        "filename": "rbc.pdf",
        "institution": "RBC",
        "account_type": "checking",
        "period_start": "2026-04-01",
        "period_end": "2026-04-30",
        "pdf_path": "data/statements/rbc.pdf",
        "total_parsed": 0,
        "matched_count": 0,
        "ambiguous_count": 0,
        "new_count": 0,
        "previously_imported_count": 0,
    }


class TestRowIdHelper:
    def test_format_is_r_plus_16_hex(self) -> None:
        rid = row_id_for("2026-04-15", 4.85, "STARBUCKS")
        assert rid.startswith("r")
        assert len(rid) == 17  # "r" + 16 hex
        assert all(c in "0123456789abcdef" for c in rid[1:])
        assert not rid.isdigit()  # leading "r" guarantees this

    def test_deterministic(self) -> None:
        a = row_id_for("2026-04-15", 4.85, "STARBUCKS")
        b = row_id_for("2026-04-15", 4.85, "STARBUCKS")
        assert a == b

    def test_dup_counter_disambiguates(self) -> None:
        a = row_id_for("2026-04-15", 4.85, "STARBUCKS", dup_counter=0)
        b = row_id_for("2026-04-15", 4.85, "STARBUCKS", dup_counter=1)
        assert a != b

    def test_assign_row_ids_handles_duplicates(self) -> None:
        rows = [
            _row(tx_index=0, raw_description="STARBUCKS", amount=4.85),
            _row(tx_index=1, raw_description="STARBUCKS", amount=4.85),  # exact dup
            _row(tx_index=2, raw_description="TIM HORTONS", amount=2.50),
        ]
        _assign_row_ids(rows)
        ids = [r["row_id"] for r in rows]
        assert len(set(ids)) == 3  # all unique even with the dup pair


class TestStability:
    def test_row_id_stable_across_reparse(self, store: StatementStore) -> None:
        rows = [
            _row(tx_index=0, raw_description="STARBUCKS"),
            _row(tx_index=1, raw_description="TIM HORTONS", amount=2.50),
        ]
        store.save_statement(_stmt(), [dict(r) for r in rows])
        first = {r["tx_index"]: r["row_id"] for r in store.get_transactions("stmt1")}

        # Re-parse: same input rows, fresh save call
        store.save_statement(_stmt(), [dict(r) for r in rows])
        second = {r["tx_index"]: r["row_id"] for r in store.get_transactions("stmt1")}

        assert first == second

    def test_row_id_unchanged_after_middle_row_action_update(self, store: StatementStore) -> None:
        """The fragile-index bug: editing row 0 must not shift the id for row 1."""
        rows = [
            _row(tx_index=0, raw_description="STARBUCKS"),
            _row(tx_index=1, raw_description="TIM HORTONS", amount=2.50),
            _row(tx_index=2, raw_description="WHOLE FOODS", amount=43.21),
        ]
        store.save_statement(_stmt(), [dict(r) for r in rows])

        before = store.get_transactions("stmt1")
        target_row_id = before[1]["row_id"]

        # Update the middle row by row_id; the others' row_ids must not shift.
        store.update_transaction_action_by_row_id("stmt1", target_row_id, action="skip")

        after = store.get_transactions("stmt1")
        assert [r["row_id"] for r in after] == [r["row_id"] for r in before]


class TestUpdateByRowId:
    def test_update_hits_target_row(self, store: StatementStore) -> None:
        rows = [
            _row(tx_index=0, raw_description="A"),
            _row(tx_index=1, raw_description="B"),
        ]
        store.save_statement(_stmt(), [dict(r) for r in rows])
        target = store.get_transactions("stmt1")[1]["row_id"]

        result = store.update_transaction_action_by_row_id("stmt1", target, action="import", company="B Co")
        assert result is not None
        assert result["row_id"] == target
        assert result["tx_index"] == 1

        refreshed = store.get_transactions("stmt1")
        # Only row 1 carries the edited_company we just set.
        assert refreshed[0].get("edited_company") is None
        assert refreshed[1]["edited_company"] == "B Co"
        assert refreshed[1]["action"] == "import"

    def test_unknown_row_id_returns_none(self, store: StatementStore) -> None:
        store.save_statement(_stmt(), [dict(_row(tx_index=0))])
        result = store.update_transaction_action_by_row_id("stmt1", "rdoesnotexist000", action="skip")
        assert result is None


class TestLazyBackfill:
    def test_get_transactions_backfills_null_row_ids(self, store: StatementStore) -> None:
        """Pre-migration rows have row_id=NULL; first read computes + persists."""
        rows = [_row(tx_index=0, raw_description="OLD"), _row(tx_index=1, raw_description="NEW")]
        store.save_statement(_stmt(), [dict(r) for r in rows])

        # Simulate pre-migration state by NULLing the row_ids.
        conn = store._connect()
        try:
            conn.execute("UPDATE statement_transactions SET row_id = NULL WHERE statement_id = ?", ("stmt1",))
            conn.commit()
        finally:
            conn.close()

        first_read = store.get_transactions("stmt1")
        assert all(r["row_id"] for r in first_read)

        # Confirm the backfill persisted.
        conn = store._connect()
        try:
            row = conn.execute(
                "SELECT row_id FROM statement_transactions WHERE statement_id = ? AND tx_index = 0",
                ("stmt1",),
            ).fetchone()
        finally:
            conn.close()
        assert row["row_id"] is not None
