"""Tests for the merchant intelligence API endpoint.

Covers ``GET /api/v1/merchants/intelligence`` (audit T9): the happy path
(200 + response shape) plus the query-param bounds — ``month`` must match the
calendar-month pattern and ``months`` must fall in [1, 24].
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from tests.asserts import assert_ok, assert_problem


def _make_intelligence_payload() -> dict[str, Any]:
    """A minimal-but-complete MerchantIntelligenceResponse-shaped dict."""
    return {
        "month": "2026-06",
        "months_analyzed": 6,
        "period": {"from": "2026-01", "to": "2026-06"},
        "merchants": [
            {
                "company": "Spotify",
                "total": 60.0,
                "monthly_amounts": [10.0] * 6,
                "monthly_counts": [1] * 6,
                "months_active": 6,
                "avg_amount": 10.0,
                "frequency_type": "fixed",
                "category": "subscriptions",
                "is_recurring": True,
                "price_change": None,
                "is_new": False,
                "is_churned": False,
            }
        ],
        "summary": {
            "recurring_burn_rate": 10.0,
            "recurring_count": 1,
            "discretionary_this_month": 0.0,
            "new_merchants": [],
            "churned_merchants": [],
            "price_changes": [],
        },
    }


class TestMerchantIntelligence:
    @pytest.mark.parametrize("mock_run_sync", ["merchants"], indirect=True)
    def test_returns_200_and_shape(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = _make_intelligence_payload()

        resp = api_client.get("/api/v1/merchants/intelligence?month=2026-06&months=6")
        assert_ok(resp)

        data = resp.json()
        assert data["month"] == "2026-06"
        assert data["months_analyzed"] == 6
        assert data["period"]["from"] == "2026-01"
        assert len(data["merchants"]) == 1
        assert data["merchants"][0]["company"] == "Spotify"
        assert data["summary"]["recurring_burn_rate"] == 10.0

    @pytest.mark.parametrize("mock_run_sync", ["merchants"], indirect=True)
    def test_defaults_months_to_six(self, mock_run_sync: AsyncMock, api_client) -> None:
        """`months` is optional and defaults to 6 — the service still gets called."""
        mock_run_sync.return_value = _make_intelligence_payload()

        resp = api_client.get("/api/v1/merchants/intelligence?month=2026-06")
        assert_ok(resp)
        # month + default months (6) forwarded to service.get_intelligence
        assert mock_run_sync.call_args.args[1:] == ("2026-06", 6)

    def test_invalid_month_is_422(self, api_client) -> None:
        resp = api_client.get("/api/v1/merchants/intelligence?month=2026-13")
        assert_problem(resp, 422)

    def test_missing_month_is_422(self, api_client) -> None:
        resp = api_client.get("/api/v1/merchants/intelligence")
        assert_problem(resp, 422)

    def test_months_above_max_is_422(self, api_client) -> None:
        resp = api_client.get("/api/v1/merchants/intelligence?month=2026-06&months=25")
        assert_problem(resp, 422)

    def test_months_below_min_is_422(self, api_client) -> None:
        resp = api_client.get("/api/v1/merchants/intelligence?month=2026-06&months=0")
        assert_problem(resp, 422)
