"""Tests for PATCH /api/v1/transactions/bulk — bulk category update."""

from unittest.mock import AsyncMock

import pytest

from tests.asserts import assert_ok, assert_problem


class TestBulkCategoryUpdate:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_bulk_update_all_succeed(self, mock_run_sync: AsyncMock, api_client) -> None:
        # Per row the handler reads the pre-mutation projection (get_item, for the
        # ledger before-image) then update_category (returns the old category).
        mock_run_sync.side_effect = [None, "Miscellaneous", None, "Restaurant/Dining", None, "Groceries"]

        resp = api_client.patch(
            "/api/v1/transactions/bulk",
            json={
                "updates": [
                    {"forwarded_to": "a@e.com", "date_file_name": "2026.02.01_1.eml", "category": "Groceries"},
                    {"forwarded_to": "a@e.com", "date_file_name": "2026.02.02_2.eml", "category": "Groceries"},
                    {"forwarded_to": "a@e.com", "date_file_name": "2026.02.03_3.eml", "category": "Restaurant/Dining"},
                ],
                "source": "test_bulk",
            },
        )
        assert_ok(resp)
        body = resp.json()
        assert body["total"] == 3
        assert body["succeeded"] == 3
        assert body["failed"] == 0
        assert all(r["ok"] for r in body["results"])
        assert body["results"][0]["old_category"] == "Miscellaneous"
        assert body["results"][0]["new_category"] == "Groceries"

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_bulk_update_partial_failure(self, mock_run_sync: AsyncMock, api_client) -> None:
        # Per row: get_item (ledger before-image) then update_category. Row 2's
        # update raises — failures are per-row, no rollback.
        mock_run_sync.side_effect = [None, "Old", None, RuntimeError("item missing"), None, "Other"]

        resp = api_client.patch(
            "/api/v1/transactions/bulk",
            json={
                "updates": [
                    {"forwarded_to": "a@e.com", "date_file_name": "1.eml", "category": "X"},
                    {"forwarded_to": "a@e.com", "date_file_name": "2.eml", "category": "Y"},
                    {"forwarded_to": "a@e.com", "date_file_name": "3.eml", "category": "Z"},
                ]
            },
        )
        assert_ok(resp)
        body = resp.json()
        assert body["total"] == 3
        assert body["succeeded"] == 2
        assert body["failed"] == 1

        assert body["results"][0]["ok"] is True
        assert body["results"][1]["ok"] is False
        assert "item missing" in body["results"][1]["error"]
        assert body["results"][2]["ok"] is True

    def test_bulk_update_empty_list_is_noop(self, api_client):
        resp = api_client.patch("/api/v1/transactions/bulk", json={"updates": []})
        assert_ok(resp)
        body = resp.json()
        assert body == {"total": 0, "succeeded": 0, "failed": 0, "results": []}

    def test_bulk_update_rejects_malformed_body(self, api_client):
        # Missing `category` field on a row
        resp = api_client.patch(
            "/api/v1/transactions/bulk",
            json={"updates": [{"forwarded_to": "a@e.com", "date_file_name": "1.eml"}]},
        )
        assert_problem(resp, 422)
        assert resp.json()["code"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_source_defaults_to_manual_bulk(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = "Old"

        resp = api_client.patch(
            "/api/v1/transactions/bulk",
            json={
                "updates": [
                    {"forwarded_to": "a@e.com", "date_file_name": "1.eml", "category": "X"},
                ]
            },
        )
        assert_ok(resp)
        # run_sync called as (update_category_fn, forwarded_to, date_file_name, category, source)
        args, _ = mock_run_sync.call_args
        assert args[-1] == "manual_bulk"
