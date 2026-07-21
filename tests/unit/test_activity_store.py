"""Dual-backend contract for the agent-activity ledger.

Each scenario runs against *both* ``ActivityStore`` (DynamoDB via moto) and
``ActivityStoreLocal`` (SQLite via tmp_path), asserting identical observable
behavior. The moto store relies on lazy auto-create — the table is NOT
pre-provisioned, so the first ``record`` must self-create it (and enable TTL).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import boto3
import pytest
from moto import mock_aws

from src.finance.activity_store import RETENTION_DAYS, ActivityStore
from src.finance.activity_store_local import ActivityStoreLocal
from src.finance.local_db import get_connection
from src.finance.migrations import apply_migrations
from src.finance.protocols import IActivityStore

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def dyn_resource() -> Iterator[Any]:
    """In-memory moto DynamoDB with NO tables pre-created (lazy auto-create)."""
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
    with mock_aws():
        yield boto3.resource("dynamodb", region_name="us-west-2")


def _days_ago(n: int) -> str:
    """Timezone-aware UTC ISO timestamp ``n`` days before now.

    Used instead of hardcoded calendar dates so fixtures stay inside the SQLite
    prune window (entries older than the retention horizon are evicted on write).
    """
    return (datetime.now(UTC) - timedelta(days=n)).isoformat()


def _entry(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "principal_kind": "token",
        "principal_id": "tok_abc123",
        "principal_label": "laptop-claude",
        "operation_id": "patchTransaction",
        "method": "PATCH",
        "path": "/api/v1/transactions/2026.02.15_10.30_x.eml",
        "resource_id": "2026.02.15_10.30_x.eml",
        "summary": "changed category to Groceries",
        "before_json": '{"Category": "Uncategorized"}',
        "after_json": '{"Category": "Groceries"}',
        "reversible": True,
    }
    base.update(overrides)
    return base


class TestActivityStoreContract:
    @pytest.fixture(params=["dynamodb", "sqlite"])
    def store(self, request: pytest.FixtureRequest, dyn_resource: Any, tmp_path: Path) -> Any:
        if request.param == "dynamodb":
            # No table pre-created — assert lazy auto-create works.
            return ActivityStore(dyn_resource=dyn_resource)
        return ActivityStoreLocal(db_path=tmp_path / "activity.db")

    def test_record_then_get_roundtrip(self, store: Any) -> None:
        entry_id = store.record(_entry())
        # Default id is a uuid4 hex (32 hex chars).
        assert len(entry_id) == 32
        assert all(c in "0123456789abcdef" for c in entry_id)

        got = store.get_entry(entry_id)
        assert got is not None
        assert got["id"] == entry_id
        assert got["principal_kind"] == "token"
        assert got["principal_id"] == "tok_abc123"
        assert got["principal_label"] == "laptop-claude"
        assert got["operation_id"] == "patchTransaction"
        assert got["method"] == "PATCH"
        assert got["resource_id"] == "2026.02.15_10.30_x.eml"
        assert got["summary"] == "changed category to Groceries"
        assert got["before_json"] == '{"Category": "Uncategorized"}'
        assert got["after_json"] == '{"Category": "Groceries"}'
        assert got["reversible"] is True
        assert got["reverted_at"] is None
        assert got["reverted_by"] is None
        # ts is server-filled and timezone-aware UTC.
        assert got["ts"] is not None
        parsed = datetime.fromisoformat(got["ts"])
        assert parsed.tzinfo is not None

    def test_record_honors_explicit_id_and_ts(self, store: Any) -> None:
        ts = _days_ago(1)
        entry_id = store.record(_entry(id="deadbeefcafe0001", ts=ts))
        assert entry_id == "deadbeefcafe0001"
        got = store.get_entry(entry_id)
        assert got is not None
        assert got["ts"] == ts

    def test_get_missing_returns_none(self, store: Any) -> None:
        assert store.get_entry("nope") is None

    def test_list_roundtrip_and_newest_first(self, store: Any) -> None:
        store.record(_entry(id="a" * 32, ts=_days_ago(30), summary="oldest"))
        store.record(_entry(id="b" * 32, ts=_days_ago(1), summary="newest"))
        store.record(_entry(id="c" * 32, ts=_days_ago(15), summary="middle"))

        rows = store.list_entries()
        assert [r["summary"] for r in rows] == ["newest", "middle", "oldest"]

    def test_list_filters_by_principal(self, store: Any) -> None:
        store.record(_entry(id="a" * 32, principal_id="tok_one"))
        store.record(_entry(id="b" * 32, principal_id="tok_two"))

        rows = store.list_entries(principal="tok_one")
        assert {r["principal_id"] for r in rows} == {"tok_one"}
        assert len(rows) == 1

    def test_list_filters_by_since_inclusive(self, store: Any) -> None:
        old = _days_ago(30)
        boundary = _days_ago(15)
        recent = _days_ago(1)
        store.record(_entry(id="a" * 32, ts=old))
        store.record(_entry(id="b" * 32, ts=boundary))
        store.record(_entry(id="c" * 32, ts=recent))

        # Inclusive lower bound: the boundary entry is included.
        rows = store.list_entries(since=boundary)
        assert {r["ts"] for r in rows} == {boundary, recent}

    def test_list_filters_by_operation(self, store: Any) -> None:
        store.record(_entry(id="a" * 32, operation_id="patchTransaction"))
        store.record(_entry(id="b" * 32, operation_id="putOverride"))

        rows = store.list_entries(operation="putOverride")
        assert {r["operation_id"] for r in rows} == {"putOverride"}

    def test_list_limit_applied_after_filtering(self, store: Any) -> None:
        newest = _days_ago(1)
        store.record(_entry(id=f"{0:032x}", ts=newest))
        for i in range(1, 5):
            store.record(_entry(id=f"{i:032x}", ts=_days_ago(1 + i * 5)))
        rows = store.list_entries(limit=2)
        assert len(rows) == 2
        # Limit keeps the newest.
        assert rows[0]["ts"] == newest

    def test_list_kind_filter_applies_before_limit(self, store: Any) -> None:
        # Three token entries newer than one session entry, with limit=2: a
        # post-limit kind filter would slice off the two newest (both token) and
        # then filter to nothing, starving the session caller's own feed. The
        # store must filter by principal_kind BEFORE the limit.
        store.record(_entry(id="a" * 32, ts=_days_ago(1), principal_kind="token"))
        store.record(_entry(id="b" * 32, ts=_days_ago(2), principal_kind="token"))
        store.record(_entry(id="c" * 32, ts=_days_ago(3), principal_kind="token"))
        store.record(_entry(id="d" * 32, ts=_days_ago(4), principal_kind="session", summary="mine"))

        rows = store.list_entries(limit=2, principal_kind="session")
        assert [r["summary"] for r in rows] == ["mine"]
        assert all(r["principal_kind"] == "session" for r in rows)

    def test_list_kind_filter_composes_with_other_filters(self, store: Any) -> None:
        store.record(_entry(id="a" * 32, principal_kind="token", operation_id="putOverride"))
        store.record(_entry(id="b" * 32, principal_kind="session", operation_id="putOverride"))
        store.record(_entry(id="c" * 32, principal_kind="session", operation_id="patchTransaction"))

        rows = store.list_entries(principal_kind="session", operation="putOverride")
        assert len(rows) == 1
        assert rows[0]["principal_kind"] == "session"
        assert rows[0]["operation_id"] == "putOverride"

    def test_mark_reverted_sets_both_fields(self, store: Any) -> None:
        original = store.record(_entry(id="a" * 32))
        reverting = store.record(_entry(id="b" * 32, summary="revert of a"))

        store.mark_reverted(original, reverting)
        got = store.get_entry(original)
        assert got is not None
        assert got["reverted_by"] == reverting
        assert got["reverted_at"] is not None
        parsed = datetime.fromisoformat(got["reverted_at"])
        assert parsed.tzinfo is not None

    def test_append_only_no_mutation_methods(self, store: Any) -> None:
        # The only public mutators are ``record`` and ``mark_reverted``. No
        # update/delete/set method may exist — append-only is the point.
        forbidden = {
            name
            for name in dir(store)
            if not name.startswith("_")
            and callable(getattr(store, name))
            and name != "mark_reverted"
            and (name.startswith(("update", "delete", "set_", "remove", "put_")))
        }
        assert forbidden == set()

    def test_reversible_false_roundtrip(self, store: Any) -> None:
        entry_id = store.record(_entry(id="a" * 32, reversible=False))
        got = store.get_entry(entry_id)
        assert got is not None
        assert got["reversible"] is False


def test_protocol_exposes_only_append_only_surface() -> None:
    # The protocol itself must not advertise any mutation beyond mark_reverted.
    members = {name for name in dir(IActivityStore) if not name.startswith("_")}
    assert members == {"record", "list_entries", "get_entry", "mark_reverted"}


class TestActivityStoreLocalPrune:
    """SQLite-only: prune-on-write removes entries older than the retention window."""

    def test_prune_on_write_removes_old_entries(self, tmp_path: Path) -> None:
        store = ActivityStoreLocal(db_path=tmp_path / "activity.db")

        old_ts = (datetime.now(UTC) - timedelta(days=RETENTION_DAYS + 30)).isoformat()
        old_id = store.record(_entry(id="a" * 32, ts=old_ts))
        # Still present immediately after its own write (prune ran, but this row
        # is the just-written one — old_ts predates the cutoff, so a *subsequent*
        # write should evict it).
        recent_id = store.record(_entry(id="b" * 32))

        assert store.get_entry(old_id) is None
        assert store.get_entry(recent_id) is not None

    def test_prune_keeps_recent_entries(self, tmp_path: Path) -> None:
        store = ActivityStoreLocal(db_path=tmp_path / "activity.db")
        recent_ts = (datetime.now(UTC) - timedelta(days=RETENTION_DAYS - 10)).isoformat()
        keep_id = store.record(_entry(id="a" * 32, ts=recent_ts))
        store.record(_entry(id="b" * 32))
        assert store.get_entry(keep_id) is not None


class TestActivityStoreDynamoTTL:
    """DynamoDB-only: every item carries a ttl = ts + 90d and TTL is enabled."""

    def test_item_carries_ttl(self, dyn_resource: Any) -> None:
        store = ActivityStore(dyn_resource=dyn_resource)
        ts = "2026-01-01T00:00:00+00:00"
        store.record(_entry(id="a" * 32, ts=ts))

        item = store.table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("PK").eq(store.USER_PK),
        )["Items"][0]
        expected = int((datetime.fromisoformat(ts) + timedelta(days=RETENTION_DAYS)).timestamp())
        assert int(item["ttl"]) == expected

    def test_time_to_live_enabled(self, dyn_resource: Any) -> None:
        store = ActivityStore(dyn_resource=dyn_resource)
        store.record(_entry(id="a" * 32))

        desc = store.dyn_resource.meta.client.describe_time_to_live(TableName=ActivityStore.TABLE_NAME)
        spec = desc["TimeToLiveDescription"]
        assert spec["TimeToLiveStatus"] in ("ENABLED", "ENABLING")
        assert spec.get("AttributeName") == "ttl"


class TestActivityStoreDynamoMarkReverted:
    """DynamoDB-only: mark_reverted(ts=...) reconstructs the SK with no scan."""

    def test_mark_reverted_with_ts_skips_partition_scan(
        self, dyn_resource: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = ActivityStore(dyn_resource=dyn_resource)
        ts = "2026-01-01T00:00:00+00:00"
        original = store.record(_entry(id="a" * 32, ts=ts))
        reverting = store.record(_entry(id="b" * 32))

        # With ts provided the key is reconstructed directly — any _query_all call
        # means the scanning fallback ran when it should not have.
        def _fail() -> list[dict[str, Any]]:
            raise AssertionError("_query_all called despite ts being provided")

        monkeypatch.setattr(store, "_query_all", _fail)
        store.mark_reverted(original, reverting, ts=ts)
        monkeypatch.undo()

        # The reconstructed key addressed the right item.
        got = store.get_entry(original)
        assert got is not None
        assert got["reverted_by"] == reverting
        assert got["reverted_at"] is not None


class TestActivityMigration:
    """Migration 004 applies cleanly on a 003-level DB and matches a fresh DB."""

    @staticmethod
    def _activity_schema(path: Path) -> dict[str, str]:
        conn = get_connection(path)
        try:
            rows = conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE name = 'activity' OR name = 'idx_activity_ts' ORDER BY name"
            ).fetchall()
            return {r["name"]: r["sql"] for r in rows}
        finally:
            conn.close()

    def test_migration_matches_fresh_schema(self, tmp_path: Path) -> None:
        # Fresh DB: full schema (activity comes from local_db._SCHEMA_SQL).
        fresh = tmp_path / "fresh.db"
        ActivityStoreLocal(db_path=fresh)  # __init__ runs ensure_schema
        fresh_schema = self._activity_schema(fresh)
        assert "activity" in fresh_schema
        assert "idx_activity_ts" in fresh_schema

        # Migrated DB: start at version 3 with no activity table, then apply.
        migrated = tmp_path / "migrated.db"
        conn = get_connection(migrated)
        try:
            conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            for v in (1, 2, 3):
                conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (v, "2026-01-01T00:00:00+00:00"),
                )
            conn.commit()
            applied = apply_migrations(conn)
        finally:
            conn.close()

        assert 4 in applied
        migrated_schema = self._activity_schema(migrated)

        # Fresh and migrated DBs must end up with an identical activity schema.
        assert migrated_schema == fresh_schema
