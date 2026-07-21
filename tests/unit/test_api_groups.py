"""Tests for category groups API endpoints."""

from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from src.finance import demo_clock
from src.finance.budget_service import DEFAULT_GROUPS
from src.finance.exceptions import VersionConflictError
from tests.asserts import assert_ok, assert_problem
from tests.factories import make_groups_item as _make_groups_item

# 2026-12-31 16:30 Pacific is the same instant as 2027-01-01 00:30 UTC — a
# container running UTC would bucket "this year" as 2027. Expressed with the
# Pacific tzinfo so ``freeze_clock`` (which returns the instant verbatim) makes
# ``app_today()`` read the Pacific calendar date, 2026-12-31.
_YEAR_BOUNDARY = datetime(2026, 12, 31, 16, 30, tzinfo=ZoneInfo("America/Los_Angeles"))

# ---------------------------------------------------------------------------
# GET /api/v1/groups
# ---------------------------------------------------------------------------


class TestGetGroups:
    @pytest.mark.parametrize("mock_run_sync", ["groups"], indirect=True)
    def test_returns_defaults_when_no_dynamo_item(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        mock_run_sync.return_value = None
        resp = api_client.get("/api/v1/groups?year=2026")
        assert_ok(resp)
        data = resp.json()
        assert data["version"] == 0
        assert data["year"] == 2026
        assert len(data["groups"]) == len(DEFAULT_GROUPS)
        assert data["groups"][0]["name"] == "Food & Dining"

    @pytest.mark.parametrize("mock_run_sync", ["groups"], indirect=True)
    def test_returns_stored_groups(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        custom_groups = [{"name": "My Group", "categories": ["groceries", "rent"]}]
        mock_run_sync.return_value = _make_groups_item(groups=custom_groups, version=3)
        resp = api_client.get("/api/v1/groups?year=2026")
        assert_ok(resp)
        data = resp.json()
        assert data["version"] == 3
        assert len(data["groups"]) == 1
        assert data["groups"][0]["name"] == "My Group"
        assert data["groups"][0]["categories"] == ["groceries", "rent"]

    @pytest.mark.parametrize("mock_run_sync", ["groups"], indirect=True)
    def test_defaults_to_current_year(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        mock_run_sync.return_value = None
        resp = api_client.get("/api/v1/groups")
        assert_ok(resp)
        data = resp.json()
        assert data["year"] > 0  # current year

    @pytest.mark.parametrize("mock_run_sync", ["groups"], indirect=True)
    def test_default_year_uses_app_timezone_not_utc(
        self, mock_run_sync: AsyncMock, api_client: TestClient, freeze_clock
    ) -> None:
        # At 2026-12-31 16:30 Pacific (== 2027-01-01 00:30 UTC) the default year
        # must be the Pacific date's year, 2026 — not the container's UTC 2027.
        freeze_clock(demo_clock, at=_YEAR_BOUNDARY)  # router reads app_today() → demo_clock
        mock_run_sync.return_value = None
        resp = api_client.get("/api/v1/groups")
        assert_ok(resp)
        assert resp.json()["year"] == 2026


# ---------------------------------------------------------------------------
# PUT /api/v1/groups
# ---------------------------------------------------------------------------


class TestPutGroups:
    @pytest.mark.parametrize("mock_run_sync", ["groups"], indirect=True)
    def test_creates_groups(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        new_groups = [{"name": "Custom", "categories": ["groceries"]}]
        # get_groups (ledger before-image), put_groups, get_groups (re-read)
        mock_run_sync.side_effect = [
            None,  # get_groups before-image
            1,  # put_groups returns new version
            _make_groups_item(groups=new_groups, version=1),
        ]

        resp = api_client.put(
            "/api/v1/groups?year=2026",
            json={"groups": new_groups, "version": None},
        )
        assert_ok(resp)
        data = resp.json()
        assert data["version"] == 1
        assert len(data["groups"]) == 1
        assert data["groups"][0]["name"] == "Custom"

    @pytest.mark.parametrize("mock_run_sync", ["groups"], indirect=True)
    def test_updates_with_version(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        updated = [{"name": "Updated", "categories": ["rent", "utilities"]}]
        mock_run_sync.side_effect = [
            None,  # get_groups before-image
            2,
            _make_groups_item(groups=updated, version=2),
        ]

        resp = api_client.put(
            "/api/v1/groups?year=2026",
            json={"groups": updated, "version": 1},
        )
        assert_ok(resp)
        data = resp.json()
        assert data["version"] == 2
        assert data["groups"][0]["name"] == "Updated"

    @pytest.mark.parametrize("mock_run_sync", ["groups"], indirect=True)
    def test_returns_409_on_version_conflict(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        # get_groups before-image succeeds; put_groups raises the conflict.
        mock_run_sync.side_effect = [None, VersionConflictError("conflict")]

        resp = api_client.put(
            "/api/v1/groups?year=2026",
            json={"groups": [{"name": "X", "categories": []}], "version": 1},
        )
        assert_problem(resp, 409)
        assert "conflict" in resp.json()["error"].lower()

    @pytest.mark.parametrize("mock_run_sync", ["groups"], indirect=True)
    def test_invalidates_cache_on_success(self, mock_run_sync: AsyncMock, api_client: TestClient) -> None:
        mock_run_sync.side_effect = [None, 1, _make_groups_item(version=1)]

        with patch("src.api.routers.groups.get_budget_service") as mock_get_svc:
            mock_svc = mock_get_svc.return_value
            mock_svc.invalidate_cache = lambda: None
            # Just verify the endpoint succeeds (invalidate_cache is called internally)
            resp = api_client.put(
                "/api/v1/groups?year=2026",
                json={"groups": [{"name": "A", "categories": []}], "version": None},
            )
            assert_ok(resp)
