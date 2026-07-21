"""Tests for OverrideService — CRUD with DynamoDB and JSON backup."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from src.finance.exceptions import VersionConflictError
from src.finance.override_service import OverrideService


def _make_service(dyn_resource: MagicMock | None = None) -> OverrideService:
    if dyn_resource is None:
        dyn_resource = MagicMock()
        dyn_resource.Table.return_value = MagicMock(name="dynamodb_table")
    return OverrideService(dyn_resource=dyn_resource)


# ---------------------------------------------------------------------------
# get_overrides
# ---------------------------------------------------------------------------


class TestGetOverrides:
    def test_returns_none_when_empty(self):
        svc = _make_service()
        svc.table.get_item.return_value = {}
        assert svc.get_overrides() is None

    def test_returns_item_when_present(self):
        item = {
            "PK": "USER#default",
            "SK": "CONFIG#category_overrides",
            "Data": {"AMAZON.CA": "Miscellaneous"},
            "Version": 1,
        }
        svc = _make_service()
        svc.table.get_item.return_value = {"Item": item}
        result = svc.get_overrides()
        assert result is not None
        assert result["Version"] == 1
        assert result["Data"]["AMAZON.CA"] == "Miscellaneous"

    def test_uses_correct_key(self):
        svc = _make_service()
        svc.table.get_item.return_value = {}
        svc.get_overrides()
        svc.table.get_item.assert_called_once_with(Key={"PK": "USER#default", "SK": "CONFIG#category_overrides"})


# ---------------------------------------------------------------------------
# put_override (single member)
# ---------------------------------------------------------------------------


class TestPutOverride:
    def test_adds_to_existing(self):
        svc = _make_service()
        svc.get_overrides = MagicMock(
            return_value={
                "Data": {"EXISTING": "Groceries"},
                "Version": 1,
            }
        )
        svc.table.put_item.return_value = {}
        svc._write_backup = MagicMock()

        new_version = svc.put_override("NEW COMPANY", "Rent")
        assert new_version == 2

        put_item = svc.table.put_item.call_args[1]["Item"]
        assert put_item["Data"]["EXISTING"] == "Groceries"
        assert put_item["Data"]["NEW COMPANY"] == "Rent"

    def test_creates_from_scratch_when_none(self):
        svc = _make_service()
        svc.get_overrides = MagicMock(return_value=None)
        svc.table.put_item.return_value = {}
        svc._write_backup = MagicMock()

        new_version = svc.put_override("FIRST", "Groceries")
        assert new_version == 1

        call_kwargs = svc.table.put_item.call_args[1]
        assert call_kwargs["ConditionExpression"] == "attribute_not_exists(Version)"
        assert call_kwargs["Item"]["Data"] == {"FIRST": "Groceries"}

    def test_updates_existing_company(self):
        svc = _make_service()
        svc.get_overrides = MagicMock(
            return_value={
                "Data": {"AMAZON.CA": "Miscellaneous"},
                "Version": 3,
            }
        )
        svc.table.put_item.return_value = {}
        svc._write_backup = MagicMock()

        svc.put_override("AMAZON.CA", "Technology")
        put_item = svc.table.put_item.call_args[1]["Item"]
        assert put_item["Data"]["AMAZON.CA"] == "Technology"


# ---------------------------------------------------------------------------
# delete_override
# ---------------------------------------------------------------------------


class TestDeleteOverride:
    def test_removes_existing_company(self):
        svc = _make_service()
        svc.get_overrides = MagicMock(
            return_value={
                "Data": {"AMAZON.CA": "Miscellaneous", "RENT": "Rent"},
                "Version": 2,
            }
        )
        svc.table.put_item.return_value = {}
        svc._write_backup = MagicMock()

        svc.delete_override("AMAZON.CA")
        put_item = svc.table.put_item.call_args[1]["Item"]
        assert "AMAZON.CA" not in put_item["Data"]
        assert put_item["Data"]["RENT"] == "Rent"

    def test_case_insensitive_delete(self):
        svc = _make_service()
        svc.get_overrides = MagicMock(
            return_value={
                "Data": {"AMAZON.CA": "Miscellaneous"},
                "Version": 1,
            }
        )
        svc.table.put_item.return_value = {}
        svc._write_backup = MagicMock()

        svc.delete_override("amazon.ca")
        put_item = svc.table.put_item.call_args[1]["Item"]
        assert len(put_item["Data"]) == 0

    def test_raises_key_error_when_not_found(self):
        svc = _make_service()
        svc.get_overrides = MagicMock(
            return_value={
                "Data": {"AMAZON.CA": "Miscellaneous"},
                "Version": 1,
            }
        )

        with pytest.raises(KeyError):
            svc.delete_override("NONEXISTENT")

    def test_raises_key_error_when_no_overrides(self):
        svc = _make_service()
        svc.get_overrides = MagicMock(return_value=None)

        with pytest.raises(KeyError):
            svc.delete_override("ANYTHING")


# ---------------------------------------------------------------------------
# put_all_overrides
# ---------------------------------------------------------------------------


class TestPutAllOverrides:
    def test_writes_with_version(self):
        svc = _make_service()
        svc.table.put_item.return_value = {}
        svc._write_backup = MagicMock()

        new_version = svc.put_all_overrides({"A": "B"}, expected_version=5)
        assert new_version == 6

        call_kwargs = svc.table.put_item.call_args[1]
        assert call_kwargs["ConditionExpression"] == "Version = :expected"
        assert call_kwargs["ExpressionAttributeValues"] == {":expected": 5}

    def test_raises_on_version_conflict(self):
        svc = _make_service()
        # error_response: Any sidesteps botocore's private _ClientErrorResponseTypeDef
        # TypedDict invariance — plain dict is correct at runtime.
        error_response: Any = {"Error": {"Code": "ConditionalCheckFailedException", "Message": "conflict"}}
        svc.table.put_item.side_effect = ClientError(error_response, "PutItem")

        with pytest.raises(VersionConflictError):
            svc.put_all_overrides({"A": "B"}, expected_version=1)

    def test_creates_new_with_none_version(self):
        svc = _make_service()
        svc.table.put_item.return_value = {}
        svc._write_backup = MagicMock()

        new_version = svc.put_all_overrides({"A": "B"}, expected_version=None)
        assert new_version == 1

        call_kwargs = svc.table.put_item.call_args[1]
        assert call_kwargs["ConditionExpression"] == "attribute_not_exists(Version)"
        assert "ExpressionAttributeValues" not in call_kwargs


# ---------------------------------------------------------------------------
# _write_backup
# ---------------------------------------------------------------------------


class TestWriteBackup:
    @patch("src.finance.override_service._CONFIG_DIR")
    def test_backup_failure_is_swallowed(self, mock_config_dir: MagicMock) -> None:
        """_write_backup catches exceptions and logs them."""
        mock_config_dir.mkdir.side_effect = OSError("Permission denied")
        svc = _make_service()
        # Should not raise
        svc._write_backup({"A": "B"})


# ---------------------------------------------------------------------------
# lookup_category — tiered resolution via resolve_override
# ---------------------------------------------------------------------------


class TestLookupCategory:
    def test_exact_match_returns_category_preserving_case(self):
        svc = _make_service()
        svc.get_overrides = MagicMock(return_value={"Data": {"AMAZON.CA": "Miscellaneous"}})
        assert svc.lookup_category("amazon.ca") == "Miscellaneous"

    def test_normalized_match_strips_store_number(self):
        """Tier 1: overrides keyed on `BOOSTER JUICE #232` catch `BOOSTER JUICE #999`."""
        svc = _make_service()
        svc.get_overrides = MagicMock(return_value={"Data": {"BOOSTER JUICE #232": "Restaurant/Dining"}})
        assert svc.lookup_category("BOOSTER JUICE #999") == "Restaurant/Dining"

    def test_ambiguous_normalized_group_returns_none(self):
        """Two overrides share a normalized key with different categories — neither resolves."""
        svc = _make_service()
        svc.get_overrides = MagicMock(
            return_value={
                "Data": {
                    "SHOPPERS DRUG MART #123": "Health Care",
                    "SHOPPERS DRUG MART #456": "Groceries",
                },
            }
        )
        assert svc.lookup_category("SHOPPERS DRUG MART #789") is None

    def test_no_match_returns_none(self):
        svc = _make_service()
        svc.get_overrides = MagicMock(return_value={"Data": {"AMAZON.CA": "Miscellaneous"}})
        assert svc.lookup_category("UNKNOWN MERCHANT") is None

    def test_no_overrides_returns_none(self):
        svc = _make_service()
        svc.get_overrides = MagicMock(return_value=None)
        assert svc.lookup_category("AMAZON.CA") is None


class TestConsolidateOverrides:
    """Atomically collapse member overrides into a single canonical entry."""

    def test_consolidate_success(self):
        svc = _make_service()
        svc.get_overrides = MagicMock(
            return_value={
                "Data": {"COFFEE SPOT #1": "Restaurant/Dining", "COFFEE SPOT #2": "Restaurant/Dining"},
                "Version": 2,
            }
        )
        svc.table.put_item.return_value = {}
        svc._write_backup = MagicMock()
        svc.consolidate_overrides("COFFEE SPOT", "Restaurant/Dining", ["COFFEE SPOT #1", "COFFEE SPOT #2"])
        put_item = svc.table.put_item.call_args[1]["Item"]
        assert "COFFEE SPOT #1" not in put_item["Data"]
        assert "COFFEE SPOT #2" not in put_item["Data"]
        assert put_item["Data"]["COFFEE SPOT"] == "Restaurant/Dining"

    def test_consolidate_is_case_insensitive_on_members(self):
        svc = _make_service()
        svc.get_overrides = MagicMock(return_value={"Data": {"Coffee Spot #1": "Restaurant/Dining"}, "Version": 1})
        svc.table.put_item.return_value = {}
        svc._write_backup = MagicMock()
        # Caller passes lowercase but the key is mixed-case.
        svc.consolidate_overrides("COFFEE SPOT", "Restaurant/Dining", ["coffee spot #1"])
        put_item = svc.table.put_item.call_args[1]["Item"]
        assert "Coffee Spot #1" not in put_item["Data"]
        assert put_item["Data"]["COFFEE SPOT"] == "Restaurant/Dining"

    def test_consolidate_missing_member_raises_keyerror(self):
        svc = _make_service()
        svc.get_overrides = MagicMock(return_value={"Data": {"COFFEE SPOT #1": "Restaurant/Dining"}, "Version": 1})
        with pytest.raises(KeyError):
            svc.consolidate_overrides(
                "COFFEE SPOT", "Restaurant/Dining", ["COFFEE SPOT #1", "COFFEE SPOT #NONEXISTENT"]
            )

    def test_consolidate_canonical_collision_raises_fileexists(self):
        svc = _make_service()
        svc.get_overrides = MagicMock(
            return_value={
                "Data": {
                    "COFFEE SPOT #1": "Restaurant/Dining",
                    "COFFEE SPOT": "Restaurant/Dining",  # already exists as canonical
                },
                "Version": 1,
            }
        )
        with pytest.raises(FileExistsError):
            svc.consolidate_overrides("COFFEE SPOT", "Restaurant/Dining", ["COFFEE SPOT #1"])

    def test_consolidate_canonical_can_be_one_of_members(self):
        """If the canonical key is itself a member, the member is deleted then
        re-added with the (possibly new) canonical category — no collision."""
        svc = _make_service()
        svc.get_overrides = MagicMock(
            return_value={"Data": {"COFFEE SPOT": "Old", "COFFEE SPOT #1": "Old"}, "Version": 1}
        )
        svc.table.put_item.return_value = {}
        svc._write_backup = MagicMock()
        svc.consolidate_overrides("COFFEE SPOT", "Restaurant/Dining", ["COFFEE SPOT", "COFFEE SPOT #1"])
        put_item = svc.table.put_item.call_args[1]["Item"]
        assert put_item["Data"] == {"COFFEE SPOT": "Restaurant/Dining"}

    def test_consolidate_empty_members_raises_valueerror(self):
        svc = _make_service()
        with pytest.raises(ValueError, match="members cannot be empty"):
            svc.consolidate_overrides("COFFEE SPOT", "Restaurant/Dining", [])

    def test_consolidate_no_overrides_item_raises_keyerror(self):
        svc = _make_service()
        svc.get_overrides = MagicMock(return_value=None)
        with pytest.raises(KeyError):
            svc.consolidate_overrides("COFFEE SPOT", "Restaurant/Dining", ["COFFEE SPOT #1"])
