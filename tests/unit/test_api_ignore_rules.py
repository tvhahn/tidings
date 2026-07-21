"""Tests for merchant auto-ignore rule API endpoints."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.dependencies import get_ignore_rule_service, get_transactions_db
from src.finance import app_config
from src.finance.exceptions import VersionConflictError
from tests.asserts import assert_ok, assert_problem


@pytest.fixture(autouse=True)
def _non_demo_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin demo_mode off — write endpoints gate on ensure_not_demo, and a fresh
    checkout's first-run config defaults to demo_mode:true (app_config seeds
    data/config.json that way), which would 403 every write test here."""
    cfg = dict(app_config.get_config())
    cfg["demo_mode"] = False
    monkeypatch.setattr(app_config, "get_config", lambda: cfg)


def _rules_item(patterns: list[str], version: int = 1) -> dict[str, Any]:
    return {
        "PK": "USER#default",
        "SK": "CONFIG#ignore_rules",
        "Data": dict.fromkeys(patterns, ""),
        "Version": version,
    }


# ---------------------------------------------------------------------------
# GET /api/v1/ignore-rules
# ---------------------------------------------------------------------------


class TestListIgnoreRules:
    @pytest.mark.parametrize("mock_run_sync", ["ignore_rules"], indirect=True)
    def test_returns_rules_sorted(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = _rules_item(["MAPLETRADE INC.", "MiscPayment CARDCO"], version=3)
        resp = api_client.get("/api/v1/ignore-rules")
        assert_ok(resp)
        body = resp.json()
        assert body["count"] == 2
        assert body["version"] == 3
        assert [r["pattern"] for r in body["rules"]] == ["MAPLETRADE INC.", "MiscPayment CARDCO"]

    @pytest.mark.parametrize("mock_run_sync", ["ignore_rules"], indirect=True)
    def test_returns_empty_when_not_seeded(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = None
        resp = api_client.get("/api/v1/ignore-rules")
        assert_ok(resp)
        body = resp.json()
        assert body == {"rules": [], "count": 0, "version": 0}


# ---------------------------------------------------------------------------
# POST /api/v1/ignore-rules
# ---------------------------------------------------------------------------


class TestAddIgnoreRule:
    @patch("src.api.routers.ignore_rules.invalidate_ignore_rules_cache")
    @pytest.mark.parametrize("mock_run_sync", ["ignore_rules"], indirect=True)
    def test_adds_rule(self, mock_invalidate: MagicMock, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.side_effect = [None, _rules_item(["MAPLETRADE INC."], version=1)]
        resp = api_client.post("/api/v1/ignore-rules", json={"pattern": "MAPLETRADE INC."})
        assert_ok(resp)
        assert resp.json()["count"] == 1
        mock_invalidate.assert_called_once()

    @pytest.mark.parametrize("mock_run_sync", ["ignore_rules"], indirect=True)
    def test_empty_pattern_is_422(self, mock_run_sync: AsyncMock, api_client) -> None:
        resp = api_client.post("/api/v1/ignore-rules", json={"pattern": "   "})
        assert_problem(resp, 422)


# ---------------------------------------------------------------------------
# DELETE a rule by pattern
# ---------------------------------------------------------------------------


class TestDeleteIgnoreRule:
    @patch("src.api.routers.ignore_rules.invalidate_ignore_rules_cache")
    @pytest.mark.parametrize("mock_run_sync", ["ignore_rules"], indirect=True)
    def test_deletes_rule(self, mock_invalidate: MagicMock, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = 2
        resp = api_client.delete("/api/v1/ignore-rules/MAPLETRADE%20INC.")
        assert_ok(resp)
        assert resp.json()["detail"] == "deleted"
        mock_invalidate.assert_called_once()

    @pytest.mark.parametrize("mock_run_sync", ["ignore_rules"], indirect=True)
    def test_delete_missing_is_404(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.side_effect = KeyError("nope")
        resp = api_client.delete("/api/v1/ignore-rules/NOPE")
        assert_problem(resp, 404)


# ---------------------------------------------------------------------------
# POST /api/v1/ignore-rules/apply  (run_sync NOT mocked — exercises the helper)
# ---------------------------------------------------------------------------


class TestApplyIgnoreRules:
    @patch("src.api.routers.ignore_rules.get_ignore_context", return_value=(["MAPLETRADE INC."], {}))
    def test_backfills_matching_rows(self, _mock_ctx: MagicMock, api_client) -> None:
        svc = MagicMock()
        svc.get_patterns.return_value = ["MAPLETRADE INC."]

        db = MagicMock()
        db.scan_all_transactions.return_value = [
            {"ForwardedTo": "u", "DateFileName": "a", "Company": "MAPLETRADE INC.", "Ignored": False},
            {"ForwardedTo": "u", "DateFileName": "b", "Company": "MAPLETRADE INC.", "Ignored": True},
            {"ForwardedTo": "u", "DateFileName": "c", "Company": "STARBUCKS", "Ignored": False},
            {"ForwardedTo": "u", "DateFileName": "d", "Company": "MAPLETRADE INC.", "DeletedAt": "x"},
        ]

        api_client.app.dependency_overrides[get_ignore_rule_service] = lambda: svc
        api_client.app.dependency_overrides[get_transactions_db] = lambda: db

        resp = api_client.post("/api/v1/ignore-rules/apply", json={})
        assert_ok(resp)
        body = resp.json()
        # 2 non-deleted matches (a, b); only a was flipped false→true.
        assert body["total_matched"] == 2
        assert body["total_updated"] == 1
        assert body["results"][0] == {"pattern": "MAPLETRADE INC.", "matched": 2, "updated": 1}
        db.set_ignored.assert_called_once_with("u", "a", True)

    @patch("src.api.routers.ignore_rules.get_ignore_context", return_value=(["MAPLETRADE INC."], {}))
    def test_unknown_pattern_is_404(self, _mock_ctx: MagicMock, api_client) -> None:
        svc = MagicMock()
        svc.get_patterns.return_value = ["MAPLETRADE INC."]
        api_client.app.dependency_overrides[get_ignore_rule_service] = lambda: svc
        api_client.app.dependency_overrides[get_transactions_db] = lambda: MagicMock()

        resp = api_client.post("/api/v1/ignore-rules/apply", json={"pattern": "UNKNOWN"})
        assert_problem(resp, 404)


# ---------------------------------------------------------------------------
# GET /api/v1/ignore-rules/suggestions
# ---------------------------------------------------------------------------


class TestIgnoreSuggestions:
    @patch("src.api.routers.ignore_rules.get_ignore_context", return_value=([], {}))
    @patch("src.api.routers.ignore_rules._query_recent_transactions")
    def test_suggests_habitually_ignored_merchant(
        self, mock_query: MagicMock, _mock_ctx: MagicMock, api_client
    ) -> None:
        # CARDCO: 4 total, 3 ignored (75%) → suggested. Costco: 3 total, 1 ignored → not.
        mock_query.return_value = [
            {"Company": "MiscPayment CARDCO", "Ignored": True},
            {"Company": "MiscPayment CARDCO", "Ignored": True},
            {"Company": "MiscPayment CARDCO", "Ignored": True},
            {"Company": "MiscPayment CARDCO", "Ignored": False},
            {"Company": "Costco", "Ignored": True},
            {"Company": "Costco", "Ignored": False},
            {"Company": "Costco", "Ignored": False},
        ]
        svc = MagicMock()
        svc.get_patterns.return_value = []
        api_client.app.dependency_overrides[get_ignore_rule_service] = lambda: svc

        resp = api_client.get("/api/v1/ignore-rules/suggestions")
        assert_ok(resp)
        body = resp.json()
        assert body["count"] == 1
        sug = body["suggestions"][0]
        assert sug["merchant"] == "MiscPayment CARDCO"
        assert sug["total_count"] == 4
        assert sug["ignored_count"] == 3
        assert sug["share"] == 0.75

    @patch("src.api.routers.ignore_rules.get_ignore_context", return_value=(["MiscPayment CARDCO"], {}))
    @patch("src.api.routers.ignore_rules._query_recent_transactions")
    def test_excludes_merchant_with_existing_rule(
        self, mock_query: MagicMock, _mock_ctx: MagicMock, api_client
    ) -> None:
        mock_query.return_value = [
            {"Company": "MiscPayment CARDCO", "Ignored": True},
            {"Company": "MiscPayment CARDCO", "Ignored": True},
            {"Company": "MiscPayment CARDCO", "Ignored": True},
        ]
        svc = MagicMock()
        svc.get_patterns.return_value = ["MiscPayment CARDCO"]
        api_client.app.dependency_overrides[get_ignore_rule_service] = lambda: svc

        resp = api_client.get("/api/v1/ignore-rules/suggestions")
        assert_ok(resp)
        assert resp.json()["count"] == 0

    @patch("src.api.routers.ignore_rules.get_ignore_context", return_value=([], {}))
    @patch("src.api.routers.ignore_rules._query_recent_transactions")
    def test_excludes_dismissed_merchant(self, mock_query: MagicMock, _mock_ctx: MagicMock, api_client) -> None:
        # CARDCO would otherwise qualify (3/3 ignored) but has been dismissed.
        mock_query.return_value = [
            {"Company": "MiscPayment CARDCO", "Ignored": True},
            {"Company": "MiscPayment CARDCO", "Ignored": True},
            {"Company": "MiscPayment CARDCO", "Ignored": True},
        ]
        svc = MagicMock()
        svc.get_patterns.return_value = []
        # Dismissed map is keyed by the lowercased merchant; filter is case-insensitive.
        svc.get_dismissed.return_value = {"miscpayment cardco": "2026-07-16T00:00:00+00:00"}
        api_client.app.dependency_overrides[get_ignore_rule_service] = lambda: svc

        resp = api_client.get("/api/v1/ignore-rules/suggestions")
        assert_ok(resp)
        assert resp.json()["count"] == 0


# ---------------------------------------------------------------------------
# GET /api/v1/ignore-rules/suggestions/dismissed
# ---------------------------------------------------------------------------


class TestListDismissedIgnoreSuggestions:
    @pytest.mark.parametrize("mock_run_sync", ["ignore_rules"], indirect=True)
    def test_lists_dismissed_newest_first(self, mock_run_sync: AsyncMock, api_client) -> None:
        # The service normalizes + sorts; the handler just wraps the rows.
        mock_run_sync.return_value = [
            {"merchant": "MiscPayment CARDCO", "dismissed_at": "2026-07-16T00:00:00+00:00"},
            {"merchant": "Costco", "dismissed_at": "2026-07-10T00:00:00+00:00"},
        ]
        resp = api_client.get("/api/v1/ignore-rules/suggestions/dismissed")
        assert_ok(resp)
        body = resp.json()
        assert body["count"] == 2
        assert [d["merchant"] for d in body["dismissed"]] == ["MiscPayment CARDCO", "Costco"]
        assert body["dismissed"][0]["dismissed_at"] == "2026-07-16T00:00:00+00:00"

    @pytest.mark.parametrize("mock_run_sync", ["ignore_rules"], indirect=True)
    def test_empty_when_no_dismissals(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = []
        resp = api_client.get("/api/v1/ignore-rules/suggestions/dismissed")
        assert_ok(resp)
        assert resp.json() == {"dismissed": [], "count": 0}


# ---------------------------------------------------------------------------
# POST /api/v1/ignore-rules/suggestions/dismissed
# ---------------------------------------------------------------------------


class TestDismissIgnoreSuggestion:
    @pytest.mark.parametrize("mock_run_sync", ["ignore_rules"], indirect=True)
    def test_dismiss_suggestion(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = None
        resp = api_client.post(
            "/api/v1/ignore-rules/suggestions/dismissed",
            json={"merchant": "MiscPayment CARDCO"},
        )
        assert_ok(resp)
        assert resp.json()["detail"] == "dismissed"
        # dismiss_suggestion dispatched through run_sync with the merchant.
        mock_run_sync.assert_called_once()
        assert mock_run_sync.call_args[0][1] == "MiscPayment CARDCO"

    @pytest.mark.parametrize("mock_run_sync", ["ignore_rules"], indirect=True)
    def test_empty_merchant_is_422(self, mock_run_sync: AsyncMock, api_client) -> None:
        resp = api_client.post("/api/v1/ignore-rules/suggestions/dismissed", json={"merchant": "  "})
        assert_problem(resp, 422)

    @pytest.mark.parametrize("mock_run_sync", ["ignore_rules"], indirect=True)
    def test_dismiss_returns_409_on_conflict(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.side_effect = VersionConflictError("conflict")
        resp = api_client.post(
            "/api/v1/ignore-rules/suggestions/dismissed",
            json={"merchant": "Costco"},
        )
        assert_problem(resp, 409)

    @patch("src.finance.app_config.get_config", return_value={"demo_mode": True})
    def test_dismiss_blocked_in_demo(self, _mock_config: MagicMock, api_client) -> None:
        resp = api_client.post(
            "/api/v1/ignore-rules/suggestions/dismissed",
            json={"merchant": "Costco"},
        )
        assert_problem(resp, 403)


# ---------------------------------------------------------------------------
# Endpoint DELETE /api/v1/ignore-rules/suggestions/dismissed/{merchant}
# ---------------------------------------------------------------------------


class TestUndismissIgnoreSuggestion:
    @pytest.mark.parametrize("mock_run_sync", ["ignore_rules"], indirect=True)
    def test_undismiss_suggestion(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = None
        resp = api_client.delete("/api/v1/ignore-rules/suggestions/dismissed/MiscPayment%20CARDCO")
        assert_ok(resp)
        assert resp.json()["detail"] == "undismissed"
        mock_run_sync.assert_called_once()
        assert mock_run_sync.call_args[0][1] == "MiscPayment CARDCO"

    @patch("src.finance.app_config.get_config", return_value={"demo_mode": True})
    def test_undismiss_blocked_in_demo(self, _mock_config: MagicMock, api_client) -> None:
        resp = api_client.delete("/api/v1/ignore-rules/suggestions/dismissed/Costco")
        assert_problem(resp, 403)
