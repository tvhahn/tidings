"""Tests for transaction API endpoints."""

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest

from tests.asserts import assert_ok, assert_problem
from tests.factories import make_transaction_item as _make_item

# ---------------------------------------------------------------------------
# GET /api/v1/transactions
# ---------------------------------------------------------------------------


def _items_sorted_desc() -> list[dict[str, Any]]:
    return [
        _make_item(DateFileName="2026.02.01_08.00_early.eml"),
        _make_item(DateFileName="2026.02.28_20.00_late.eml"),
        _make_item(DateFileName="2026.02.15_12.00_mid.eml"),
    ]


def _check_returns_two(data: dict[str, Any]) -> None:
    assert data["month"] == "2026-02"
    assert data["count"] == 2
    assert len(data["transactions"]) == 2


def _check_strips_large_fields(data: dict[str, Any]) -> None:
    txn = data["transactions"][0]
    for hidden in ("body", "subject", "file_name", "from_name", "transaction_hash"):
        assert hidden not in txn


def _check_converts_decimal(data: dict[str, Any]) -> None:
    txn = data["transactions"][0]
    assert txn["amount"] == 99.99
    assert isinstance(txn["amount"], float)


def _check_sorts_descending(data: dict[str, Any]) -> None:
    names = [t["date_file_name"] for t in data["transactions"]]
    assert names == sorted(names, reverse=True)


class TestListTransactions:
    @pytest.mark.parametrize(
        ("items", "check"),
        [
            (
                [
                    _make_item(DateFileName="2026.02.15_10.30_a.eml"),
                    _make_item(DateFileName="2026.02.10_08.00_b.eml"),
                ],
                _check_returns_two,
            ),
            ([_make_item()], _check_strips_large_fields),
            ([_make_item(Amount=Decimal("99.99"))], _check_converts_decimal),
            (_items_sorted_desc(), _check_sorts_descending),
        ],
        ids=["returns-transactions", "strips-large-fields", "converts-decimal", "sorts-descending"],
    )
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_list_behavior(self, mock_run_sync: AsyncMock, items: list[dict[str, Any]], check: Any, api_client) -> None:
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions?month=2026-02")
        assert_ok(resp)
        check(resp.json())

    def test_missing_month_param_returns_422(self, api_client) -> None:
        resp = api_client.get("/api/v1/transactions")
        assert_problem(resp, 422)

    def test_invalid_month_format_returns_422(self, api_client) -> None:
        resp = api_client.get("/api/v1/transactions?month=Feb-2026")
        assert_problem(resp, 422)

    def test_out_of_range_month_returns_422(self, api_client) -> None:
        # MONTH_PATTERN is calendar-valid: 13 is not a real month.
        resp = api_client.get("/api/v1/transactions?month=2026-13")
        assert_problem(resp, 422)


# ---------------------------------------------------------------------------
# GET /api/v1/transactions/all — combined active + attention + trash buckets
# ---------------------------------------------------------------------------


class TestListAllTransactions:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_splits_into_buckets_sorted_desc(self, mock_run_sync: AsyncMock, api_client) -> None:
        # Two plain-active rows, one miscellaneous row (active AND attention),
        # one soft-deleted row (trash). Fed in scrambled order to prove the
        # handler sorts each bucket by DateFileName descending.
        active_late = _make_item(DateFileName="2026.02.28_20.00_a.eml")
        active_mid = _make_item(DateFileName="2026.02.20_12.00_d.eml")
        attention_row = _make_item(DateFileName="2026.02.15_10.00_b.eml", Category="miscellaneous")
        trash_row = _make_item(
            DateFileName="2026.02.01_08.00_c.eml",
            DeletedAt="2026-02-05T00:00:00-08:00",
        )
        mock_run_sync.return_value = [attention_row, trash_row, active_late, active_mid]

        resp = api_client.get("/api/v1/transactions/all?month=2026-02")
        assert_ok(resp)
        data = resp.json()

        assert data["month"] == "2026-02"

        txns = data["transactions"]
        assert txns["count"] == 3
        assert [t["date_file_name"] for t in txns["transactions"]] == [
            "2026.02.28_20.00_a.eml",
            "2026.02.20_12.00_d.eml",
            "2026.02.15_10.00_b.eml",
        ]

        attention = data["attention"]
        assert attention["count"] == 1
        assert attention["transactions"][0]["date_file_name"] == "2026.02.15_10.00_b.eml"

        trash = data["trash"]
        assert trash["count"] == 1
        assert trash["transactions"][0]["date_file_name"] == "2026.02.01_08.00_c.eml"
        assert trash["transactions"][0]["deleted_at"] == "2026-02-05T00:00:00-08:00"

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_empty_month_yields_zero_counts(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = []

        resp = api_client.get("/api/v1/transactions/all?month=2026-02")
        assert_ok(resp)
        data = resp.json()
        assert data["transactions"]["count"] == 0
        assert data["attention"]["count"] == 0
        assert data["trash"]["count"] == 0

    def test_invalid_month_returns_422(self, api_client) -> None:
        resp = api_client.get("/api/v1/transactions/all?month=2026-13")
        assert_problem(resp, 422)


# ---------------------------------------------------------------------------
# GET /api/v1/transactions/bulk — combined buckets across multiple months
# ---------------------------------------------------------------------------


class TestListBulkTransactions:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_returns_response_keyed_by_month(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.name = "run_sync"
        items_jan = [_make_item(DateFileName="2026.01.10_09.00_j.eml")]
        items_feb = [
            _make_item(DateFileName="2026.02.10_09.00_f.eml", Category="miscellaneous"),
            _make_item(DateFileName="2026.02.20_09.00_g.eml", DeletedAt="2026-02-21T00:00:00-08:00"),
        ]
        # One value per month, in request order (sequential per-month query).
        mock_run_sync.side_effect = [items_jan, items_feb]

        resp = api_client.get("/api/v1/transactions/bulk?months=2026-01,2026-02")
        assert_ok(resp)
        data = resp.json()

        assert set(data.keys()) == {"2026-01", "2026-02"}
        assert mock_run_sync.call_count == 2

        jan = data["2026-01"]
        assert jan["month"] == "2026-01"
        assert jan["transactions"]["count"] == 1
        assert jan["attention"]["count"] == 0
        assert jan["trash"]["count"] == 0

        feb = data["2026-02"]
        assert feb["month"] == "2026-02"
        assert feb["transactions"]["count"] == 1  # the miscellaneous row is active
        assert feb["attention"]["count"] == 1
        assert feb["trash"]["count"] == 1

    def test_more_than_twelve_months_returns_422(self, api_client) -> None:
        # 13 individually-valid months — the length guard fires, not the pattern.
        months = ["2025-12"] + [f"2026-{m:02d}" for m in range(1, 13)]
        assert len(months) == 13
        resp = api_client.get("/api/v1/transactions/bulk?months=" + ",".join(months))
        assert_problem(resp, 422)

    @pytest.mark.parametrize("bad", ["2026-13", "not-a-month"])
    def test_malformed_month_returns_422(self, bad: str, api_client) -> None:
        resp = api_client.get(f"/api/v1/transactions/bulk?months=2026-01,{bad}")
        assert_problem(resp, 422)


# ---------------------------------------------------------------------------
# GET /api/v1/transactions/latest — freshness probe
# ---------------------------------------------------------------------------


class TestLatestTimestamp:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_returns_latest_string(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = "2026.04.20_14.32_abc.eml"
        resp = api_client.get("/api/v1/transactions/latest?month=2026-04")
        assert_ok(resp)
        data = resp.json()
        assert data["month"] == "2026-04"
        assert data["latest"] == "2026.04.20_14.32_abc.eml"

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_returns_null_when_empty(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = None
        resp = api_client.get("/api/v1/transactions/latest?month=2026-04")
        assert_ok(resp)
        assert resp.json() == {"month": "2026-04", "latest": None}

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_month_optional(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = "2026.04.20_14.32_abc.eml"
        resp = api_client.get("/api/v1/transactions/latest")
        assert_ok(resp)
        data = resp.json()
        assert data["month"] is None
        assert data["latest"] == "2026.04.20_14.32_abc.eml"

    def test_invalid_month_returns_422(self, api_client) -> None:
        resp = api_client.get("/api/v1/transactions/latest?month=bogus")
        assert_problem(resp, 422)


# ---------------------------------------------------------------------------
# Endpoint PATCH /api/v1/transactions/{forwarded_to}/{date_file_name}
# ---------------------------------------------------------------------------


class TestUpdateCategory:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_update_returns_old_and_new(self, mock_run_sync: AsyncMock, api_client) -> None:
        # get_item (ledger before-image) then update_category (returns old category).
        mock_run_sync.side_effect = [None, "miscellaneous"]

        resp = api_client.patch(
            "/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml",
            json={"category": "Groceries"},
        )
        assert_ok(resp)

        data = resp.json()
        assert data["old_category"] == "miscellaneous"
        assert data["new_category"] == "groceries"
        assert data["forwarded_to"] == "user@example.com"

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_update_calls_db_with_correct_args(self, mock_run_sync: AsyncMock, api_client) -> None:
        # get_item (ledger before-image) then update_category.
        mock_run_sync.side_effect = [None, "miscellaneous"]

        api_client.patch(
            "/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml",
            json={"category": "Groceries"},
        )

        # Two calls now: the before-image read, then update_category (the last call).
        assert mock_run_sync.call_count == 2
        call_args = mock_run_sync.call_args
        # args: func, forwarded_to, date_file_name, category, source
        assert call_args[0][1] == "user@example.com"
        assert call_args[0][2] == "2026.02.15_10.30_test.eml"
        assert call_args[0][3] == "Groceries"
        assert call_args[0][4] == "manual"


# ---------------------------------------------------------------------------
# Endpoint POST /api/v1/transactions/{forwarded_to}/{date_file_name}/review
# ---------------------------------------------------------------------------


class TestMarkReviewed:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_mark_reviewed_returns_source(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = None

        resp = api_client.post("/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml/review")
        assert_ok(resp)

        data = resp.json()
        assert data["source"] == "manual"
        assert data["forwarded_to"] == "user@example.com"


# ---------------------------------------------------------------------------
# Endpoint POST /api/v1/transactions/{forwarded_to}/{date_file_name}/ignore
# ---------------------------------------------------------------------------


class TestSetIgnored:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_ignore_returns_true(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = None

        resp = api_client.post(
            "/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml/ignore",
            json={"ignored": True},
        )
        assert_ok(resp)

        data = resp.json()
        assert data["ignored"] is True
        assert data["forwarded_to"] == "user@example.com"
        assert data["date_file_name"] == "2026.02.15_10.30_test.eml"

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_unignore_returns_false(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = True

        resp = api_client.post(
            "/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml/ignore",
            json={"ignored": False},
        )
        assert_ok(resp)
        assert resp.json()["ignored"] is False

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_ignore_calls_db_with_correct_args(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = None

        api_client.post(
            "/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml/ignore",
            json={"ignored": True},
        )

        mock_run_sync.assert_called_once()
        call_args = mock_run_sync.call_args
        # args: func, forwarded_to, date_file_name, ignored
        assert call_args[0][1] == "user@example.com"
        assert call_args[0][2] == "2026.02.15_10.30_test.eml"
        assert call_args[0][3] is True


# ---------------------------------------------------------------------------
# Transaction response includes ignored field
# ---------------------------------------------------------------------------


class TestIgnoredFieldInResponse:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_ignored_defaults_to_false(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = [_make_item()]

        resp = api_client.get("/api/v1/transactions?month=2026-02")
        txn = resp.json()["transactions"][0]
        assert txn["ignored"] is False

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_ignored_true_when_set(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = [_make_item(Ignored=True)]

        resp = api_client.get("/api/v1/transactions?month=2026-02")
        txn = resp.json()["transactions"][0]
        assert txn["ignored"] is True

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_ignored_excluded_from_attention(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(Category="miscellaneous", Company="Unknown Shop", Ignored=True),
            _make_item(Category="miscellaneous", Company="Another Shop"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/attention?month=2026-02")
        data = resp.json()
        assert data["count"] == 1
        assert data["transactions"][0]["company"] == "Another Shop"


# ---------------------------------------------------------------------------
# Endpoint PUT /api/v1/transactions/{forwarded_to}/{date_file_name}/comment
# ---------------------------------------------------------------------------


class TestSetComment:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_set_comment_returns_response(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = None

        resp = api_client.put(
            "/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml/comment",
            json={"comment": "split with roommate"},
        )
        assert_ok(resp)

        data = resp.json()
        assert data["forwarded_to"] == "user@example.com"
        assert data["date_file_name"] == "2026.02.15_10.30_test.eml"
        assert data["comment"] == "split with roommate"

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_null_comment_clears(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = "old note"

        resp = api_client.put(
            "/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml/comment",
            json={"comment": None},
        )
        assert_ok(resp)
        assert resp.json()["comment"] is None

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_comment_calls_db_with_correct_args(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = None

        api_client.put(
            "/api/v1/transactions/user%40example.com/2026.02.15_10.30_test.eml/comment",
            json={"comment": "annual renewal"},
        )

        mock_run_sync.assert_called_once()
        call_args = mock_run_sync.call_args
        # args: func, forwarded_to, date_file_name, comment
        assert call_args[0][1] == "user@example.com"
        assert call_args[0][2] == "2026.02.15_10.30_test.eml"
        assert call_args[0][3] == "annual renewal"


# ---------------------------------------------------------------------------
# Transaction response includes comment field
# ---------------------------------------------------------------------------


class TestCommentFieldInResponse:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_comment_defaults_to_null(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = [_make_item()]

        resp = api_client.get("/api/v1/transactions?month=2026-02")
        txn = resp.json()["transactions"][0]
        assert txn["comment"] is None

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_comment_present_when_set(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = [_make_item(Comment="test note")]

        resp = api_client.get("/api/v1/transactions?month=2026-02")
        txn = resp.json()["transactions"][0]
        assert txn["comment"] == "test note"


# ---------------------------------------------------------------------------
# TransactionContext in response
# ---------------------------------------------------------------------------


class TestTransactionContext:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_context_null_by_default(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = [_make_item()]

        resp = api_client.get("/api/v1/transactions?month=2026-02")
        txn = resp.json()["transactions"][0]
        assert txn["context"] is None

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_context_present_when_stored(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = [
            _make_item(
                TransactionContext={
                    "category_month_total": Decimal("340.50"),
                    "merchant_month_count": 3,
                    "category_budget_target": Decimal(400),
                    "category_budget_pct": Decimal("85.1"),
                }
            )
        ]

        resp = api_client.get("/api/v1/transactions?month=2026-02")
        txn = resp.json()["transactions"][0]
        ctx = txn["context"]
        assert ctx is not None
        assert ctx["category_month_total"] == 340.50
        assert ctx["merchant_month_count"] == 3
        assert ctx["category_budget_target"] == 400.0
        assert ctx["category_budget_pct"] == 85.1

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_context_without_budget_fields(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = [
            _make_item(
                TransactionContext={
                    "category_month_total": Decimal(50),
                    "merchant_month_count": 1,
                }
            )
        ]

        resp = api_client.get("/api/v1/transactions?month=2026-02")
        txn = resp.json()["transactions"][0]
        ctx = txn["context"]
        assert ctx is not None
        assert ctx["category_month_total"] == 50.0
        assert ctx["category_budget_target"] is None
        assert ctx["category_budget_pct"] is None
