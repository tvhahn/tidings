"""Tests for `src/finance/category_audit.py` — build + normalize the v2 audit dict."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

import src.finance.app_config as app_config
from src.finance.category_audit import (
    SCHEMA_VERSION,
    build_audit,
    normalize_audit,
    now_local_iso,
)

ISO_WITH_OFFSET_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?[+-]\d{2}:\d{2}$")


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    tmp_config = tmp_path / "config.json"
    monkeypatch.setattr(app_config, "_CONFIG_PATH", Path(tmp_config))
    app_config.invalidate_config_cache()
    yield tmp_config
    app_config.invalidate_config_cache()


def _write_config(path: Path, data: dict[str, object]) -> None:
    path.write_text(json.dumps(data))
    app_config.invalidate_config_cache()


class TestNowLocalIso:
    def test_uses_pacific_by_default(self, isolated_config: Path) -> None:
        _write_config(isolated_config, {"storage": "sqlite"})
        stamp = now_local_iso()
        assert ISO_WITH_OFFSET_RE.match(stamp), stamp
        # Pacific is -08:00 in winter, -07:00 in summer. Either is fine.
        assert stamp.endswith(("-07:00", "-08:00"))

    def test_respects_berlin(self, isolated_config: Path) -> None:
        _write_config(isolated_config, {"timezone": "Europe/Berlin"})
        stamp = now_local_iso()
        # Berlin: +01:00 winter, +02:00 summer.
        assert stamp.endswith(("+01:00", "+02:00")), stamp

    def test_respects_tokyo(self, isolated_config: Path) -> None:
        _write_config(isolated_config, {"timezone": "Asia/Tokyo"})
        stamp = now_local_iso()
        assert stamp.endswith("+09:00"), stamp


class TestBuildAudit:
    def test_minimal_shape(self, isolated_config: Path) -> None:
        _write_config(isolated_config, {"storage": "sqlite"})
        audit = build_audit("manual")
        assert audit["source"] == "manual"
        assert audit["schema_version"] == SCHEMA_VERSION
        assert ISO_WITH_OFFSET_RE.match(audit["reviewed_at"])
        # No optional fields when not supplied.
        for key in (
            "tier",
            "matched_rule",
            "confidence",
            "model",
            "fallback_reason",
            "previous_category",
            "previous_source",
        ):
            assert key not in audit

    def test_override_with_tier(self, isolated_config: Path) -> None:
        _write_config(isolated_config, {"storage": "sqlite"})
        audit = build_audit(
            "override",
            tier="normalized",
            matched_rule="GROCERY MART #123",
            confidence=Decimal(1),
        )
        assert audit["source"] == "override"
        assert audit["tier"] == "normalized"
        assert audit["matched_rule"] == "GROCERY MART #123"
        assert audit["confidence"] == Decimal(1)

    def test_ai_success_records_model(self, isolated_config: Path) -> None:
        _write_config(isolated_config, {"storage": "sqlite"})
        audit = build_audit("ai", model="gpt-5.4-nano")
        assert audit == {
            "source": "ai",
            "model": "gpt-5.4-nano",
            "reviewed_at": audit["reviewed_at"],
            "schema_version": SCHEMA_VERSION,
        }

    def test_ai_fallback_records_reason(self, isolated_config: Path) -> None:
        _write_config(isolated_config, {"storage": "sqlite"})
        audit = build_audit("ai_fallback", fallback_reason="api_error", model="gpt-5.4-nano")
        assert audit["source"] == "ai_fallback"
        assert audit["fallback_reason"] == "api_error"
        assert audit["model"] == "gpt-5.4-nano"

    def test_previous_fields(self, isolated_config: Path) -> None:
        _write_config(isolated_config, {"storage": "sqlite"})
        audit = build_audit(
            "manual",
            previous_category="miscellaneous",
            previous_source="ai_fallback",
        )
        assert audit["previous_category"] == "miscellaneous"
        assert audit["previous_source"] == "ai_fallback"

    def test_explicit_reviewed_at_wins(self, isolated_config: Path) -> None:
        _write_config(isolated_config, {"storage": "sqlite"})
        audit = build_audit("manual", reviewed_at="2026-01-01T00:00:00-08:00")
        assert audit["reviewed_at"] == "2026-01-01T00:00:00-08:00"


class TestNormalizeAudit:
    def test_none_passthrough(self) -> None:
        assert normalize_audit(None) is None

    def test_empty_passthrough(self) -> None:
        assert normalize_audit({}) == {}

    def test_legacy_override_normalized(self) -> None:
        raw = {"source": "override_normalized", "reviewed_at": "2026-02-15T21:38:22+00:00"}
        out = normalize_audit(raw)
        assert out is not None
        assert out["source"] == "override"
        assert out["tier"] == "normalized"
        assert out["reviewed_at"] == "2026-02-15T21:38:22+00:00"

    def test_legacy_override_alias(self) -> None:
        out = normalize_audit({"source": "override_alias"})
        assert out is not None
        assert out["source"] == "override"
        assert out["tier"] == "alias"

    def test_legacy_override_fuzzy(self) -> None:
        out = normalize_audit({"source": "override_fuzzy"})
        assert out is not None
        assert out["source"] == "override"
        assert out["tier"] == "fuzzy"

    def test_bare_legacy_override_gets_exact(self) -> None:
        out = normalize_audit({"source": "override"})
        assert out is not None
        assert out["source"] == "override"
        assert out["tier"] == "exact"

    def test_canonical_v2_passthrough(self) -> None:
        raw = {
            "source": "override",
            "tier": "alias",
            "matched_rule": "AMZN Mktp CA",
            "confidence": 1.0,
            "reviewed_at": "2026-04-18T11:37:42-07:00",
            "schema_version": 2,
        }
        out = normalize_audit(raw)
        assert out == raw

    def test_unknown_source_passes_through(self) -> None:
        out = normalize_audit({"source": "manual"})
        assert out == {"source": "manual"}

    def test_drops_invalid_tier(self) -> None:
        out = normalize_audit({"source": "override", "tier": "bogus"})
        assert out is not None
        # Invalid tier dropped; legacy fallback adds tier="exact" since the
        # remaining state is "bare override without tier".
        assert out["tier"] == "exact"

    def test_returns_a_copy(self) -> None:
        raw = {"source": "override"}
        out = normalize_audit(raw)
        assert out is not raw
        # Mutating the result must not touch the input.
        assert "tier" not in raw
