"""Tests for search API endpoints."""

import csv
import io
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from tests.asserts import assert_ok, assert_problem
from tests.factories import make_transaction_item as _make_item

# ---------------------------------------------------------------------------
# GET /api/v1/transactions/search
# ---------------------------------------------------------------------------


class TestSearchEndpoint:
    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_basic_search_returns_results(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [_make_item(), _make_item(DateFileName="2026.02.10_08.00_b.eml")]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/search?from=2026-02&to=2026-02")
        assert_ok(resp)

        data = resp.json()
        assert len(data["transactions"]) == 2
        assert data["summary"]["total_count"] == 2
        assert data["capped"] is False

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_filter_by_category(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(Category="groceries"),
            _make_item(Category="restaurant/dining", DateFileName="2026.02.10_08.00_b.eml"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/search?from=2026-02&to=2026-02&category=groceries")
        assert_ok(resp)

        data = resp.json()
        assert data["summary"]["total_count"] == 1
        assert data["transactions"][0]["category"] == "groceries"

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_filter_by_company_substring(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(Company="Costco Wholesale"),
            _make_item(Company="Safeway", DateFileName="2026.02.10_08.00_b.eml"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/search?from=2026-02&to=2026-02&company=costco")
        data = resp.json()
        assert data["summary"]["total_count"] == 1
        assert "Costco" in data["transactions"][0]["company"]

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_filter_by_institution(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(Institution="RBC"),
            _make_item(Institution="CIBC", DateFileName="2026.02.10_08.00_b.eml"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/search?from=2026-02&to=2026-02&institution=cibc")
        data = resp.json()
        assert data["summary"]["total_count"] == 1

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_filter_by_type(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(TransactionType="purchase"),
            _make_item(TransactionType="e-transfer", DateFileName="2026.02.10_08.00_b.eml"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/search?from=2026-02&to=2026-02&type=e-transfer")
        data = resp.json()
        assert data["summary"]["total_count"] == 1

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_filter_by_amount_range(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(Amount=Decimal("10.00")),
            _make_item(Amount=Decimal("50.00"), DateFileName="2026.02.10_08.00_b.eml"),
            _make_item(Amount=Decimal("100.00"), DateFileName="2026.02.12_08.00_c.eml"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/search?from=2026-02&to=2026-02&min_amount=20&max_amount=80")
        data = resp.json()
        assert data["summary"]["total_count"] == 1
        assert data["transactions"][0]["amount"] == 50.0

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_excludes_deleted_by_default(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(),
            _make_item(DeletedAt="2026-02-20T10:00:00Z", DateFileName="2026.02.10_08.00_b.eml"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/search?from=2026-02&to=2026-02")
        data = resp.json()
        assert data["summary"]["total_count"] == 1

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_includes_deleted_when_requested(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(),
            _make_item(DeletedAt="2026-02-20T10:00:00Z", DateFileName="2026.02.10_08.00_b.eml"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/search?from=2026-02&to=2026-02&include_deleted=true")
        data = resp.json()
        assert data["summary"]["total_count"] == 2

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_excludes_ignored_by_default(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(),
            _make_item(Ignored=True, DateFileName="2026.02.10_08.00_b.eml"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/search?from=2026-02&to=2026-02")
        data = resp.json()
        assert data["summary"]["total_count"] == 1

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_includes_ignored_when_requested(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(),
            _make_item(Ignored=True, DateFileName="2026.02.10_08.00_b.eml"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/search?from=2026-02&to=2026-02&include_ignored=true")
        data = resp.json()
        assert data["summary"]["total_count"] == 2

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_multi_month_queries_all_months(self, mock_run_sync: AsyncMock, api_client) -> None:
        jan_items = [_make_item(DateFileName="2026.01.15_10.30_a.eml")]
        feb_items = [_make_item(DateFileName="2026.02.15_10.30_b.eml")]
        mock_run_sync.side_effect = [jan_items, feb_items]

        resp = api_client.get("/api/v1/transactions/search?from=2026-01&to=2026-02")
        data = resp.json()
        assert data["summary"]["total_count"] == 2
        assert data["summary"]["months_queried"] == 2

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_results_sorted_newest_first(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(DateFileName="2026.02.10_08.00_a.eml"),
            _make_item(DateFileName="2026.02.20_08.00_b.eml"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/search?from=2026-02&to=2026-02")
        data = resp.json()
        dates = [t["date_file_name"] for t in data["transactions"]]
        assert dates == sorted(dates, reverse=True)

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_summary_by_category(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(Amount=Decimal("100.00"), Category="groceries"),
            _make_item(
                Amount=Decimal("50.00"),
                Category="restaurant/dining",
                DateFileName="2026.02.10_08.00_b.eml",
            ),
        ]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/search?from=2026-02&to=2026-02")
        data = resp.json()
        assert data["summary"]["by_category"]["groceries"] == 100.0
        assert data["summary"]["by_category"]["restaurant/dining"] == 50.0
        assert data["summary"]["total_amount"] == 150.0
        assert data["summary"]["avg_amount"] == 75.0

    def test_missing_from_returns_422(self, api_client) -> None:
        resp = api_client.get("/api/v1/transactions/search?to=2026-02")
        assert_problem(resp, 422)

    def test_missing_to_returns_422(self, api_client) -> None:
        resp = api_client.get("/api/v1/transactions/search?from=2026-02")
        assert_problem(resp, 422)

    def test_invalid_from_format_returns_422(self, api_client) -> None:
        resp = api_client.get("/api/v1/transactions/search?from=Feb-2026&to=2026-02")
        assert_problem(resp, 422)

    def test_invalid_to_format_returns_422(self, api_client) -> None:
        resp = api_client.get("/api/v1/transactions/search?from=2026-02&to=Feb-2026")
        assert_problem(resp, 422)

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_to_before_from_returns_422(self, mock_run_sync: AsyncMock, api_client) -> None:
        resp = api_client.get("/api/v1/transactions/search?from=2026-03&to=2026-01")
        assert_problem(resp, 422)

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_exceeds_max_months_returns_422(self, mock_run_sync: AsyncMock, api_client) -> None:
        # 26 months exceeds _MAX_MONTHS=24
        resp = api_client.get("/api/v1/transactions/search?from=2024-01&to=2026-02")
        assert_problem(resp, 422)

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_13_month_range_succeeds(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = []

        resp = api_client.get("/api/v1/transactions/search?from=2025-03&to=2026-03")
        assert_ok(resp)
        assert resp.json()["summary"]["months_queried"] == 13


# ---------------------------------------------------------------------------
# GET /api/v1/transactions/search — free-text `q` (merchant OR note OR category)
# ---------------------------------------------------------------------------


class TestSearchFreeTextQuery:
    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_q_matches_company(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(Company="Costco Wholesale"),
            _make_item(Company="Safeway", DateFileName="2026.02.10_08.00_b.eml"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/search?from=2026-02&to=2026-02&q=costco")
        assert_ok(resp)
        data = resp.json()
        assert data["summary"]["total_count"] == 1
        assert "Costco" in data["transactions"][0]["company"]

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_q_matches_comment(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(Comment="lunch with team"),
            _make_item(Comment="office supplies", DateFileName="2026.02.10_08.00_b.eml"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/search?from=2026-02&to=2026-02&q=lunch")
        assert_ok(resp)
        data = resp.json()
        assert data["summary"]["total_count"] == 1

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_q_matches_category(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(Category="Groceries"),
            _make_item(Category="restaurant/dining", DateFileName="2026.02.10_08.00_b.eml"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/search?from=2026-02&to=2026-02&q=groc")
        assert_ok(resp)
        data = resp.json()
        assert data["summary"]["total_count"] == 1

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_q_or_semantics_category_only(self, mock_run_sync: AsyncMock, api_client) -> None:
        # Needle hits ONLY the category — not company or comment — and still returns.
        items = [
            _make_item(Company="Safeway", Comment="weekly run", Category="Groceries"),
            _make_item(
                Company="Shell",
                Comment="fill up",
                Category="transportation",
                DateFileName="2026.02.10_08.00_b.eml",
            ),
        ]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/search?from=2026-02&to=2026-02&q=groceries")
        assert_ok(resp)
        data = resp.json()
        assert data["summary"]["total_count"] == 1
        assert data["transactions"][0]["category"] == "Groceries"

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_q_no_match_returns_zero(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(Company="Safeway", Comment="weekly run", Category="Groceries"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/search?from=2026-02&to=2026-02&q=nonexistent")
        assert_ok(resp)
        data = resp.json()
        assert data["summary"]["total_count"] == 0


# ---------------------------------------------------------------------------
# GET /api/v1/transactions/export
# ---------------------------------------------------------------------------


class TestExportEndpoint:
    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_returns_csv_content_type(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = [_make_item()]

        resp = api_client.get("/api/v1/transactions/export?from=2026-02&to=2026-02")
        assert_ok(resp)
        assert "text/csv" in resp.headers["content-type"]
        assert "attachment" in resp.headers["content-disposition"]

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_csv_has_correct_headers(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = [_make_item()]

        resp = api_client.get("/api/v1/transactions/export?from=2026-02&to=2026-02")
        reader = csv.reader(io.StringIO(resp.text))
        headers = next(reader)
        assert headers == [
            "Date",
            "Amount",
            "Company",
            "Category",
            "Institution",
            "Type",
            "Name",
            "Comment",
            "Statement Source",
            "Ignored",
        ]

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_csv_data_row_format(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = [
            _make_item(
                Date="02/15/2026 10:30 PST",
                Amount=Decimal("42.50"),
                Company="Test Store",
                Category="groceries",
                Institution="RBC",
                TransactionType="purchase",
                Name="Alice",
            )
        ]

        resp = api_client.get("/api/v1/transactions/export?from=2026-02&to=2026-02")
        reader = csv.reader(io.StringIO(resp.text))
        next(reader)  # skip headers
        row = next(reader)

        # Date should have TZ stripped
        assert row[0] == "02/15/2026 10:30"
        assert row[1] == "42.5"
        assert row[2] == "Test Store"
        assert row[3] == "groceries"
        assert row[4] == "RBC"
        assert row[5] == "purchase"
        assert row[6] == "Alice"

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_csv_filters_apply(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(Category="groceries"),
            _make_item(Category="restaurant/dining", DateFileName="2026.02.10_08.00_b.eml"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/export?from=2026-02&to=2026-02&category=groceries")
        reader = csv.reader(io.StringIO(resp.text))
        rows = list(reader)
        # header + 1 data row
        assert len(rows) == 2

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_csv_no_result_cap(self, mock_run_sync: AsyncMock, api_client) -> None:
        # Create more items than the web cap (1000)
        items = [_make_item(DateFileName=f"2026.02.15_10.{str(i).zfill(2)}_test.eml") for i in range(50)]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/export?from=2026-02&to=2026-02")
        reader = csv.reader(io.StringIO(resp.text))
        rows = list(reader)
        # header + 50 data rows (no cap applied)
        assert len(rows) == 51

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_csv_free_text_q_narrows_rows(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(Company="Costco Wholesale"),
            _make_item(Company="Safeway", DateFileName="2026.02.10_08.00_b.eml"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/export?from=2026-02&to=2026-02&q=costco")
        reader = csv.reader(io.StringIO(resp.text))
        rows = list(reader)
        # header + 1 data row
        assert len(rows) == 2
