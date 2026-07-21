"""Tests for category overrides API endpoints."""

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from src.api.routers.overrides import _query_correction_items
from src.finance import demo_clock
from src.finance.exceptions import VersionConflictError
from tests.asserts import assert_ok, assert_problem

# 2026-12-31 16:30 Pacific == 2027-01-01 00:30 UTC. Pacific-expressed so
# ``freeze_clock`` makes ``app_today()`` resolve the Pacific calendar date.
_YEAR_BOUNDARY = datetime(2026, 12, 31, 16, 30, tzinfo=ZoneInfo("America/Los_Angeles"))


def _make_overrides_item(
    data: dict[str, str] | None = None,
    version: int = 1,
    dismissed: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a fake DynamoDB overrides item."""
    if data is None:
        data = {"AMAZON.CA": "Miscellaneous", "BOOSTER JUICE # 232": "Restaurant/Dining"}
    item: dict[str, Any] = {
        "PK": "USER#default",
        "SK": "CONFIG#category_overrides",
        "Data": data,
        "Version": version,
    }
    if dismissed is not None:
        item["Dismissed"] = dismissed
    return item


# ---------------------------------------------------------------------------
# GET /api/v1/overrides
# ---------------------------------------------------------------------------


class TestListOverrides:
    @pytest.mark.parametrize("mock_run_sync", ["overrides"], indirect=True)
    def test_returns_overrides(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = _make_overrides_item()
        resp = api_client.get("/api/v1/overrides")
        assert_ok(resp)
        body = resp.json()
        assert body["count"] == 2
        assert body["version"] == 1
        # Sorted by company name
        assert body["overrides"][0]["company"] == "AMAZON.CA"
        assert body["overrides"][1]["company"] == "BOOSTER JUICE # 232"

    @pytest.mark.parametrize("mock_run_sync", ["overrides"], indirect=True)
    def test_returns_empty_when_not_seeded(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = None
        resp = api_client.get("/api/v1/overrides")
        assert_ok(resp)
        body = resp.json()
        assert body["count"] == 0
        assert body["version"] == 0
        assert body["overrides"] == []


# ---------------------------------------------------------------------------
# Endpoint PUT /api/v1/overrides/{company}
# ---------------------------------------------------------------------------


class TestPutOverride:
    @patch("src.api.routers.overrides.invalidate_category_overrides_cache")
    @pytest.mark.parametrize("mock_run_sync", ["overrides"], indirect=True)
    def test_adds_override(self, mock_invalidate: MagicMock, mock_run_sync: AsyncMock, api_client) -> None:
        # Calls: get_overrides (ledger before-image), put_override, get_overrides (response)
        mock_run_sync.side_effect = [
            None,  # get_overrides before-image (no existing override → create-shaped)
            None,  # put_override returns None (version ignored in this path)
            _make_overrides_item(
                data={"AMAZON.CA": "Miscellaneous", "NEW CO": "Rent"},
                version=2,
            ),
        ]
        resp = api_client.put(
            "/api/v1/overrides/NEW%20CO",
            json={"category": "Rent"},
        )
        assert_ok(resp)
        body = resp.json()
        assert body["count"] == 2
        mock_invalidate.assert_called_once()

    @patch("src.api.routers.overrides.invalidate_category_overrides_cache")
    @pytest.mark.parametrize("mock_run_sync", ["overrides"], indirect=True)
    def test_adds_override_with_slash_in_name(
        self, mock_invalidate: MagicMock, mock_run_sync: AsyncMock, api_client
    ) -> None:
        """Company names containing '/' should not cause 405 Method Not Allowed."""
        mock_run_sync.side_effect = [
            None,  # get_overrides before-image
            None,  # put_override
            _make_overrides_item(
                data={"Rembours. d'impôt/Tax Refund": "Miscellaneous"},
                version=2,
            ),
        ]
        resp = api_client.put(
            "/api/v1/overrides/Rembours.%20d'imp%C3%B4t%2FTax%20Refund",
            json={"category": "Miscellaneous"},
        )
        assert_ok(resp)
        body = resp.json()
        assert body["count"] == 1
        mock_invalidate.assert_called_once()

    @patch("src.api.routers.overrides.invalidate_category_overrides_cache")
    @pytest.mark.parametrize("mock_run_sync", ["overrides"], indirect=True)
    def test_returns_409_on_conflict(self, mock_invalidate: MagicMock, mock_run_sync: AsyncMock, api_client) -> None:
        # get_overrides before-image succeeds; put_override raises the conflict.
        mock_run_sync.side_effect = [None, VersionConflictError("conflict")]
        resp = api_client.put(
            "/api/v1/overrides/WHATEVER",
            json={"category": "Rent"},
        )
        assert_problem(resp, 409)


# ---------------------------------------------------------------------------
# Endpoint DELETE /api/v1/overrides/{company}
# ---------------------------------------------------------------------------


class TestDeleteOverride:
    @patch("src.api.routers.overrides.invalidate_category_overrides_cache")
    @pytest.mark.parametrize("mock_run_sync", ["overrides"], indirect=True)
    def test_deletes_override(self, mock_invalidate: MagicMock, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = None  # delete_override returns version
        resp = api_client.delete("/api/v1/overrides/AMAZON.CA")
        assert_ok(resp)
        mock_invalidate.assert_called_once()

    @pytest.mark.parametrize("mock_run_sync", ["overrides"], indirect=True)
    def test_returns_404_when_not_found(self, mock_run_sync: AsyncMock, api_client) -> None:
        # get_overrides before-image succeeds; delete_override raises KeyError.
        mock_run_sync.side_effect = [None, KeyError("NONEXISTENT")]
        resp = api_client.delete("/api/v1/overrides/NONEXISTENT")
        assert_problem(resp, 404)

    @pytest.mark.parametrize("mock_run_sync", ["overrides"], indirect=True)
    def test_returns_409_on_version_conflict(self, mock_run_sync: AsyncMock, api_client) -> None:
        # get_overrides before-image succeeds; delete_override raises the conflict.
        mock_run_sync.side_effect = [None, VersionConflictError("conflict")]
        resp = api_client.delete("/api/v1/overrides/WHATEVER")
        assert_problem(resp, 409)


# ---------------------------------------------------------------------------
# GET /api/v1/overrides/suggestions
# ---------------------------------------------------------------------------


class TestGetSuggestions:
    @pytest.mark.parametrize("mock_run_sync", ["overrides"], indirect=True)
    def test_returns_suggestions(self, mock_run_sync: AsyncMock, api_client) -> None:
        # run_sync is called twice: svc.get_overrides, then _query_correction_items
        # (the CategoryAudit-carrying items across the queried months).
        mock_run_sync.side_effect = [
            _make_overrides_item(data={"EXISTING": "Rent"}),
            [
                {
                    "Company": "NEW MERCHANT",
                    "Category": "Groceries",
                    "CategoryAudit": {"source": "manual", "reviewed_at": "2026-02-01T00:00:00"},
                },
                {
                    "Company": "NEW MERCHANT",
                    "Category": "Groceries",
                    "CategoryAudit": {"source": "manual", "reviewed_at": "2026-02-15T00:00:00"},
                },
                {
                    "Company": "EXISTING",
                    "Category": "Rent",
                    "CategoryAudit": {"source": "manual", "reviewed_at": "2026-02-10T00:00:00"},
                },
            ],
        ]

        resp = api_client.get("/api/v1/overrides/suggestions?months=1")
        assert_ok(resp)
        body = resp.json()
        assert body["count"] == 1
        assert body["suggestions"][0]["company"] == "NEW MERCHANT"
        assert body["suggestions"][0]["suggested_category"] == "Groceries"
        assert body["suggestions"][0]["correction_count"] == 2

    @pytest.mark.parametrize("mock_run_sync", ["overrides"], indirect=True)
    def test_returns_suggestion_for_single_correction(self, mock_run_sync: AsyncMock, api_client) -> None:
        """A company with exactly 1 manual correction should generate a suggestion."""
        mock_run_sync.side_effect = [
            _make_overrides_item(data={}),
            [
                {
                    "Company": "SOLO MERCHANT",
                    "Category": "Groceries",
                    "CategoryAudit": {"source": "manual", "reviewed_at": "2026-02-20T00:00:00"},
                },
            ],
        ]

        resp = api_client.get("/api/v1/overrides/suggestions?months=1")
        assert_ok(resp)
        body = resp.json()
        assert body["count"] == 1
        assert body["suggestions"][0]["company"] == "SOLO MERCHANT"
        assert body["suggestions"][0]["suggested_category"] == "Groceries"
        assert body["suggestions"][0]["correction_count"] == 1

    @pytest.mark.parametrize("mock_run_sync", ["overrides"], indirect=True)
    def test_returns_empty_on_query_failure(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.side_effect = [
            _make_overrides_item(data={}),
            Exception("connection failed"),
        ]

        resp = api_client.get("/api/v1/overrides/suggestions?months=1")
        assert_ok(resp)
        assert resp.json()["count"] == 0
        assert resp.json()["suggestions"] == []

    @pytest.mark.parametrize("mock_run_sync", ["overrides"], indirect=True)
    def test_returns_empty_when_no_corrections(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.side_effect = [
            _make_overrides_item(data={}),
            [],
        ]

        resp = api_client.get("/api/v1/overrides/suggestions?months=1")
        assert_ok(resp)
        assert resp.json()["count"] == 0

    @pytest.mark.parametrize("mock_run_sync", ["overrides"], indirect=True)
    def test_filters_dismissed_suggestions(self, mock_run_sync: AsyncMock, api_client) -> None:
        """Dismissed suggestions should not appear in the results."""
        mock_run_sync.side_effect = [
            _make_overrides_item(
                data={},
                dismissed={"new merchant|groceries": "2026-02-20T00:00:00+00:00"},
            ),
            [
                {
                    "Company": "NEW MERCHANT",
                    "Category": "Groceries",
                    "CategoryAudit": {"source": "manual", "reviewed_at": "2026-02-15T00:00:00"},
                },
            ],
        ]

        resp = api_client.get("/api/v1/overrides/suggestions?months=1")
        assert_ok(resp)
        assert resp.json()["count"] == 0

    @pytest.mark.parametrize("mock_run_sync", ["overrides"], indirect=True)
    def test_resurfaces_dismissed_with_newer_correction(self, mock_run_sync: AsyncMock, api_client) -> None:
        """A dismissed suggestion should resurface if a newer correction exists."""
        mock_run_sync.side_effect = [
            _make_overrides_item(
                data={},
                dismissed={"new merchant|groceries": "2026-02-10T00:00:00+00:00"},
            ),
            [
                {
                    "Company": "NEW MERCHANT",
                    "Category": "Groceries",
                    "CategoryAudit": {"source": "manual", "reviewed_at": "2026-02-20T00:00:00"},
                },
            ],
        ]

        resp = api_client.get("/api/v1/overrides/suggestions?months=1")
        assert_ok(resp)
        body = resp.json()
        assert body["count"] == 1
        assert body["suggestions"][0]["company"] == "NEW MERCHANT"

    @pytest.mark.parametrize("months", ["0", "25", "100000"])
    @pytest.mark.parametrize("mock_run_sync", ["overrides"], indirect=True)
    def test_rejects_out_of_range_months(self, mock_run_sync: AsyncMock, months: str, api_client) -> None:
        """`months` is bounded to 1..24 — out-of-range values are rejected pre-handler."""
        resp = api_client.get(f"/api/v1/overrides/suggestions?months={months}")
        assert_problem(resp, 422)

    @pytest.mark.parametrize("mock_run_sync", ["overrides"], indirect=True)
    def test_default_months_is_accepted(self, mock_run_sync: AsyncMock, api_client) -> None:
        """No `months` param uses the default (12) and succeeds."""
        mock_run_sync.side_effect = [
            _make_overrides_item(data={}),
            [],
        ]
        resp = api_client.get("/api/v1/overrides/suggestions")
        assert_ok(resp)
        assert resp.json()["count"] == 0


# ---------------------------------------------------------------------------
# POST /api/v1/overrides/suggestions/dismissed
# ---------------------------------------------------------------------------


class TestDismissSuggestion:
    @pytest.mark.parametrize("mock_run_sync", ["overrides"], indirect=True)
    def test_dismiss_suggestion(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = None
        resp = api_client.post(
            "/api/v1/overrides/suggestions/dismissed",
            json={"company": "FLOWERS INC", "category": "Groceries"},
        )
        assert_ok(resp)
        assert resp.json()["detail"] == "dismissed"
        # Verify dismiss_suggestion was called with correct args
        mock_run_sync.assert_called_once()
        call_args = mock_run_sync.call_args
        assert call_args[0][1] == "FLOWERS INC"
        assert call_args[0][2] == "Groceries"

    @pytest.mark.parametrize("mock_run_sync", ["overrides"], indirect=True)
    def test_dismiss_returns_409_on_conflict(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.side_effect = VersionConflictError("conflict")
        resp = api_client.post(
            "/api/v1/overrides/suggestions/dismissed",
            json={"company": "X", "category": "Y"},
        )
        assert_problem(resp, 409)


# ---------------------------------------------------------------------------
# Endpoint DELETE /api/v1/overrides/suggestions/dismissed/{key}
# ---------------------------------------------------------------------------


class TestUndismissSuggestion:
    @pytest.mark.parametrize("mock_run_sync", ["overrides"], indirect=True)
    def test_undismiss_suggestion(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = None
        resp = api_client.delete("/api/v1/overrides/suggestions/dismissed/flowers%20inc%7Cgroceries")
        assert_ok(resp)
        assert resp.json()["detail"] == "undismissed"


# ---------------------------------------------------------------------------
# Correction-window anchor (app-timezone "today", not container UTC)
# ---------------------------------------------------------------------------


class TestCorrectionWindowAnchor:
    def test_window_anchored_on_app_timezone_date(self, freeze_clock) -> None:
        # _query_correction_items walks back N months from app_today(). Frozen at
        # 2026-12-31 16:30 Pacific (== 2027-01-01 00:30 UTC), the anchor must be
        # the Pacific month (2026-12); a container on UTC would start at 2027-01
        # and skip December's corrections entirely.
        freeze_clock(demo_clock, at=_YEAR_BOUNDARY)  # helper reads app_today() → demo_clock
        summary = MagicMock(name="summary")
        summary.query_month.return_value = []
        with patch("src.api.dependencies.get_spending_summary", return_value=summary):
            _query_correction_items(3)
        queried = [call.args[0] for call in summary.query_month.call_args_list]
        assert queried == ["2026-12", "2026-11", "2026-10"]
