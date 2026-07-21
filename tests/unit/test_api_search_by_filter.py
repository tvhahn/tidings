"""Tests for ``POST /api/v1/transactions/search-by-filter``.

Sibling endpoint to ``GET /transactions/search`` that accepts array
(any-of) filters in a JSON body. The GET form covers single-value
filtering, validation of the month-range, capping, etc. — the GET test
file ``test_api_search.py`` already exercises that. This file covers the
POST-shaped surface area and the array semantics that don't exist on
the GET.
"""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from tests.asserts import assert_ok, assert_problem
from tests.factories import make_transaction_item as _make_item

_PATH = "/api/v1/transactions/search-by-filter"


class TestMerchantIn:
    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_any_of_substring_match(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(Company="WHOLE FOODS MARKET"),
            _make_item(Company="TRADER JOES", DateFileName="2026.02.10_08.00_b.eml"),
            _make_item(Company="STARBUCKS", DateFileName="2026.02.12_08.00_c.eml"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.post(
            _PATH,
            json={
                "from_month": "2026-02",
                "to_month": "2026-02",
                "merchant_in": ["whole foods", "trader joe"],
            },
        )
        assert_ok(resp)

        data = resp.json()
        assert data["summary"]["total_count"] == 2
        companies = {t["company"] for t in data["transactions"]}
        assert "STARBUCKS" not in companies

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_single_element_list(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(Company="COSTCO WHOLESALE"),
            _make_item(Company="SAFEWAY", DateFileName="2026.02.10_08.00_b.eml"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.post(
            _PATH,
            json={"from_month": "2026-02", "to_month": "2026-02", "merchant_in": ["costco"]},
        )
        data = resp.json()
        assert data["summary"]["total_count"] == 1
        assert "COSTCO" in data["transactions"][0]["company"]

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_empty_list_means_no_filter(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [_make_item(), _make_item(DateFileName="2026.02.10_08.00_b.eml")]
        mock_run_sync.return_value = items

        resp = api_client.post(
            _PATH,
            json={"from_month": "2026-02", "to_month": "2026-02", "merchant_in": []},
        )
        data = resp.json()
        assert data["summary"]["total_count"] == 2


class TestCategoryIn:
    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_any_of_exact_match_case_insensitive(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(Category="groceries"),
            _make_item(Category="restaurants", DateFileName="2026.02.10_08.00_b.eml"),
            _make_item(Category="entertainment", DateFileName="2026.02.12_08.00_c.eml"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.post(
            _PATH,
            json={
                "from_month": "2026-02",
                "to_month": "2026-02",
                "category_in": ["Groceries", "Restaurants"],
            },
        )
        data = resp.json()
        assert data["summary"]["total_count"] == 2
        cats = {t["category"] for t in data["transactions"]}
        assert cats == {"groceries", "restaurants"}


class TestCombinedFilters:
    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_category_plus_amount_range(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(Category="groceries", Amount=Decimal("12.00")),
            _make_item(Category="groceries", Amount=Decimal("80.00"), DateFileName="2026.02.10_08.00_b.eml"),
            _make_item(
                Category="groceries",
                Amount=Decimal("250.00"),
                DateFileName="2026.02.12_08.00_c.eml",
            ),
            _make_item(
                Category="restaurants",
                Amount=Decimal("50.00"),
                DateFileName="2026.02.14_08.00_d.eml",
            ),
        ]
        mock_run_sync.return_value = items

        resp = api_client.post(
            _PATH,
            json={
                "from_month": "2026-02",
                "to_month": "2026-02",
                "category_in": ["groceries"],
                "min_amount": 20,
                "max_amount": 200,
            },
        )
        data = resp.json()
        assert data["summary"]["total_count"] == 1
        assert data["transactions"][0]["amount"] == 80.0


class TestVisibility:
    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_excludes_deleted_by_default(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(),
            _make_item(DeletedAt="2026-02-20T10:00:00Z", DateFileName="2026.02.10_08.00_b.eml"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.post(_PATH, json={"from_month": "2026-02", "to_month": "2026-02"})
        data = resp.json()
        assert data["summary"]["total_count"] == 1


class TestValidation:
    def test_invalid_month_format_rejected(self, api_client) -> None:
        resp = api_client.post(_PATH, json={"from_month": "2026-13", "to_month": "2026-02"})
        assert_problem(resp, 422)

    @pytest.mark.parametrize("mock_run_sync", ["search"], indirect=True)
    def test_to_before_from_rejected(self, mock_run_sync: AsyncMock, api_client) -> None:
        # Validates inside the handler via _generate_month_keys.
        resp = api_client.post(_PATH, json={"from_month": "2026-04", "to_month": "2026-02"})
        assert_problem(resp, 422)
