"""Tests for journal API endpoint — day-grouped transaction timeline."""

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from tests.asserts import assert_ok, assert_problem
from tests.factories import make_budget_targets_item, make_transaction_item


def _item(
    day: str, hour: str = "10.30", amount: str = "42.50", txn_type: str = "purchase", **kw: Any
) -> dict[str, Any]:
    """Build a DynamoDB item for a specific day."""
    return make_transaction_item(
        DateFileName=f"2026.04.{day}_{hour}_test.eml",
        Date=f"04/{day}/2026 {hour.replace('.', ':')} PST",
        Amount=Decimal(amount),
        TransactionType=txn_type,
        **kw,
    )


class TestGetJournal:
    @pytest.mark.parametrize("mock_run_sync", ["journal"], indirect=True)
    def test_groups_by_day(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        items = [_item("14"), _item("14", hour="11.00"), _item("15")]
        mock_run_sync.side_effect = [items, None]

        resp = api_client.get("/api/v1/journal?month=2026-04")
        assert_ok(resp)

        data = resp.json()
        assert len(data["days"]) == 2
        # Most recent day first
        assert data["days"][0]["date"] == "2026-04-15"
        assert data["days"][0]["count"] == 1
        assert data["days"][1]["date"] == "2026-04-14"
        assert data["days"][1]["count"] == 2

    @pytest.mark.parametrize("mock_run_sync", ["journal"], indirect=True)
    def test_filters_deleted(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        items = [_item("14"), _item("14", hour="11.00", DeletedAt="2026-04-14T12:00:00")]
        mock_run_sync.side_effect = [items, None]

        resp = api_client.get("/api/v1/journal?month=2026-04")
        data = resp.json()

        assert data["transaction_count"] == 1
        assert data["days"][0]["count"] == 1

    @pytest.mark.parametrize("mock_run_sync", ["journal"], indirect=True)
    def test_filters_ignored(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        items = [_item("14"), _item("14", hour="11.00", Ignored=True)]
        mock_run_sync.side_effect = [items, None]

        resp = api_client.get("/api/v1/journal?month=2026-04")
        data = resp.json()

        assert data["transaction_count"] == 1

    @pytest.mark.parametrize("mock_run_sync", ["journal"], indirect=True)
    def test_days_sorted_descending(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        items = [_item("10"), _item("14"), _item("12")]
        mock_run_sync.side_effect = [items, None]

        resp = api_client.get("/api/v1/journal?month=2026-04")
        dates = [d["date"] for d in resp.json()["days"]]

        assert dates == ["2026-04-14", "2026-04-12", "2026-04-10"]

    @pytest.mark.parametrize("mock_run_sync", ["journal"], indirect=True)
    def test_transactions_within_day_sorted_descending(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        items = [_item("14", hour="08.00"), _item("14", hour="15.00"), _item("14", hour="12.00")]
        mock_run_sync.side_effect = [items, None]

        resp = api_client.get("/api/v1/journal?month=2026-04")
        txns = resp.json()["days"][0]["transactions"]
        dfns = [t["date_file_name"] for t in txns]

        # 15:00 > 12:00 > 08:00
        assert dfns[0] > dfns[1] > dfns[2]

    def test_out_of_range_month_returns_422(self, api_client: TestClient) -> None:
        # MONTH_PATTERN is calendar-valid: 13 is not a real month.
        resp = api_client.get("/api/v1/journal?month=2026-13")
        assert_problem(resp, 422)

    @pytest.mark.parametrize("mock_run_sync", ["journal"], indirect=True)
    def test_non_spending_types_excluded(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        items = [
            _item("14", amount="50.00", txn_type="purchase"),
            _item("14", hour="11.00", amount="30.00", txn_type="deposit"),
        ]
        mock_run_sync.side_effect = [items, None]

        resp = api_client.get("/api/v1/journal?month=2026-04")
        day = resp.json()["days"][0]

        assert day["day_total"] == 50.0
        assert day["count"] == 1
        assert resp.json()["transaction_count"] == 1

    @pytest.mark.parametrize("mock_run_sync", ["journal"], indirect=True)
    def test_zero_amount_rows_excluded(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        items = [
            _item("14", amount="50.00"),
            _item("14", hour="11.00", amount="0.00"),
        ]
        mock_run_sync.side_effect = [items, None]

        resp = api_client.get("/api/v1/journal?month=2026-04")
        day = resp.json()["days"][0]

        assert day["count"] == 1
        assert resp.json()["transaction_count"] == 1

    @pytest.mark.parametrize("mock_run_sync", ["journal"], indirect=True)
    def test_mtd_accumulates_correctly(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        items = [
            _item("10", amount="100.00"),
            _item("12", amount="200.00"),
            _item("14", amount="50.00"),
        ]
        mock_run_sync.side_effect = [items, None]

        resp = api_client.get("/api/v1/journal?month=2026-04")
        days = resp.json()["days"]

        # days[0] is Apr 14 (most recent), days[2] is Apr 10 (oldest)
        assert days[2]["mtd_total"] == 100.0  # Apr 10: just 100
        assert days[1]["mtd_total"] == 300.0  # Apr 12: 100 + 200
        assert days[0]["mtd_total"] == 350.0  # Apr 14: 100 + 200 + 50

    @pytest.mark.parametrize("mock_run_sync", ["journal"], indirect=True)
    def test_budget_ceiling_returned(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        targets = make_budget_targets_item(year=2026)  # spending_ceiling=5000 (annual)
        mock_run_sync.side_effect = [[_item("14")], targets]

        resp = api_client.get("/api/v1/journal?month=2026-04")

        # Annual ceiling / 12 = monthly ceiling
        assert resp.json()["budget_ceiling"] == round(5000.0 / 12, 2)

    @pytest.mark.parametrize("mock_run_sync", ["journal"], indirect=True)
    def test_budget_ceiling_null_when_no_budget(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        mock_run_sync.side_effect = [[_item("14")], None]

        resp = api_client.get("/api/v1/journal?month=2026-04")

        assert resp.json()["budget_ceiling"] is None

    @pytest.mark.parametrize("mock_run_sync", ["journal"], indirect=True)
    def test_context_carried_through(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        items = [
            _item(
                "14",
                TransactionContext={
                    "category_month_total": Decimal("350.00"),
                    "merchant_month_count": 3,
                    "category_budget_target": Decimal("500.00"),
                    "category_budget_pct": Decimal("70.0"),
                },
            )
        ]
        mock_run_sync.side_effect = [items, None]

        resp = api_client.get("/api/v1/journal?month=2026-04")
        ctx = resp.json()["days"][0]["transactions"][0]["context"]

        assert ctx is not None
        assert ctx["category_month_total"] == 350.0
        assert ctx["merchant_month_count"] == 3
        assert ctx["category_budget_pct"] == 70.0

    @pytest.mark.parametrize("mock_run_sync", ["journal"], indirect=True)
    def test_empty_month_returns_empty_days(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        mock_run_sync.side_effect = [[], None]

        resp = api_client.get("/api/v1/journal?month=2026-04")
        data = resp.json()

        assert data["days"] == []
        assert data["month_total"] == 0.0
        assert data["transaction_count"] == 0

    def test_missing_month_returns_422(self, api_client: TestClient) -> None:
        resp = api_client.get("/api/v1/journal")
        assert_problem(resp, 422)

    def test_invalid_month_format_returns_422(self, api_client: TestClient) -> None:
        resp = api_client.get("/api/v1/journal?month=April-2026")
        assert_problem(resp, 422)
