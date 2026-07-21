"""Tests for IgnoreRuleService — merchant auto-ignore CRUD with DynamoDB + JSON backup."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from src.finance.exceptions import VersionConflictError
from src.finance.ignore_rule_service import IgnoreRuleService


def _make_service(dyn_resource: MagicMock | None = None) -> IgnoreRuleService:
    if dyn_resource is None:
        dyn_resource = MagicMock()
        dyn_resource.Table.return_value = MagicMock(name="dynamodb_table")
    return IgnoreRuleService(dyn_resource=dyn_resource)


class TestGetRules:
    def test_returns_none_when_empty(self) -> None:
        svc = _make_service()
        svc.table.get_item.return_value = {}
        assert svc.get_rules() is None

    def test_returns_item_when_present(self) -> None:
        item = {
            "PK": "USER#default",
            "SK": "CONFIG#ignore_rules",
            "Data": {"MAPLETRADE INC.": ""},
            "Version": 1,
        }
        svc = _make_service()
        svc.table.get_item.return_value = {"Item": item}
        result = svc.get_rules()
        assert result is not None
        assert result["Version"] == 1
        assert "MAPLETRADE INC." in result["Data"]

    def test_uses_correct_key(self) -> None:
        svc = _make_service()
        svc.table.get_item.return_value = {}
        svc.get_rules()
        svc.table.get_item.assert_called_once_with(Key={"PK": "USER#default", "SK": "CONFIG#ignore_rules"})


class TestAddRule:
    def test_adds_to_existing(self) -> None:
        svc = _make_service()
        svc.get_rules = MagicMock(return_value={"Data": {"EXISTING": ""}, "Version": 1})
        svc.table.put_item.return_value = {}
        svc._write_backup = MagicMock()

        new_version = svc.add_rule("MAPLETRADE INC.")
        assert new_version == 2
        put_item = svc.table.put_item.call_args[1]["Item"]
        assert put_item["Data"] == {"EXISTING": "", "MAPLETRADE INC.": ""}

    def test_creates_from_scratch_when_none(self) -> None:
        svc = _make_service()
        svc.get_rules = MagicMock(return_value=None)
        svc.table.put_item.return_value = {}
        svc._write_backup = MagicMock()

        new_version = svc.add_rule("MAPLETRADE INC.")
        assert new_version == 1
        call_kwargs = svc.table.put_item.call_args[1]
        assert call_kwargs["ConditionExpression"] == "attribute_not_exists(Version)"
        assert call_kwargs["Item"]["Data"] == {"MAPLETRADE INC.": ""}

    def test_case_insensitive_dedupe(self) -> None:
        svc = _make_service()
        svc.get_rules = MagicMock(return_value={"Data": {"MAPLETRADE INC.": ""}, "Version": 1})
        svc.table.put_item.return_value = {}
        svc._write_backup = MagicMock()

        svc.add_rule("mapletrade inc.")
        put_item = svc.table.put_item.call_args[1]["Item"]
        assert put_item["Data"] == {"MAPLETRADE INC.": ""}


class TestDeleteRule:
    def test_removes_existing(self) -> None:
        svc = _make_service()
        svc.get_rules = MagicMock(return_value={"Data": {"MAPLETRADE INC.": "", "CARDCO": ""}, "Version": 2})
        svc.table.put_item.return_value = {}
        svc._write_backup = MagicMock()

        svc.delete_rule("MAPLETRADE INC.")
        put_item = svc.table.put_item.call_args[1]["Item"]
        assert put_item["Data"] == {"CARDCO": ""}

    def test_case_insensitive_delete(self) -> None:
        svc = _make_service()
        svc.get_rules = MagicMock(return_value={"Data": {"MAPLETRADE INC.": ""}, "Version": 1})
        svc.table.put_item.return_value = {}
        svc._write_backup = MagicMock()

        svc.delete_rule("mapletrade inc.")
        put_item = svc.table.put_item.call_args[1]["Item"]
        assert put_item["Data"] == {}

    def test_raises_key_error_when_not_found(self) -> None:
        svc = _make_service()
        svc.get_rules = MagicMock(return_value={"Data": {"MAPLETRADE INC.": ""}, "Version": 1})
        with pytest.raises(KeyError):
            svc.delete_rule("NONEXISTENT")

    def test_raises_key_error_when_no_rules(self) -> None:
        svc = _make_service()
        svc.get_rules = MagicMock(return_value=None)
        with pytest.raises(KeyError):
            svc.delete_rule("ANYTHING")


class TestPutAllRules:
    def test_writes_with_version(self) -> None:
        svc = _make_service()
        svc.table.put_item.return_value = {}
        svc._write_backup = MagicMock()

        new_version = svc.put_all_rules(["A", "B"], expected_version=5)
        assert new_version == 6
        call_kwargs = svc.table.put_item.call_args[1]
        assert call_kwargs["ConditionExpression"] == "Version = :expected"
        assert call_kwargs["ExpressionAttributeValues"] == {":expected": 5}
        assert call_kwargs["Item"]["Data"] == {"A": "", "B": ""}

    def test_raises_on_version_conflict(self) -> None:
        svc = _make_service()
        error_response: Any = {"Error": {"Code": "ConditionalCheckFailedException", "Message": "conflict"}}
        svc.table.put_item.side_effect = ClientError(error_response, "PutItem")
        with pytest.raises(VersionConflictError):
            svc.put_all_rules(["A"], expected_version=1)


class TestDismissals:
    def test_dismiss_adds_lowercased_entry(self) -> None:
        svc = _make_service()
        svc.get_rules = MagicMock(return_value={"Data": {"EXISTING": ""}, "Version": 1})
        svc.table.put_item.return_value = {}
        svc._write_backup = MagicMock()

        svc.dismiss_suggestion("MiscPayment CARDCO")
        put_item = svc.table.put_item.call_args[1]["Item"]
        # Rules preserved; dismissal recorded under the lowercased merchant.
        assert put_item["Data"] == {"EXISTING": ""}
        assert "miscpayment cardco" in put_item["Dismissed"]
        assert put_item["Version"] == 2

    def test_dismiss_creates_item_when_none(self) -> None:
        svc = _make_service()
        svc.get_rules = MagicMock(return_value=None)
        svc.table.put_item.return_value = {}
        svc._write_backup = MagicMock()

        svc.dismiss_suggestion("Costco")
        call_kwargs = svc.table.put_item.call_args[1]
        assert call_kwargs["ConditionExpression"] == "attribute_not_exists(Version)"
        assert "costco" in call_kwargs["Item"]["Dismissed"]

    def test_undismiss_removes_entry(self) -> None:
        svc = _make_service()
        svc.get_rules = MagicMock(
            return_value={"Data": {}, "Version": 3, "Dismissed": {"costco": "2026-07-16T00:00:00+00:00"}}
        )
        svc.table.put_item.return_value = {}
        svc._write_backup = MagicMock()

        svc.undismiss_suggestion("COSTCO")
        put_item = svc.table.put_item.call_args[1]["Item"]
        # Dismissed now empty, so the key is dropped from the written item.
        assert "Dismissed" not in put_item

    def test_undismiss_nonexistent_is_noop(self) -> None:
        svc = _make_service()
        svc.get_rules = MagicMock(return_value={"Data": {}, "Version": 1, "Dismissed": {}})
        svc.table.put_item.return_value = {}
        svc._write_backup = MagicMock()

        svc.undismiss_suggestion("nothing")
        svc.table.put_item.assert_not_called()

    def test_get_dismissed_returns_map(self) -> None:
        svc = _make_service()
        svc.get_rules = MagicMock(
            return_value={"Data": {}, "Version": 1, "Dismissed": {"costco": "2026-07-16T00:00:00+00:00"}}
        )
        assert svc.get_dismissed() == {"costco": "2026-07-16T00:00:00+00:00"}

    def test_dismiss_stores_object_with_original_casing(self) -> None:
        # New value shape: {merchant: <original casing>, dismissed_at: <iso>}
        # keyed by the lowercased merchant.
        svc = _make_service()
        svc.get_rules = MagicMock(return_value={"Data": {}, "Version": 1})
        svc.table.put_item.return_value = {}
        svc._write_backup = MagicMock()

        svc.dismiss_suggestion("MiscPayment CARDCO")
        entry = svc.table.put_item.call_args[1]["Item"]["Dismissed"]["miscpayment cardco"]
        assert entry["merchant"] == "MiscPayment CARDCO"
        assert entry["dismissed_at"]

    def test_list_dismissed_normalizes_and_sorts_newest_first(self) -> None:
        svc = _make_service()
        svc.get_rules = MagicMock(
            return_value={
                "Data": {},
                "Version": 2,
                "Dismissed": {
                    "costco": {"merchant": "Costco", "dismissed_at": "2026-07-10T00:00:00+00:00"},
                    "miscpayment cardco": {
                        "merchant": "MiscPayment CARDCO",
                        "dismissed_at": "2026-07-16T00:00:00+00:00",
                    },
                },
            }
        )
        result = svc.list_dismissed()
        assert [d["merchant"] for d in result] == ["MiscPayment CARDCO", "Costco"]
        assert result[0]["dismissed_at"] == "2026-07-16T00:00:00+00:00"

    def test_list_dismissed_tolerates_legacy_string_value(self) -> None:
        # Pre-upgrade backups/tests may carry a bare ISO string; the key becomes
        # the display merchant (casing lost) and the string is dismissed_at.
        svc = _make_service()
        svc.get_rules = MagicMock(
            return_value={"Data": {}, "Version": 1, "Dismissed": {"costco": "2026-07-10T00:00:00+00:00"}}
        )
        assert svc.list_dismissed() == [{"merchant": "costco", "dismissed_at": "2026-07-10T00:00:00+00:00"}]

    def test_list_dismissed_empty_when_none(self) -> None:
        svc = _make_service()
        svc.get_rules = MagicMock(return_value=None)
        assert svc.list_dismissed() == []


class TestMatches:
    def test_exact_match(self) -> None:
        svc = _make_service()
        svc.get_rules = MagicMock(return_value={"Data": {"MAPLETRADE INC.": ""}})
        match = svc.matches("mapletrade inc.")
        assert match is not None
        assert match.tier == "exact"

    def test_normalized_match(self) -> None:
        svc = _make_service()
        svc.get_rules = MagicMock(return_value={"Data": {"MiscPayment CARDCO #221": ""}})
        match = svc.matches("MiscPayment CARDCO #999")
        assert match is not None
        assert match.tier == "normalized"

    def test_no_match_returns_none(self) -> None:
        svc = _make_service()
        svc.get_rules = MagicMock(return_value={"Data": {"MAPLETRADE INC.": ""}})
        assert svc.matches("STARBUCKS") is None

    def test_no_rules_returns_none(self) -> None:
        svc = _make_service()
        svc.get_rules = MagicMock(return_value=None)
        assert svc.matches("MAPLETRADE INC.") is None
