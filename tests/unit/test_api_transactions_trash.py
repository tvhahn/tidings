"""Soft-delete / trash / permanent-delete tests for the transactions API.

Split out of test_api_transactions.py — the deletion lifecycle (soft-delete
filtering, the trash list, restore, and permanent delete) is its own seam.
"""

from unittest.mock import AsyncMock

import pytest

from tests.asserts import assert_ok, assert_problem
from tests.factories import make_transaction_item as _make_item

# ---------------------------------------------------------------------------
# Soft delete filtering
# ---------------------------------------------------------------------------


class TestDeletedFiltering:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_list_excludes_deleted(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(Company="Active Store"),
            _make_item(Company="Deleted Store", DeletedAt="2026-02-20T00:00:00+00:00"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions?month=2026-02")
        data = resp.json()
        assert data["count"] == 1
        assert data["transactions"][0]["company"] == "Active Store"

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_attention_excludes_deleted(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(Category="miscellaneous", Company="Unknown Shop", DeletedAt="2026-02-20T00:00:00+00:00"),
            _make_item(Category="miscellaneous", Company="Another Shop"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/attention?month=2026-02")
        data = resp.json()
        assert data["count"] == 1
        assert data["transactions"][0]["company"] == "Another Shop"

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_deleted_at_in_response(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = [_make_item(DeletedAt="2026-02-20T00:00:00+00:00")]

        resp = api_client.get("/api/v1/transactions/trash?month=2026-02")
        txn = resp.json()["transactions"][0]
        assert txn["deleted_at"] == "2026-02-20T00:00:00+00:00"

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_deleted_at_defaults_to_null(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = [_make_item()]

        resp = api_client.get("/api/v1/transactions?month=2026-02")
        txn = resp.json()["transactions"][0]
        assert txn["deleted_at"] is None


# ---------------------------------------------------------------------------
# GET /api/v1/transactions/trash
# ---------------------------------------------------------------------------


class TestTrashList:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_returns_only_deleted(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(Company="Active Store"),
            _make_item(Company="Deleted Store", DeletedAt="2026-02-20T00:00:00+00:00"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/trash?month=2026-02")
        assert_ok(resp)

        data = resp.json()
        assert data["count"] == 1
        assert data["transactions"][0]["company"] == "Deleted Store"

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_empty_trash(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = [_make_item()]

        resp = api_client.get("/api/v1/transactions/trash?month=2026-02")
        data = resp.json()
        assert data["count"] == 0
        assert data["transactions"] == []


# ---------------------------------------------------------------------------
# Endpoint POST /api/v1/transactions/{forwarded_to}/{date_file_name}/delete
# ---------------------------------------------------------------------------


class TestSoftDelete:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_soft_delete_returns_deleted_at(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.side_effect = [
            None,  # set_deleted
            _make_item(DeletedAt="2026-02-20T00:00:00+00:00"),  # get_item
        ]

        resp = api_client.post(
            "/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml/delete",
            json={"deleted": True},
        )
        assert_ok(resp)

        data = resp.json()
        assert data["deleted_at"] == "2026-02-20T00:00:00+00:00"
        assert data["forwarded_to"] == "user@example.com"

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_restore_returns_null_deleted_at(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = "2026-02-20T00:00:00+00:00"

        resp = api_client.post(
            "/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml/delete",
            json={"deleted": False},
        )
        assert_ok(resp)
        assert resp.json()["deleted_at"] is None


# ---------------------------------------------------------------------------
# Endpoint DELETE /api/v1/transactions/{forwarded_to}/{date_file_name}
# ---------------------------------------------------------------------------


class TestPermanentDelete:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_permanent_delete_returns_keys(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = _make_item()

        resp = api_client.delete("/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml")
        assert_ok(resp)

        data = resp.json()
        assert data["forwarded_to"] == "user@example.com"
        assert data["date_file_name"] == "2026.02.15_10.30_test.eml"

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_permanent_delete_not_found(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = None

        resp = api_client.delete("/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml")
        assert_problem(resp, 404)
