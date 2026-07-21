"""Tests for the DEMO_TODAY world-clock override."""

from datetime import date

from src.finance.demo_clock import app_today, demo_today_override


class TestDemoTodayOverride:
    def test_unset_returns_none(self, monkeypatch):
        monkeypatch.delenv("DEMO_TODAY", raising=False)
        assert demo_today_override() is None

    def test_valid_value_parses(self, monkeypatch):
        monkeypatch.setenv("DEMO_TODAY", "2026-03-19")
        assert demo_today_override() == date(2026, 3, 19)

    def test_whitespace_tolerated(self, monkeypatch):
        monkeypatch.setenv("DEMO_TODAY", " 2026-03-19 ")
        assert demo_today_override() == date(2026, 3, 19)

    def test_malformed_value_ignored(self, monkeypatch, caplog):
        monkeypatch.setenv("DEMO_TODAY", "March 19")
        assert demo_today_override() is None
        assert "Ignoring malformed" in caplog.text


class TestAppToday:
    def test_override_wins(self, monkeypatch):
        monkeypatch.setenv("DEMO_TODAY", "2026-03-19")
        assert app_today() == date(2026, 3, 19)

    def test_falls_back_to_real_clock(self, monkeypatch):
        monkeypatch.delenv("DEMO_TODAY", raising=False)
        assert abs((app_today() - date.today()).days) <= 1  # noqa: DTZ011 — real-clock fallback assertion, tolerant to tz skew
