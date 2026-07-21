"""Tests for `src/finance/app_timezone.py` — config-driven timezone helpers."""

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import src.finance.app_config as app_config
from src.finance.app_timezone import (
    _DEFAULT_TZ_NAME,
    get_app_timezone,
    get_tzinfos,
)


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Redirect _CONFIG_PATH to a tmp file + clear the in-memory cache."""
    tmp_config = tmp_path / "config.json"
    monkeypatch.setattr(app_config, "_CONFIG_PATH", Path(tmp_config))
    app_config.invalidate_config_cache()
    yield tmp_config
    app_config.invalidate_config_cache()


def _write_config(path: Path, data: dict[str, object]) -> None:
    path.write_text(json.dumps(data))
    app_config.invalidate_config_cache()


class TestGetAppTimezone:
    def test_defaults_to_pacific_when_config_absent(self, isolated_config: Path) -> None:
        _write_config(isolated_config, {"storage": "sqlite"})
        assert get_app_timezone() == ZoneInfo(_DEFAULT_TZ_NAME)

    def test_respects_berlin(self, isolated_config: Path) -> None:
        _write_config(isolated_config, {"timezone": "Europe/Berlin"})
        assert get_app_timezone() == ZoneInfo("Europe/Berlin")

    def test_respects_tokyo(self, isolated_config: Path) -> None:
        _write_config(isolated_config, {"timezone": "Asia/Tokyo"})
        assert get_app_timezone() == ZoneInfo("Asia/Tokyo")

    def test_invalid_zone_falls_back_to_pacific(self, isolated_config: Path, caplog: pytest.LogCaptureFixture) -> None:
        _write_config(isolated_config, {"timezone": "Not/A/Real/Zone"})
        with caplog.at_level(logging.WARNING, logger="src.finance.app_timezone"):
            result = get_app_timezone()
        assert result == ZoneInfo(_DEFAULT_TZ_NAME)
        assert any("Not/A/Real/Zone" in rec.message for rec in caplog.records)

    def test_empty_string_falls_back_to_pacific(self, isolated_config: Path) -> None:
        _write_config(isolated_config, {"timezone": ""})
        assert get_app_timezone() == ZoneInfo(_DEFAULT_TZ_NAME)


class TestGetTzinfos:
    def test_pst_pdt_map_to_pacific_under_default(self, isolated_config: Path) -> None:
        _write_config(isolated_config, {})
        tzinfos = get_tzinfos()
        assert tzinfos["PST"] is not None
        assert tzinfos["PDT"] is not None
        # gettz("America/Los_Angeles") returns a dateutil tz, not a ZoneInfo —
        # verify the zone it represents resolves correctly.
        from datetime import datetime

        winter = datetime(2026, 1, 15, 12, 0, tzinfo=tzinfos["PST"])
        summer = datetime(2026, 7, 15, 12, 0, tzinfo=tzinfos["PDT"])
        winter_offset = winter.utcoffset()
        summer_offset = summer.utcoffset()
        assert winter_offset is not None
        assert summer_offset is not None
        # Pacific: PST=UTC-8 → 12:00 PST == 20:00 UTC; PDT=UTC-7 → 12:00 PDT == 19:00 UTC.
        assert winter_offset.total_seconds() == -8 * 3600
        assert summer_offset.total_seconds() == -7 * 3600

    def test_pst_pdt_still_map_to_pacific_under_berlin(self, isolated_config: Path) -> None:
        """Legacy-data invariant: old rows contain literal ' PST'/' PDT'
        suffixes that must resolve to Pacific regardless of user's config."""
        _write_config(isolated_config, {"timezone": "Europe/Berlin"})
        tzinfos = get_tzinfos()
        from datetime import datetime

        winter = datetime(2026, 1, 15, 12, 0, tzinfo=tzinfos["PST"])
        winter_offset = winter.utcoffset()
        assert winter_offset is not None
        assert winter_offset.total_seconds() == -8 * 3600  # not +0100 (Berlin)

    def test_returns_independent_copies(self, isolated_config: Path) -> None:
        a = get_tzinfos()
        b = get_tzinfos()
        a["FAKE"] = None
        assert "FAKE" not in b

    def test_berlin_adds_cet_and_cest(self, isolated_config: Path) -> None:
        """Non-Pacific config adds the configured zone's abbreviations so
        re-parse of a stored `" CEST"` or `" CET"` string resolves cleanly."""
        _write_config(isolated_config, {"timezone": "Europe/Berlin"})
        tzinfos = get_tzinfos()
        assert "CET" in tzinfos
        assert "CEST" in tzinfos
        # PST/PDT still resolve to Pacific even under Berlin config.
        assert "PST" in tzinfos
        assert "PDT" in tzinfos

    def test_tokyo_adds_jst(self, isolated_config: Path) -> None:
        _write_config(isolated_config, {"timezone": "Asia/Tokyo"})
        tzinfos = get_tzinfos()
        assert "JST" in tzinfos
