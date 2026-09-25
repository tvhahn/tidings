"""Router↔service↔storage integration tests — no mocked ``run_sync``.

Every ``test_api_*.py`` module patches ``run_sync`` and feeds the router
hand-crafted DynamoDB items from ``tests/factories.py``. That proves the
router's response *shape*, but never that those factory items match what the
service actually persists — the coupling is maintained only by the factory
docstrings ("Matches the shape written by BudgetService.put_targets()"). If a
service's write shape drifted, the mocked tests would stay green while
production 500s on the read.

These tests close that seam. They override the FastAPI service dependency with
a *real* service — DynamoDB-side against a ``moto`` fake, SQLite-side against a
tmp DB — and drive a write→read round-trip through the HTTP layer. Nothing is
hand-crafted: the bytes the service writes are the bytes the router reads back,
across the same ``run_sync`` executor hop production uses. Parametrized over
both backends so the two implementations stay in lockstep at the API boundary
(complements ``test_dual_backend_contract.py``, which exercises the
service↔storage seam directly, one layer below the router).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from src.api.dependencies import (
    get_budget_service,
    get_override_service,
    get_spending_summary,
    get_transactions_db,
)
from src.api.main import app
from src.finance.user_mapping import get_forwarded_to_addresses
from tests.asserts import assert_ok, assert_problem

if TYPE_CHECKING:
    from pathlib import Path


def _override_service(backend: str, dyn_resource: Any, tmp_path: Path) -> Any:
    if backend == "dynamodb":
        from src.finance.override_service import OverrideService

        return OverrideService(dyn_resource=dyn_resource)
    from src.finance.override_service_local import OverrideServiceLocal

    return OverrideServiceLocal(db_path=tmp_path / "overrides.db")


def _budget_service(backend: str, dyn_resource: Any, tmp_path: Path) -> Any:
    if backend == "dynamodb":
        from src.finance.budget_service import BudgetService

        return BudgetService(dyn_resource=dyn_resource)
    from src.finance.budget_service_local import BudgetServiceLocal

    return BudgetServiceLocal(db_path=tmp_path / "budget.db")


@pytest.fixture(params=["dynamodb", "sqlite"])
def override_client(request: pytest.FixtureRequest, api_client: Any, dyn_resource: Any, tmp_path: Path) -> Any:
    """``api_client`` with ``get_override_service`` wired to a real backend.

    ``api_client`` (root conftest) clears ``dependency_overrides`` on teardown.
    """
    svc = _override_service(request.param, dyn_resource, tmp_path)
    app.dependency_overrides[get_override_service] = lambda: svc
    return api_client


@pytest.fixture(params=["dynamodb", "sqlite"])
def budget_client(request: pytest.FixtureRequest, api_client: Any, dyn_resource: Any, tmp_path: Path) -> Any:
    """``api_client`` with ``get_budget_service`` wired to a real backend."""
    svc = _budget_service(request.param, dyn_resource, tmp_path)
    app.dependency_overrides[get_budget_service] = lambda: svc
    return api_client


class TestOverrideRoundTrip:
    """PUT → GET through the real OverrideService (shared config-service base)."""

    def test_put_then_independent_get_returns_written_value(self, override_client: Any) -> None:
        put = assert_ok(override_client.put("/api/v1/overrides/STARBUCKS", json={"category": "coffee"}))
        assert any(o["company"] == "STARBUCKS" and o["category"] == "coffee" for o in put["overrides"])

        # A fresh GET reads the persisted row back — not the PUT's echo.
        listing = assert_ok(override_client.get("/api/v1/overrides"))
        assert listing["count"] == 1
        assert listing["overrides"] == [{"company": "STARBUCKS", "category": "coffee"}]

    def test_version_increments_across_writes(self, override_client: Any) -> None:
        v1 = assert_ok(override_client.put("/api/v1/overrides/STARBUCKS", json={"category": "coffee"}))["version"]
        v2 = assert_ok(override_client.put("/api/v1/overrides/TIMHORTONS", json={"category": "coffee"}))["version"]
        assert v2 > v1

    def test_overwrite_same_company_updates_category(self, override_client: Any) -> None:
        assert_ok(override_client.put("/api/v1/overrides/STARBUCKS", json={"category": "coffee"}))
        assert_ok(override_client.put("/api/v1/overrides/STARBUCKS", json={"category": "dining"}))
        listing = assert_ok(override_client.get("/api/v1/overrides"))
        assert listing["count"] == 1
        assert listing["overrides"][0]["category"] == "dining"

    def test_delete_removes_the_row(self, override_client: Any) -> None:
        assert_ok(override_client.put("/api/v1/overrides/STARBUCKS", json={"category": "coffee"}))
        assert_ok(override_client.delete("/api/v1/overrides/STARBUCKS"))
        assert assert_ok(override_client.get("/api/v1/overrides"))["count"] == 0

    def test_delete_missing_is_404(self, override_client: Any) -> None:
        assert_problem(override_client.delete("/api/v1/overrides/NOPE"), 404)


_BUDGET_BODY = {
    "spending_ceiling": 60000,
    "categories": {
        "groceries": {"target": 7200, "input_mode": "monthly", "category_type": "variable"},
        "rent": {"target": 24000, "input_mode": "monthly", "category_type": "fixed"},
    },
    "groups": [{"name": "Essentials", "categories": ["groceries", "rent"]}],
    "targets_version": None,
    "groups_version": None,
}


class TestBudgetConfigRoundTrip:
    """PUT → GET through the real BudgetService (separate impls; targets + groups)."""

    def test_put_then_independent_get_matches(self, budget_client: Any) -> None:
        put = assert_ok(budget_client.put("/api/v1/budget/config?year=2026", json=_BUDGET_BODY))
        get = assert_ok(budget_client.get("/api/v1/budget/config?year=2026"))

        # The read reflects exactly what the service persisted — no factory stand-in.
        assert get["spending_ceiling"] == 60000
        assert set(get["categories"]) == {"groceries", "rent"}
        assert get["categories"]["groceries"]["target"] == 7200
        assert get["categories"]["rent"]["category_type"] == "fixed"
        assert [g["name"] for g in get["groups"]] == ["Essentials"]
        assert get["groups"][0]["categories"] == ["groceries", "rent"]
        # First write establishes version 1 on both rows; GET agrees with PUT.
        assert put["targets_version"] == get["targets_version"] == 1
        assert put["groups_version"] == get["groups_version"] == 1

    def test_second_write_bumps_versions(self, budget_client: Any) -> None:
        assert_ok(budget_client.put("/api/v1/budget/config?year=2026", json=_BUDGET_BODY))
        body_v2 = {**_BUDGET_BODY, "spending_ceiling": 72000, "targets_version": 1, "groups_version": 1}
        put2 = assert_ok(budget_client.put("/api/v1/budget/config?year=2026", json=body_v2))
        assert put2["targets_version"] == 2
        assert assert_ok(budget_client.get("/api/v1/budget/config?year=2026"))["spending_ceiling"] == 72000

    def test_stale_version_conflicts(self, budget_client: Any) -> None:
        assert_ok(budget_client.put("/api/v1/budget/config?year=2026", json=_BUDGET_BODY))  # → version 1
        # Re-submitting with the now-stale None (create) version must 409, not clobber.
        assert_problem(budget_client.put("/api/v1/budget/config?year=2026", json=_BUDGET_BODY), 409)

    def test_get_before_any_write_is_404(self, budget_client: Any) -> None:
        assert_problem(budget_client.get("/api/v1/budget/config?year=2099"), 404)


# ---------------------------------------------------------------------------
# Transactions: statement import, search, PATCH, summary — real storage
# ---------------------------------------------------------------------------


def _transaction_stores(backend: str, dyn_resource: Any, tmp_path: Path) -> tuple[Any, Any]:
    """Return (transactions_db, spending_summary) sharing ONE backing store."""
    if backend == "dynamodb":
        from src.finance.spending_summary import SpendingSummary
        from src.finance.transaction_db import TransactionsDB

        return TransactionsDB(dyn_resource=dyn_resource), SpendingSummary(dyn_resource=dyn_resource)
    from src.finance.spending_summary_local import SpendingSummaryLocal
    from src.finance.transaction_db_local import TransactionsDBLocal

    db_path = tmp_path / "txns.db"
    return TransactionsDBLocal(db_path=db_path), SpendingSummaryLocal(db_path=db_path)


@pytest.fixture(params=["dynamodb", "sqlite"])
def txn_env(
    request: pytest.FixtureRequest,
    api_client: Any,
    dyn_resource: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, Any]:
    """``(api_client, transactions_db)`` with the transaction + summary deps on one real store.

    The statement-import history log is a cwd-relative JSON file, not storage —
    stub it so the test never writes ``data/processed/statements/``.
    """
    db, summary = _transaction_stores(request.param, dyn_resource, tmp_path)
    app.dependency_overrides[get_transactions_db] = lambda: db
    app.dependency_overrides[get_spending_summary] = lambda: summary
    monkeypatch.setattr("src.api.routers.statements._append_import_history", lambda *_a, **_kw: None)
    return api_client, db


def _forwarded_to() -> str:
    # The statement router files rows under the first mapped address; the
    # DynamoDB summary fans out across every mapped address.
    return get_forwarded_to_addresses()[0]


def _email_txn(date: str, amount: float, company: str, **overrides: Any) -> dict[str, Any]:
    """``add_transaction`` input (snake_case) for an email-ingested row."""
    base: dict[str, Any] = {
        "forwarded_to": _forwarded_to(),
        "date": date,
        "amount": amount,
        "company": company,
        "category": "groceries",
        "institution": "RBC",
        "transaction_type": "purchase",
        "name": "Alice",
        "subject": "Receipt",
        "body": f"${amount}",
        "file_name": f"{company.replace(' ', '_').lower()}.eml",
    }
    base.update(overrides)
    return base


def _import_body(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "actions": [{"index": i, "action": "import", "category": "utilities"} for i in range(len(rows))],
        "metadata": {
            "institution": "RBC",
            "account_type": "chequing",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "transaction_count": len(rows),
        },
        "transactions": [{**r, "balance": None, "cleaned_description": r["description"].title()} for r in rows],
        "filename": "statement.pdf",
    }


class TestStatementImportDedup:
    """POST /statements/import twice with the same rows — the store's hash dedup holds."""

    _ROWS = [
        {"date": "2026-01-05", "description": "HYDRO BILL", "amount": 80.0, "type": "withdrawal"},
        {"date": "2026-01-12", "description": "PHONE CO", "amount": 45.5, "type": "withdrawal"},
        # Identical same-day twins: the occurrence counter must keep both rows.
        {"date": "2026-01-20", "description": "PARKING", "amount": 3.0, "type": "withdrawal"},
        {"date": "2026-01-20", "description": "PARKING", "amount": 3.0, "type": "withdrawal"},
    ]

    def test_second_import_reports_duplicates_and_adds_nothing(self, txn_env: tuple[Any, Any]) -> None:
        client, _db = txn_env
        body = _import_body(self._ROWS)

        first = assert_ok(client.post("/api/v1/statements/import", json=body))
        assert (first["imported"], first["duplicates"], first["skipped"]) == (4, 0, 0)
        after_first = assert_ok(client.get("/api/v1/transactions?month=2026-01"))
        assert after_first["count"] == 4

        second = assert_ok(client.post("/api/v1/statements/import", json=body))
        assert (second["imported"], second["duplicates"], second["skipped"]) == (0, 4, 0)
        after_second = assert_ok(client.get("/api/v1/transactions?month=2026-01"))
        assert after_second["count"] == 4
        assert {t["date_file_name"] for t in after_second["transactions"]} == {
            t["date_file_name"] for t in after_first["transactions"]
        }

    def test_import_loads_hash_index_once(self, txn_env: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch) -> None:
        client, db = txn_env
        loads: list[str] = []
        real_index = db.get_hash_index

        def counting_index(forwarded_to: str) -> dict[str, str]:
            loads.append(forwarded_to)
            return real_index(forwarded_to)

        monkeypatch.setattr(db, "get_hash_index", counting_index)
        if hasattr(db, "_transaction_exists"):  # DynamoDB: the per-row partition query

            def no_per_row_query(*_a: Any, **_kw: Any) -> bool:
                raise AssertionError("statement import must not query the partition per row")

            monkeypatch.setattr(db, "_transaction_exists", no_per_row_query)

        body = _import_body(self._ROWS)
        assert assert_ok(client.post("/api/v1/statements/import", json=body))["imported"] == 4
        assert assert_ok(client.post("/api/v1/statements/import", json=body))["duplicates"] == 4
        assert loads == [_forwarded_to(), _forwarded_to()]  # once per request

    def test_import_falls_back_when_hash_index_fails(
        self, txn_env: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, db = txn_env
        body = _import_body(self._ROWS)
        assert assert_ok(client.post("/api/v1/statements/import", json=body))["imported"] == 4

        def broken_index(_forwarded_to: str) -> dict[str, str]:
            raise RuntimeError("index unavailable")

        monkeypatch.setattr(db, "get_hash_index", broken_index)
        # Per-row duplicate checks still catch every row.
        second = assert_ok(client.post("/api/v1/statements/import", json=body))
        assert (second["imported"], second["duplicates"]) == (0, 4)

    def test_imported_rows_carry_statement_fields(self, txn_env: tuple[Any, Any]) -> None:
        client, _db = txn_env
        assert_ok(client.post("/api/v1/statements/import", json=_import_body(self._ROWS[:1])))
        (row,) = assert_ok(client.get("/api/v1/transactions?month=2026-01"))["transactions"]
        assert row["company"] == "Hydro Bill"
        assert row["category"] == "utilities"
        assert row["amount"] == 80.0
        assert row["transaction_type"] == "withdrawal"
        assert row["statement_source"] == "RBC_Chequing_2026-01"
        assert row["date_file_name"].startswith("2026.01.05_00.00_stmt_RBC_")


class TestSearchMonthScoping:
    """GET /transactions/search reads only the requested months from real storage."""

    @pytest.fixture
    def seeded(self, txn_env: tuple[Any, Any]) -> Any:
        client, db = txn_env
        for txn in (
            _email_txn("12/31/2025 23:30 PST", 11.0, "Dec Store"),
            _email_txn("01/01/2026 00:30 PST", 22.0, "Jan Store"),
            _email_txn("01/31/2026 23:30 PST", 33.0, "Jan End Store"),
            _email_txn("02/14/2026 12:00 PST", 44.0, "Feb Store"),
            _email_txn("03/01/2026 00:10 PST", 55.0, "Mar Store"),
        ):
            assert db.add_transaction(txn)
        return client

    def test_two_month_range_excludes_adjacent_months(self, seeded: Any) -> None:
        got = assert_ok(seeded.get("/api/v1/transactions/search?from=2026-01&to=2026-02"))
        # Newest first, by DateFileName; Dec and Mar neighbours never read.
        assert [t["company"] for t in got["transactions"]] == ["Feb Store", "Jan End Store", "Jan Store"]
        assert got["summary"]["months_queried"] == 2
        assert got["summary"]["total_count"] == 3
        assert got["summary"]["total_amount"] == 99.0
        assert got["total_matching"] == 3
        assert got["capped"] is False

    def test_single_month_excludes_neighbours(self, seeded: Any) -> None:
        got = assert_ok(seeded.get("/api/v1/transactions/search?from=2026-02&to=2026-02"))
        assert [t["company"] for t in got["transactions"]] == ["Feb Store"]
        assert got["summary"]["months_queried"] == 1

    def test_filter_applies_within_scoped_months(self, seeded: Any) -> None:
        got = assert_ok(seeded.get("/api/v1/transactions/search?from=2025-12&to=2026-03&company=jan"))
        assert [t["company"] for t in got["transactions"]] == ["Jan End Store", "Jan Store"]
        assert got["summary"]["months_queried"] == 4


class TestPatchThenGet:
    """PATCH /transactions/{tx_id} persists; a fresh GET reads it back."""

    def test_patch_category_and_state_round_trip(self, txn_env: tuple[Any, Any]) -> None:
        client, db = txn_env
        assert db.add_transaction(_email_txn("02/10/2026 09:00 PST", 12.5, "Corner Cafe"))
        (row,) = assert_ok(client.get("/api/v1/transactions?month=2026-02"))["transactions"]
        tx_id = row["tx_id"]
        assert row["category"] == "groceries"
        assert row["ignored"] is False

        patched = assert_ok(
            client.patch(f"/api/v1/transactions/{tx_id}", json={"category": "Coffee", "state": "ignored"})
        )
        assert patched["old_category"] == "groceries"
        assert patched["new_category"] == "coffee"
        assert patched["state"] == "ignored"

        (after,) = assert_ok(client.get("/api/v1/transactions?month=2026-02"))["transactions"]
        assert after["tx_id"] == tx_id
        assert after["category"] == "coffee"
        assert after["ignored"] is True
        assert after["category_audit"]["source"] == "manual"
        assert after["category_audit"]["previous_category"] == "groceries"

    def test_patch_trashed_moves_row_to_trash(self, txn_env: tuple[Any, Any]) -> None:
        client, db = txn_env
        assert db.add_transaction(_email_txn("02/11/2026 09:00 PST", 7.0, "Bakery"))
        (row,) = assert_ok(client.get("/api/v1/transactions?month=2026-02"))["transactions"]

        patched = assert_ok(client.patch(f"/api/v1/transactions/{row['tx_id']}", json={"state": "trashed"}))
        assert patched["state"] == "trashed"
        assert isinstance(patched["deleted_at"], str)

        assert assert_ok(client.get("/api/v1/transactions?month=2026-02"))["count"] == 0
        trash = assert_ok(client.get("/api/v1/transactions/trash?month=2026-02"))
        assert [t["tx_id"] for t in trash["transactions"]] == [row["tx_id"]]
        assert trash["transactions"][0]["deleted_at"] == patched["deleted_at"]


class TestSummaryTotals:
    """GET /summary aggregates exactly the seeded rows of the month and the prior month."""

    def test_totals_match_seeded_rows(self, txn_env: tuple[Any, Any]) -> None:
        client, db = txn_env
        feb = [
            _email_txn("02/01/2026 10:00 PST", 10.25, "Grocer A"),
            _email_txn("02/02/2026 10:00 PST", 20.5, "Grocer B"),
            _email_txn("02/03/2026 10:00 PST", 30.0, "Diner", category="restaurant/dining"),
            _email_txn("02/04/2026 10:00 PST", 1000.0, "Employer", transaction_type="deposit", category="income"),
            # Excluded from totals: ignored and trashed.
            _email_txn("02/05/2026 10:00 PST", 999.0, "Ignored Co", ignored=True),
            _email_txn("02/06/2026 10:00 PST", 888.0, "Trashed Co"),
        ]
        jan = [_email_txn("01/15/2026 10:00 PST", 40.0, "Grocer A", file_name="grocer_a_jan.eml")]
        # An adjacent-month row must not leak into Feb.
        mar = [_email_txn("03/01/2026 00:05 PST", 500.0, "Grocer A", file_name="grocer_a_mar.eml")]
        dfns = {t["company"]: db.add_transaction(t) for t in feb}
        for t in jan + mar:
            assert db.add_transaction(t)
        db.set_deleted(_forwarded_to(), dfns["Trashed Co"], True)

        got = assert_ok(client.get("/api/v1/summary?month=2026-02"))
        cur = got["current"]
        assert cur["year_month"] == "2026-02"
        assert cur["total_spending"] == 60.75
        assert cur["spending_count"] == 3
        assert cur["deposit_total"] == 1000.0
        assert cur["deposit_count"] == 1
        assert cur["by_category"] == {
            "groceries": {"amount": 30.75, "count": 2},
            "restaurant/dining": {"amount": 30.0, "count": 1},
        }
        prev = got["previous"]
        assert prev["year_month"] == "2026-01"
        assert prev["total_spending"] == 40.0
        assert prev["spending_count"] == 1
        assert got["delta_amount"] == 20.75
        assert got["delta_percent"] == pytest.approx(51.875)
