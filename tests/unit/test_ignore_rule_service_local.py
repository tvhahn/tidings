"""Parity tests for IgnoreRuleServiceLocal — SQLite implementation of ignore-rule CRUD.

Mirrors test_ignore_rule_service.py (DynamoDB) against a tmp SQLite backend to
guard against drift between the two implementations of the dual-backend service.
"""

from pathlib import Path

import pytest

from src.finance.exceptions import VersionConflictError
from src.finance.ignore_rule_service_local import IgnoreRuleServiceLocal


@pytest.fixture
def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> IgnoreRuleServiceLocal:
    """Fresh IgnoreRuleServiceLocal with tmp DB and stubbed backup writer."""
    monkeypatch.setattr(IgnoreRuleServiceLocal, "_write_backup", lambda self, *a, **kw: None)
    return IgnoreRuleServiceLocal(db_path=tmp_path / "test.db", user_id="test")


class TestGetRules:
    def test_returns_none_when_not_seeded(self, service: IgnoreRuleServiceLocal) -> None:
        assert service.get_rules() is None

    def test_returns_data_version_and_updated_at_after_add(self, service: IgnoreRuleServiceLocal) -> None:
        service.add_rule("MAPLETRADE INC.")

        item = service.get_rules()
        assert item is not None
        assert item["Data"] == {"MAPLETRADE INC.": ""}
        assert item["Version"] == 1
        assert item["UpdatedAt"]


class TestAddRule:
    def test_version_increments_on_repeat_add(self, service: IgnoreRuleServiceLocal) -> None:
        v1 = service.add_rule("MAPLETRADE INC.")
        v2 = service.add_rule("MiscPayment CARDCO")
        assert v1 == 1
        assert v2 == 2

    def test_patterns_accumulate(self, service: IgnoreRuleServiceLocal) -> None:
        service.add_rule("MAPLETRADE INC.")
        service.add_rule("MiscPayment CARDCO")
        assert service.get_patterns() == ["MAPLETRADE INC.", "MiscPayment CARDCO"]

    def test_case_insensitive_dedupe_keeps_original_casing(self, service: IgnoreRuleServiceLocal) -> None:
        service.add_rule("MAPLETRADE INC.")
        service.add_rule("mapletrade inc.")
        assert service.get_patterns() == ["MAPLETRADE INC."]

    def test_empty_pattern_raises(self, service: IgnoreRuleServiceLocal) -> None:
        with pytest.raises(ValueError, match="pattern cannot be empty"):
            service.add_rule("   ")


class TestMatches:
    def test_exact_case_insensitive_match(self, service: IgnoreRuleServiceLocal) -> None:
        service.add_rule("MAPLETRADE INC.")
        assert service.matches("mapletrade inc.") is not None
        assert service.matches("MAPLETRADE INC.").tier == "exact"

    def test_normalized_match_strips_trailing_digits(self, service: IgnoreRuleServiceLocal) -> None:
        service.add_rule("MiscPayment CARDCO #221")
        match = service.matches("MiscPayment CARDCO #999")
        assert match is not None
        assert match.tier == "normalized"

    def test_returns_none_when_absent(self, service: IgnoreRuleServiceLocal) -> None:
        service.add_rule("MAPLETRADE INC.")
        assert service.matches("STARBUCKS") is None

    def test_returns_none_when_no_rules(self, service: IgnoreRuleServiceLocal) -> None:
        assert service.matches("anything") is None


class TestDeleteRule:
    def test_removes_entry(self, service: IgnoreRuleServiceLocal) -> None:
        service.add_rule("MAPLETRADE INC.")
        service.add_rule("MiscPayment CARDCO")
        service.delete_rule("MAPLETRADE INC.")
        assert service.get_patterns() == ["MiscPayment CARDCO"]

    def test_case_insensitive_delete(self, service: IgnoreRuleServiceLocal) -> None:
        service.add_rule("MAPLETRADE INC.")
        service.delete_rule("mapletrade inc.")
        assert service.get_patterns() == []

    def test_raises_keyerror_when_absent(self, service: IgnoreRuleServiceLocal) -> None:
        service.add_rule("MAPLETRADE INC.")
        with pytest.raises(KeyError):
            service.delete_rule("NotThere")

    def test_raises_keyerror_when_no_rules(self, service: IgnoreRuleServiceLocal) -> None:
        with pytest.raises(KeyError):
            service.delete_rule("anything")


class TestPutAllRules:
    def test_replaces_full_set(self, service: IgnoreRuleServiceLocal) -> None:
        service.add_rule("MAPLETRADE INC.")
        service.put_all_rules(["A", "B", "  C  "], expected_version=1)
        assert service.get_patterns() == ["A", "B", "C"]


class TestOptimisticLocking:
    def test_version_conflict_when_expected_version_stale(self, service: IgnoreRuleServiceLocal) -> None:
        service.add_rule("MAPLETRADE INC.")
        with pytest.raises(VersionConflictError):
            service._put_all({"X": ""}, expected_version=0)


class TestBackupWriter:
    def test_backup_called_on_add(self, tmp_path: Path) -> None:
        calls: list[list[str]] = []

        def fake_backup(
            self: IgnoreRuleServiceLocal,
            data: dict[str, str],
            dismissed: dict[str, str] | None = None,
        ) -> None:
            calls.append(sorted(data.keys()))

        svc = IgnoreRuleServiceLocal(db_path=tmp_path / "test.db", user_id="test")
        svc._write_backup = fake_backup.__get__(svc, IgnoreRuleServiceLocal)

        svc.add_rule("MAPLETRADE INC.")
        assert calls == [["MAPLETRADE INC."]]


class TestDismissals:
    def test_get_dismissed_empty_when_not_seeded(self, service: IgnoreRuleServiceLocal) -> None:
        assert service.get_dismissed() == {}

    def test_dismiss_adds_lowercased_entry(self, service: IgnoreRuleServiceLocal) -> None:
        service.dismiss_suggestion("MiscPayment CARDCO")
        dismissed = service.get_dismissed()
        assert "miscpayment cardco" in dismissed
        # Value is the {merchant, dismissed_at} object (original casing preserved).
        entry = dismissed["miscpayment cardco"]
        assert entry["merchant"] == "MiscPayment CARDCO"
        assert entry["dismissed_at"]

    def test_list_dismissed_round_trip_preserves_casing(self, service: IgnoreRuleServiceLocal) -> None:
        service.dismiss_suggestion("MiscPayment CARDCO")
        listed = service.list_dismissed()
        assert len(listed) == 1
        assert listed[0]["merchant"] == "MiscPayment CARDCO"
        assert listed[0]["dismissed_at"]

    def test_list_dismissed_empty_when_not_seeded(self, service: IgnoreRuleServiceLocal) -> None:
        assert service.list_dismissed() == []

    def test_list_dismissed_tolerates_legacy_string_value(self, service: IgnoreRuleServiceLocal) -> None:
        # Persist a legacy bare-string dismissal directly, then read it back.
        service._put_all_with_dismissed({}, {"costco": "2026-07-10T00:00:00+00:00"}, None)
        assert service.list_dismissed() == [{"merchant": "costco", "dismissed_at": "2026-07-10T00:00:00+00:00"}]

    def test_dismiss_preserves_existing_rules(self, service: IgnoreRuleServiceLocal) -> None:
        service.add_rule("MAPLETRADE INC.")
        service.dismiss_suggestion("Costco")
        item = service.get_rules()
        assert item is not None
        assert item["Data"] == {"MAPLETRADE INC.": ""}
        assert "costco" in item["Dismissed"]

    def test_undismiss_removes_entry(self, service: IgnoreRuleServiceLocal) -> None:
        service.dismiss_suggestion("Costco")
        service.undismiss_suggestion("costco")
        assert service.get_dismissed() == {}

    def test_undismiss_is_case_insensitive(self, service: IgnoreRuleServiceLocal) -> None:
        service.dismiss_suggestion("Costco")
        service.undismiss_suggestion("COSTCO")
        assert service.get_dismissed() == {}

    def test_undismiss_nonexistent_is_noop(self, service: IgnoreRuleServiceLocal) -> None:
        # No item at all — must not raise.
        service.undismiss_suggestion("nothing")
        # Item exists but key absent — also a no-op.
        service.dismiss_suggestion("Costco")
        service.undismiss_suggestion("elsewhere")
        assert "costco" in service.get_dismissed()

    def test_dismiss_survives_rule_mutation(self, service: IgnoreRuleServiceLocal) -> None:
        # A later add_rule must preserve the Dismissed map (no clobber).
        service.dismiss_suggestion("Costco")
        service.add_rule("MAPLETRADE INC.")
        assert "costco" in service.get_dismissed()
