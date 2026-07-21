"""Tests for the quiet-transition notifier (src/finance/coverage_notifier.py).

Covers the just-crossed transition window, the per-status gating, the in-process
24h suppression + ``reset_suppression``, fail-open on a raising ``send_raw``, and
the returned notified-institutions list. Uses a plain fake coverage service and
captures ``send_raw`` calls; no network, no real provider.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.finance import coverage_notifier


class _FakeCoverage:
    """Minimal stand-in exposing ``get_coverage`` with caller-supplied rows."""

    def __init__(self, institutions: list[dict[str, Any]]) -> None:
        self._institutions = institutions

    def get_coverage(self) -> dict[str, Any]:
        return {
            "institutions": self._institutions,
            "capture": None,
            "window_months": 12,
            "checked_at": "2026-07-17T10:00:00-07:00",
        }


def _row(institution: str, status: str, days: int | None, threshold: int | None) -> dict[str, Any]:
    return {
        "institution": institution,
        "status": status,
        "last_seen_at": "2026-07-08T00:00:00",
        "days_since_last_seen": days,
        "median_gap_days": 3.0 if threshold is not None else None,
        "threshold_gap_days": threshold,
        "dormant_cutoff_days": (3 * threshold) if threshold is not None else None,
        "event_days": 40,
    }


@pytest.fixture(autouse=True)
def _reset_suppression() -> None:
    """Isolate the module-level suppression dict between tests."""
    coverage_notifier.reset_suppression()


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    """Capture ``send_raw`` calls into a list."""
    calls: list[dict[str, str]] = []

    def _fake_send_raw(title: str, body: str, tags: list[str] | None = None) -> None:
        calls.append({"title": title, "body": body})

    monkeypatch.setattr(coverage_notifier.notification_service, "send_raw", _fake_send_raw)
    return calls


class TestJustCrossedQuiet:
    def test_quiet_in_window_notifies_with_locked_body(self, sent: list[dict[str, str]]) -> None:
        # 7 < 9 <= 9 → just crossed.
        service = _FakeCoverage([_row("RBC", "quiet", days=9, threshold=7)])
        notified = coverage_notifier.check_quiet_notifications(service)

        assert notified == ["RBC"]
        assert len(sent) == 1
        assert sent[0]["title"] == "Tidings"
        assert sent[0]["body"] == "RBC has been quiet for 9 days — you usually see a gap of no more than 7"

    def test_quiet_beyond_window_does_not_notify(self, sent: list[dict[str, str]]) -> None:
        # 20 > 7 + 2 → standing quiet, not a fresh transition.
        service = _FakeCoverage([_row("RBC", "quiet", days=20, threshold=7)])
        assert coverage_notifier.check_quiet_notifications(service) == []
        assert sent == []

    @pytest.mark.parametrize("status", ["active", "dormant", "irregular"])
    def test_non_quiet_statuses_never_notify(self, sent: list[dict[str, str]], status: str) -> None:
        threshold = None if status == "irregular" else 7
        service = _FakeCoverage([_row("RBC", status, days=9, threshold=threshold)])
        assert coverage_notifier.check_quiet_notifications(service) == []
        assert sent == []


class TestSuppression:
    def test_24h_suppression_suppresses_second_call(self, sent: list[dict[str, str]]) -> None:
        service = _FakeCoverage([_row("RBC", "quiet", days=9, threshold=7)])

        assert coverage_notifier.check_quiet_notifications(service) == ["RBC"]
        # Second immediate run: within the 24h window → suppressed.
        assert coverage_notifier.check_quiet_notifications(service) == []
        assert len(sent) == 1

    def test_reset_suppression_reenables_notification(self, sent: list[dict[str, str]]) -> None:
        service = _FakeCoverage([_row("RBC", "quiet", days=9, threshold=7)])

        assert coverage_notifier.check_quiet_notifications(service) == ["RBC"]
        coverage_notifier.reset_suppression()
        assert coverage_notifier.check_quiet_notifications(service) == ["RBC"]
        assert len(sent) == 2


class TestFailOpen:
    def test_send_raw_raising_is_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(title: str, body: str, tags: list[str] | None = None) -> None:
            raise RuntimeError("provider exploded")

        monkeypatch.setattr(coverage_notifier.notification_service, "send_raw", _boom)
        service = _FakeCoverage([_row("RBC", "quiet", days=9, threshold=7)])

        # No exception propagates; the institution isn't counted as notified.
        assert coverage_notifier.check_quiet_notifications(service) == []

    def test_get_coverage_raising_is_swallowed(self) -> None:
        class _Boom:
            def get_coverage(self) -> dict[str, Any]:
                raise RuntimeError("coverage read exploded")

        assert coverage_notifier.check_quiet_notifications(_Boom()) == []

    def test_multiple_institutions_returns_all_notified(self, sent: list[dict[str, str]]) -> None:
        service = _FakeCoverage(
            [
                _row("RBC", "quiet", days=9, threshold=7),
                _row("CIBC", "quiet", days=16, threshold=14),
                _row("Simplii", "active", days=2, threshold=7),
            ]
        )
        assert coverage_notifier.check_quiet_notifications(service) == ["RBC", "CIBC"]
        assert len(sent) == 2
