"""Tests for the ingestion-coverage API endpoint.

Covers ``GET /api/v1/coverage``: the happy path (200 + full response shape),
exercising both the ``capture: null`` case (DynamoDB / no statements) and a
populated capture summary. The service is mocked via the shared ``mock_run_sync``
fixture — this suite validates the router + model round-trip, not the cadence
math (that lives in ``test_coverage_service.py``).
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from tests.asserts import assert_ok


def _make_capture_payload() -> dict[str, Any]:
    """A populated CaptureSummary-shaped dict."""
    return {
        "overall": {"caught": 47, "total": 49, "rate": 47 / 49},
        "by_institution": [
            {"institution": "CIBC", "caught": 47, "total": 49, "rate": 47 / 49},
        ],
        "by_type": [
            {"type": "deposit", "caught": 7, "total": 8, "rate": 7 / 8},
            {"type": "withdrawal", "caught": 40, "total": 41, "rate": 40 / 41},
        ],
    }


def _make_coverage_payload(capture: dict[str, Any] | None = None) -> dict[str, Any]:
    """A minimal-but-complete CoverageResponse-shaped dict."""
    return {
        "institutions": [
            {
                "institution": "RBC",
                "status": "quiet",
                "last_seen_at": "2026-07-01T00:00:00",
                "days_since_last_seen": 16,
                "median_gap_days": 3.0,
                "threshold_gap_days": 7,
                "dormant_cutoff_days": 45,
                "event_days": 40,
            },
            {
                "institution": "Simplii",
                "status": "irregular",
                "last_seen_at": "2026-06-01T00:00:00",
                "days_since_last_seen": 46,
                "median_gap_days": None,
                "threshold_gap_days": None,
                "dormant_cutoff_days": None,
                "event_days": 3,
            },
        ],
        "capture": capture,
        "window_months": 12,
        "checked_at": "2026-07-17T10:00:00-07:00",
    }


class TestCoverage:
    @pytest.mark.parametrize("mock_run_sync", ["coverage"], indirect=True)
    def test_returns_200_and_shape_capture_null(self, mock_run_sync: AsyncMock, api_client) -> None:
        """No statements imported → capture is null; cadence rows round-trip fully."""
        mock_run_sync.return_value = _make_coverage_payload(capture=None)

        resp = api_client.get("/api/v1/coverage")
        assert_ok(resp)

        data = resp.json()
        assert data["window_months"] == 12
        assert data["checked_at"] == "2026-07-17T10:00:00-07:00"
        assert data["capture"] is None
        assert len(data["institutions"]) == 2

        quiet = data["institutions"][0]
        assert quiet["institution"] == "RBC"
        assert quiet["status"] == "quiet"
        assert quiet["days_since_last_seen"] == 16
        assert quiet["median_gap_days"] == 3.0
        assert quiet["threshold_gap_days"] == 7
        assert quiet["dormant_cutoff_days"] == 45
        assert quiet["event_days"] == 40

        irregular = data["institutions"][1]
        assert irregular["status"] == "irregular"
        assert irregular["median_gap_days"] is None
        assert irregular["threshold_gap_days"] is None
        assert irregular["dormant_cutoff_days"] is None

    @pytest.mark.parametrize("mock_run_sync", ["coverage"], indirect=True)
    def test_returns_200_with_populated_capture(self, mock_run_sync: AsyncMock, api_client) -> None:
        """A populated capture summary round-trips, including the ``type`` field."""
        mock_run_sync.return_value = _make_coverage_payload(capture=_make_capture_payload())

        resp = api_client.get("/api/v1/coverage")
        assert_ok(resp)

        capture = resp.json()["capture"]
        assert capture is not None
        assert capture["overall"]["caught"] == 47
        assert capture["overall"]["total"] == 49
        assert capture["overall"]["rate"] == pytest.approx(47 / 49)
        assert capture["by_institution"][0]["institution"] == "CIBC"
        # The ``type`` field survives round-trip (Python builtin name, not a keyword).
        assert [b["type"] for b in capture["by_type"]] == ["deposit", "withdrawal"]
        assert capture["by_type"][1]["caught"] == 40
