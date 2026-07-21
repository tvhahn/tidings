"""Tests for ``PATCH /api/v1/transactions/{tx_id}`` partial updates.

The PATCH endpoint accepts any subset of ``{category, state, reviewed}``.
``state`` consolidates the three legacy ``/review``, ``/ignore``, ``/delete``
POST endpoints into a single state machine; the legacy endpoints stay
mounted but are flagged ``deprecated=True`` in OpenAPI.

Test surface:

- ``state="active"``  → clears ignored + deleted
- ``state="ignored"`` → sets ignored
- ``state="trashed"`` → sets deleted, response carries DeletedAt timestamp
- ``reviewed=True``   → marks the category audit
- combined fields in one request → all calls fire
- empty body         → no-op, all-None response
- legacy ``{category}``-only call still works (covered by test_api_transactions.py)

The point of this file is the *new* partial-PATCH behavior that lives at the
same path as the existing category-only PATCH.
"""

from unittest.mock import AsyncMock

import pytest

from tests.asserts import assert_ok, assert_problem

# tx_id base64url of "user@example.com|2026.02.15_10.30_test.eml"
_TX_ID = "dXNlckBleGFtcGxlLmNvbXwyMDI2LjAyLjE1XzEwLjMwX3Rlc3QuZW1s"
_PATH = f"/api/v1/transactions/{_TX_ID}"


class TestPatchState:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_state_active_clears_both_flags(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = None

        resp = api_client.patch(_PATH, json={"state": "active"})
        assert_ok(resp)

        body = resp.json()
        assert body["state"] == "active"
        assert body["new_category"] is None
        assert body["reviewed"] is None
        assert body["deleted_at"] is None
        # Three calls: get_item (ledger before-image) + set_ignored(False) + set_deleted(False)
        assert mock_run_sync.call_count == 3

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_state_ignored_sets_ignored_flag(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = None

        resp = api_client.patch(_PATH, json={"state": "ignored"})
        assert_ok(resp)

        body = resp.json()
        assert body["state"] == "ignored"
        # Two calls: get_item (ledger before-image) + set_ignored(True)
        assert mock_run_sync.call_count == 2
        # Verify it was set_ignored with True
        call_args = mock_run_sync.call_args
        # call args are db.set_ignored, forwarded_to, date_file_name, True
        assert call_args[0][3] is True

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_state_trashed_sets_deleted_and_returns_timestamp(self, mock_run_sync: AsyncMock, api_client) -> None:
        # Calls: get_item (ledger before-image), set_deleted, get_item (re-read
        # that surfaces the just-stamped DeletedAt).
        mock_run_sync.side_effect = [
            None,
            None,
            {"DeletedAt": "2026-04-20T18:42:11Z"},
        ]

        resp = api_client.patch(_PATH, json={"state": "trashed"})
        assert_ok(resp)

        body = resp.json()
        assert body["state"] == "trashed"
        assert body["deleted_at"] == "2026-04-20T18:42:11Z"
        assert mock_run_sync.call_count == 3

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_state_trashed_handles_missing_item(self, mock_run_sync: AsyncMock, api_client) -> None:
        # get_item (before-image), set_deleted, get_item (re-read) all empty.
        mock_run_sync.side_effect = [None, None, None]

        resp = api_client.patch(_PATH, json={"state": "trashed"})
        assert_ok(resp)

        body = resp.json()
        assert body["state"] == "trashed"
        assert body["deleted_at"] is None


class TestPatchReviewed:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_reviewed_true_marks_audit(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = None

        resp = api_client.patch(_PATH, json={"reviewed": True})
        assert_ok(resp)

        body = resp.json()
        assert body["reviewed"] is True
        assert body["state"] is None
        assert body["new_category"] is None
        # get_item (ledger before-image) + mark_category_reviewed
        assert mock_run_sync.call_count == 2
        # Last positional arg is the audit source label
        assert mock_run_sync.call_args[0][3] == "manual"

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_reviewed_false_is_no_op(self, mock_run_sync: AsyncMock, api_client) -> None:
        """Review is one-way; ``reviewed=False`` shouldn't unmark."""
        mock_run_sync.return_value = None

        resp = api_client.patch(_PATH, json={"reviewed": False})
        assert_ok(resp)

        body = resp.json()
        assert body["reviewed"] is None
        assert mock_run_sync.call_count == 0


class TestPatchCombined:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_state_ignored_plus_reviewed_in_one_request(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = None

        resp = api_client.patch(_PATH, json={"state": "ignored", "reviewed": True})
        assert_ok(resp)

        body = resp.json()
        assert body["state"] == "ignored"
        assert body["reviewed"] is True
        # get_item (ledger before-image) + set_ignored + mark_category_reviewed
        assert mock_run_sync.call_count == 3

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_category_plus_reviewed(self, mock_run_sync: AsyncMock, api_client) -> None:
        # get_item (ledger before-image), update_category (returns the old
        # category), mark_category_reviewed (returns None).
        mock_run_sync.side_effect = [None, "miscellaneous", None]

        resp = api_client.patch(_PATH, json={"category": "Groceries", "reviewed": True})
        assert_ok(resp)

        body = resp.json()
        assert body["old_category"] == "miscellaneous"
        assert body["new_category"] == "groceries"
        assert body["reviewed"] is True
        assert mock_run_sync.call_count == 3


class TestPatchEmptyBody:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_empty_body_is_no_op(self, mock_run_sync: AsyncMock, api_client) -> None:
        resp = api_client.patch(_PATH, json={})
        assert_ok(resp)

        body = resp.json()
        # No db calls, all response fields None.
        assert mock_run_sync.call_count == 0
        assert body["old_category"] is None
        assert body["new_category"] is None
        assert body["state"] is None
        assert body["reviewed"] is None
        assert body["deleted_at"] is None
        # Identity still echoed.
        assert body["forwarded_to"] == "user@example.com"
        assert body["date_file_name"] == "2026.02.15_10.30_test.eml"


class TestPatchInvalidState:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_unknown_state_value_rejected(self, mock_run_sync: AsyncMock, api_client) -> None:
        resp = api_client.patch(_PATH, json={"state": "purgatory"})
        assert_problem(resp, 422)
        assert mock_run_sync.call_count == 0
