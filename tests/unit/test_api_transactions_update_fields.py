"""PUT /api/v1/transactions/{forwarded_to}/{date_file_name}/fields tests.

Split out of test_api_transactions.py — the field-edit endpoint was the single
largest class in that module and stands alone cleanly.
"""

from unittest.mock import AsyncMock

import pytest

from tests.asserts import assert_ok, assert_problem

# ---------------------------------------------------------------------------
# Endpoint PUT /api/v1/transactions/{forwarded_to}/{date_file_name}/fields
# ---------------------------------------------------------------------------


class TestUpdateFields:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_update_all_three_fields(self, mock_run_sync: AsyncMock, api_client) -> None:
        # Two run_sync dispatches when company changes: override lookup, then db update.
        mock_run_sync.side_effect = [
            None,
            {
                "old_company": None,
                "old_amount": None,
                "old_transaction_type": None,
                "old_category": "miscellaneous",
            },
        ]

        resp = api_client.put(
            "/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml/fields",
            json={"company": "Walmart", "amount": 25.99, "transaction_type": "purchase"},
        )
        assert_ok(resp)

        data = resp.json()
        assert data["forwarded_to"] == "user@example.com"
        assert data["company"] == "Walmart"
        assert data["amount"] == 25.99
        assert data["transaction_type"] == "purchase"
        assert data["old_values"]["company"] is None
        assert data["old_values"]["amount"] is None
        assert data["old_values"]["transaction_type"] is None

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_partial_update_company_only(self, mock_run_sync: AsyncMock, api_client) -> None:
        # Company changes → override lookup (None here), then db update.
        mock_run_sync.side_effect = [
            None,
            {
                "old_company": "Old Store",
                "old_amount": 10.0,
                "old_transaction_type": "purchase",
                "old_category": "groceries",
            },
        ]

        resp = api_client.put(
            "/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml/fields",
            json={"company": "New Store"},
        )
        assert_ok(resp)

        data = resp.json()
        assert data["company"] == "New Store"
        assert data["amount"] == 10.0  # kept from old values
        assert data["transaction_type"] == "purchase"  # kept from old values

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_partial_update_amount_only(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = {
            "old_company": "Test Store",
            "old_amount": 10.0,
            "old_transaction_type": "purchase",
            "old_category": "groceries",
        }

        resp = api_client.put(
            "/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml/fields",
            json={"amount": 99.99},
        )
        assert_ok(resp)

        data = resp.json()
        assert data["amount"] == 99.99
        assert data["company"] == "Test Store"  # kept from old

    def test_amount_zero_rejected(self, api_client):
        resp = api_client.put(
            "/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml/fields",
            json={"amount": 0},
        )
        assert_problem(resp, 422)

    def test_amount_negative_rejected(self, api_client):
        resp = api_client.put(
            "/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml/fields",
            json={"amount": -5.00},
        )
        assert_problem(resp, 422)

    def test_invalid_transaction_type_rejected(self, api_client):
        resp = api_client.put(
            "/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml/fields",
            json={"transaction_type": "refund"},
        )
        assert_problem(resp, 422)

    def test_empty_request_rejected(self, api_client):
        resp = api_client.put(
            "/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml/fields",
            json={},
        )
        assert_problem(resp, 422)

    def test_empty_company_rejected(self, api_client):
        resp = api_client.put(
            "/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml/fields",
            json={"company": "  "},
        )
        assert_problem(resp, 422)

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_category_override_auto_applied(self, mock_run_sync: AsyncMock, api_client) -> None:
        # The override lookup (first run_sync dispatch) resolves a category, which
        # the endpoint auto-applies; the db update is the second dispatch.
        mock_run_sync.side_effect = [
            "groceries",
            {
                "old_company": None,
                "old_amount": None,
                "old_transaction_type": None,
                "old_category": "miscellaneous",
            },
        ]

        resp = api_client.put(
            "/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml/fields",
            json={"company": "walmart"},
        )
        assert_ok(resp)
        data = resp.json()
        assert data["category"] == "groceries"

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_valid_transaction_types(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = {
            "old_company": None,
            "old_amount": None,
            "old_transaction_type": None,
            "old_category": "miscellaneous",
        }

        for tt in ["purchase", "withdrawal", "preauth", "e-transfer", "deposit"]:
            resp = api_client.put(
                "/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml/fields",
                json={"transaction_type": tt},
            )
            assert_ok(resp)

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_calls_db_with_correct_args(self, mock_run_sync: AsyncMock, api_client) -> None:
        # First dispatch = override lookup (None), second = db.update_fields.
        mock_run_sync.side_effect = [
            None,
            {
                "old_company": None,
                "old_amount": None,
                "old_transaction_type": None,
                "old_category": "miscellaneous",
            },
        ]

        api_client.put(
            "/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml/fields",
            json={"company": "Walmart", "amount": 25.99},
        )

        assert mock_run_sync.call_count == 2
        # The db update is the last dispatch: func, forwarded_to, date_file_name, fields, category
        call_args = mock_run_sync.call_args
        assert call_args[0][1] == "user@example.com"
        assert call_args[0][2] == "2026.02.15_10.30_test.eml"
        assert call_args[0][3] == {"company": "Walmart", "amount": 25.99}

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_company_whitespace_stripped(self, mock_run_sync: AsyncMock, api_client) -> None:
        # Company changes → override lookup (None), then db update.
        mock_run_sync.side_effect = [
            None,
            {
                "old_company": None,
                "old_amount": None,
                "old_transaction_type": None,
                "old_category": "miscellaneous",
            },
        ]

        resp = api_client.put(
            "/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml/fields",
            json={"company": "  Walmart  "},
        )
        assert_ok(resp)
        assert resp.json()["company"] == "Walmart"
