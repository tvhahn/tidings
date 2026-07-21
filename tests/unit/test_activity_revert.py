"""Phase 4 tests — ``POST /api/v1/activity/{id}/revert`` and the dispatch table.

Each domain gets a real write→revert round-trip against a real SQLite backend
(wired through ``dependency_overrides`` so the revert applies against the same
store the write used), plus the guard rails: double-revert, non-reversible entry,
unknown id, the stale-revert conflict check (with ``force`` override), and the
capture linkage (the original entry is marked reverted; the revert is itself a
new, reversible entry).

Capture is fire-and-forget in production (L7); like the P3 tests this monkeypatches
``_dispatch_record`` to a synchronous ``store.record``. The revert→original
``mark_reverted`` link (L8) no longer rides on the capture task — the handler
stamps it synchronously before returning — so a plain synchronous record is
enough for the linkage assertions to hold.
"""

from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from src.api import activity as activity_module
from src.api import dependencies as deps_module
from src.api.activity_revert import RevertServices, revert_put_budget_config
from src.api.dependencies import (
    get_budget_service,
    get_merchant_alias_service,
    get_override_service,
    get_transactions_db,
)
from src.api.errors import ApiException
from src.api.main import create_app
from src.finance import agent_tokens, app_config
from src.finance.activity_store_local import ActivityStoreLocal
from src.finance.budget_service_local import BudgetServiceLocal
from src.finance.merchant_alias_service_local import MerchantAliasServiceLocal
from src.finance.override_service_local import OverrideServiceLocal
from src.finance.transaction_db_local import TransactionsDBLocal
from src.finance.tx_id import tx_id_from_composite
from tests.asserts import assert_ok, assert_problem

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

FORWARDED_TO = "user@example.com"
_YEAR = 2026


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Pin app_config persistence at a tmp file so tokens seed cleanly."""
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(app_config, "_CONFIG_PATH", cfg_path)
    app_config.invalidate_config_cache()
    yield cfg_path
    app_config.invalidate_config_cache()


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_config: Path, api_client_factory: Any) -> Any:
    """A client wired to real SQLite backends + a synchronous, linked ledger."""
    store = ActivityStoreLocal(tmp_path / "activity.db")
    monkeypatch.setattr(deps_module, "_activity_store", store)
    # Synchronous capture (a plain record). The revert→original mark_reverted link
    # is now stamped synchronously by the handler, not by the capture task.
    monkeypatch.setattr(activity_module, "_dispatch_record", lambda s, entry: s.record(entry))

    txdb = TransactionsDBLocal(db_path=tmp_path / "txns.db")
    override_svc = OverrideServiceLocal(db_path=tmp_path / "overrides.db")
    alias_svc = MerchantAliasServiceLocal(db_path=tmp_path / "aliases.db")
    budget_svc = BudgetServiceLocal(db_path=tmp_path / "budget.db")

    app = create_app()
    app.dependency_overrides[get_transactions_db] = lambda: txdb
    app.dependency_overrides[get_override_service] = lambda: override_svc
    app.dependency_overrides[get_merchant_alias_service] = lambda: alias_svc
    app.dependency_overrides[get_budget_service] = lambda: budget_svc
    client = api_client_factory(app)

    _record, raw = agent_tokens.add_token(label="kitchen-agent", scope="read+write")
    headers = {"Authorization": f"Bearer {raw}"}

    return SimpleNamespace(
        client=client,
        headers=headers,
        store=store,
        txdb=txdb,
        override=override_svc,
        alias=alias_svc,
        budget=budget_svc,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_txn(
    txdb: TransactionsDBLocal,
    *,
    file_name: str,
    category: str = "groceries",
    company: str = "Test Store",
    amount: float = 42.50,
) -> tuple[str, str, str]:
    """Add a transaction; return (forwarded_to, date_file_name, tx_id)."""
    dfn = txdb.add_transaction(
        {
            "forwarded_to": FORWARDED_TO,
            "file_name": file_name,
            "date": "02/15/2026 10:30 PST",
            "amount": amount,
            "company": company,
            "category": category,
            "institution": "RBC",
            "transaction_type": "purchase",
            "user_id": "alice",
        }
    )
    assert isinstance(dfn, str)
    return FORWARDED_TO, dfn, tx_id_from_composite(FORWARDED_TO, dfn)


def _last_entry(env: Any) -> dict[str, Any]:
    """The newest ledger entry (the one a just-completed write produced)."""
    entries = env.store.list_entries()
    assert entries, "expected at least one ledger entry"
    return entries[0]


def _before(entry: dict[str, Any]) -> Any:
    """Parse a stored entry's ``before_json`` image (store rows keep JSON)."""
    return json.loads(entry["before_json"]) if entry.get("before_json") else None


def _revert(env: Any, entry_id: str, *, force: bool = False) -> Any:
    url = f"/api/v1/activity/{entry_id}/revert"
    if force:
        url += "?force=true"
    return env.client.post(url, headers=env.headers)


def _budget_body(spending_ceiling: float) -> dict[str, Any]:
    return {
        "spending_ceiling": spending_ceiling,
        "categories": {"groceries": {"target": 7200.0, "input_mode": "monthly", "category_type": "variable"}},
        "groups": [{"name": "Essentials", "categories": ["groceries"]}],
        "targets_version": None,
        "groups_version": None,
    }


# ---------------------------------------------------------------------------
# Per-domain round-trips
# ---------------------------------------------------------------------------


class TestTransactionReverts:
    def test_patch_category_revert_restores_old_category(self, env: Any) -> None:
        ft, dfn, tx_id = _seed_txn(env.txdb, file_name="patch.eml", category="groceries")
        assert_ok(env.client.patch(f"/api/v1/transactions/{tx_id}", json={"category": "Dining"}, headers=env.headers))
        assert env.txdb.get_item(ft, dfn)["Category"] == "dining"

        entry = _last_entry(env)
        assert entry["operation_id"] == "patchTransaction"
        body = assert_ok(_revert(env, entry["id"]))
        assert body["reverted_entry_id"] == entry["id"]
        assert env.txdb.get_item(ft, dfn)["Category"] == "groceries"

    def test_patch_state_revert_restores_ignored_and_trashed(self, env: Any) -> None:
        ft, dfn, tx_id = _seed_txn(env.txdb, file_name="state.eml")
        assert_ok(env.client.patch(f"/api/v1/transactions/{tx_id}", json={"state": "trashed"}, headers=env.headers))
        assert env.txdb.get_item(ft, dfn).get("DeletedAt") is not None

        entry = _last_entry(env)
        assert_ok(_revert(env, entry["id"]))
        assert env.txdb.get_item(ft, dfn).get("DeletedAt") is None

    def test_comment_revert_restores_previous_comment(self, env: Any) -> None:
        ft, dfn, tx_id = _seed_txn(env.txdb, file_name="comment.eml")
        assert_ok(
            env.client.put(
                f"/api/v1/transactions/{tx_id}/comment", json={"comment": "split w/ roommate"}, headers=env.headers
            )
        )
        assert env.txdb.get_item(ft, dfn).get("Comment") == "split w/ roommate"

        entry = _last_entry(env)
        assert entry["operation_id"] == "setTransactionComment"
        assert_ok(_revert(env, entry["id"]))
        # No prior comment → restored to absent.
        assert env.txdb.get_item(ft, dfn).get("Comment") is None

    def test_fields_revert_restores_company_and_amount(self, env: Any) -> None:
        ft, dfn, tx_id = _seed_txn(env.txdb, file_name="fields.eml", company="Test Store", amount=42.50)
        assert_ok(
            env.client.put(
                f"/api/v1/transactions/{tx_id}/fields",
                json={"company": "New Store", "amount": 99.99},
                headers=env.headers,
            )
        )
        after = env.txdb.get_item(ft, dfn)
        assert after["Company"] == "New Store"
        assert float(after["Amount"]) == 99.99

        entry = _last_entry(env)
        assert entry["operation_id"] == "updateTransactionFields"
        assert_ok(_revert(env, entry["id"]))
        restored = env.txdb.get_item(ft, dfn)
        assert restored["Company"] == "Test Store"
        assert float(restored["Amount"]) == 42.50

    def test_bulk_revert_restores_all_three_rows(self, env: Any) -> None:
        # Distinct amounts so the dedup hash keeps all three rows.
        seeds = [_seed_txn(env.txdb, file_name=f"bulk{i}.eml", category="groceries", amount=10.0 + i) for i in range(3)]
        updates = [{"forwarded_to": ft, "date_file_name": dfn, "category": "Dining"} for ft, dfn, _ in seeds]
        assert_ok(
            env.client.patch(
                "/api/v1/transactions/bulk", json={"updates": updates, "source": "manual"}, headers=env.headers
            )
        )
        for ft, dfn, _ in seeds:
            assert env.txdb.get_item(ft, dfn)["Category"] == "dining"

        entry = _last_entry(env)
        assert entry["operation_id"] == "bulkUpdateTransactionCategory"
        assert_ok(_revert(env, entry["id"]))
        for ft, dfn, _ in seeds:
            assert env.txdb.get_item(ft, dfn)["Category"] == "groceries"


class TestOverrideReverts:
    def test_put_override_update_revert_restores_prior_category(self, env: Any) -> None:
        assert_ok(env.client.put("/api/v1/overrides/STARBUCKS", json={"category": "coffee"}, headers=env.headers))
        assert_ok(env.client.put("/api/v1/overrides/STARBUCKS", json={"category": "dining"}, headers=env.headers))
        entry = _last_entry(env)  # the second put (existed-before)
        assert entry["operation_id"] == "putOverride"
        assert _before(entry) == {"company": "STARBUCKS", "category": "coffee"}

        assert_ok(_revert(env, entry["id"]))
        assert env.override.get_overrides()["Data"]["STARBUCKS"] == "coffee"

    def test_put_override_new_revert_deletes_it(self, env: Any) -> None:
        assert_ok(env.client.put("/api/v1/overrides/NEWCO", json={"category": "coffee"}, headers=env.headers))
        entry = _last_entry(env)
        assert _before(entry) == {}  # create-shaped

        assert_ok(_revert(env, entry["id"]))
        assert "NEWCO" not in (env.override.get_overrides() or {"Data": {}})["Data"]

    def test_delete_override_revert_restores_it(self, env: Any) -> None:
        assert_ok(env.client.put("/api/v1/overrides/TIMHORTONS", json={"category": "coffee"}, headers=env.headers))
        assert_ok(env.client.delete("/api/v1/overrides/TIMHORTONS", headers=env.headers))
        entry = _last_entry(env)
        assert entry["operation_id"] == "deleteOverride"

        assert_ok(_revert(env, entry["id"]))
        assert env.override.get_overrides()["Data"]["TIMHORTONS"] == "coffee"


class TestMerchantAliasReverts:
    def test_put_alias_new_revert_deletes_it(self, env: Any) -> None:
        assert_ok(
            env.client.put("/api/v1/merchant-aliases/amzn", json={"canonical_name": "Amazon"}, headers=env.headers)
        )
        entry = _last_entry(env)
        assert entry["operation_id"] == "putMerchantAlias"
        assert _before(entry) == {}

        assert_ok(_revert(env, entry["id"]))
        assert "amzn" not in (env.alias.get_aliases() or {"Data": {}})["Data"]

    def test_delete_alias_revert_restores_it(self, env: Any) -> None:
        assert_ok(
            env.client.put("/api/v1/merchant-aliases/wf", json={"canonical_name": "Whole Foods"}, headers=env.headers)
        )
        assert_ok(env.client.delete("/api/v1/merchant-aliases/wf", headers=env.headers))
        entry = _last_entry(env)
        assert entry["operation_id"] == "deleteMerchantAlias"

        assert_ok(_revert(env, entry["id"]))
        assert env.alias.get_aliases()["Data"]["wf"] == "Whole Foods"


class TestBudgetAndGroupsReverts:
    def test_budget_config_revert_restores_prior_document(self, env: Any) -> None:
        first = assert_ok(
            env.client.put(f"/api/v1/budget/config?year={_YEAR}", json=_budget_body(48000.0), headers=env.headers)
        )
        body2 = _budget_body(50000.0)
        body2["targets_version"] = first["targets_version"]
        body2["groups_version"] = first["groups_version"]
        assert_ok(env.client.put(f"/api/v1/budget/config?year={_YEAR}", json=body2, headers=env.headers))
        entry = _last_entry(env)
        assert entry["operation_id"] == "putBudgetConfig"

        assert_ok(_revert(env, entry["id"]))
        cfg = assert_ok(env.client.get(f"/api/v1/budget/config?year={_YEAR}", headers=env.headers))
        assert cfg["spending_ceiling"] == 48000.0

    def test_groups_revert_restores_prior_document(self, env: Any) -> None:
        first = [{"name": "Essentials", "categories": ["groceries"]}]
        second = [{"name": "Essentials", "categories": ["groceries", "rent"]}]
        r1 = assert_ok(env.client.put("/api/v1/groups", json={"groups": first, "version": None}, headers=env.headers))
        assert_ok(
            env.client.put("/api/v1/groups", json={"groups": second, "version": r1["version"]}, headers=env.headers)
        )
        entry = _last_entry(env)
        assert entry["operation_id"] == "putGroups"

        assert_ok(_revert(env, entry["id"]))
        groups = assert_ok(env.client.get("/api/v1/groups", headers=env.headers))["groups"]
        assert groups == first


# ---------------------------------------------------------------------------
# Guard rails
# ---------------------------------------------------------------------------


class TestRevertGuards:
    def test_unknown_id_404(self, env: Any) -> None:
        assert_problem(_revert(env, "does-not-exist"), 404)

    def test_double_revert_409(self, env: Any) -> None:
        _ft, _dfn, tx_id = _seed_txn(env.txdb, file_name="double.eml")
        assert_ok(env.client.patch(f"/api/v1/transactions/{tx_id}", json={"category": "Dining"}, headers=env.headers))
        entry = _last_entry(env)
        assert_ok(_revert(env, entry["id"]))
        # Second revert of the same entry is rejected.
        assert_problem(_revert(env, entry["id"]), 409)

    def test_non_reversible_entry_409(self, env: Any) -> None:
        # An envelope-only entry (reversible: false) — recorded directly.
        entry_id = env.store.record(
            {
                "operation_id": "generateInsights",
                "method": "POST",
                "path": "/api/v1/insights/generate",
                "reversible": False,
            }
        )
        assert_problem(_revert(env, entry_id), 409)

    def test_reversible_but_undispatchable_operation_409(self, env: Any) -> None:
        # reversible:true but no dispatch entry for the operation → 409.
        entry_id = env.store.record(
            {"operation_id": "somethingElse", "method": "PUT", "path": "/api/v1/x", "reversible": True}
        )
        assert_problem(_revert(env, entry_id), 409)


# ---------------------------------------------------------------------------
# Stale-revert guard (L8)
# ---------------------------------------------------------------------------


class TestStaleRevert:
    def test_out_of_band_edit_makes_revert_stale_and_leaves_state(self, env: Any) -> None:
        ft, dfn, tx_id = _seed_txn(env.txdb, file_name="stale.eml", category="groceries")
        assert_ok(env.client.patch(f"/api/v1/transactions/{tx_id}", json={"category": "Dining"}, headers=env.headers))
        entry = _last_entry(env)
        # Someone else moves the row on after the entry was written.
        env.txdb.update_category(ft, dfn, "travel", "manual")

        resp = _revert(env, entry["id"])
        assert_problem(resp, 409, "stale_revert")
        # The newer edit is untouched.
        assert env.txdb.get_item(ft, dfn)["Category"] == "travel"

    def test_force_applies_over_stale(self, env: Any) -> None:
        ft, dfn, tx_id = _seed_txn(env.txdb, file_name="force.eml", category="groceries")
        assert_ok(env.client.patch(f"/api/v1/transactions/{tx_id}", json={"category": "Dining"}, headers=env.headers))
        entry = _last_entry(env)
        env.txdb.update_category(ft, dfn, "travel", "manual")

        assert_ok(_revert(env, entry["id"], force=True))
        assert env.txdb.get_item(ft, dfn)["Category"] == "groceries"

    def test_bulk_one_stale_row_names_that_tx_id(self, env: Any) -> None:
        seeds = [
            _seed_txn(env.txdb, file_name=f"bstale{i}.eml", category="groceries", amount=20.0 + i) for i in range(3)
        ]
        updates = [{"forwarded_to": ft, "date_file_name": dfn, "category": "Dining"} for ft, dfn, _ in seeds]
        assert_ok(
            env.client.patch(
                "/api/v1/transactions/bulk", json={"updates": updates, "source": "manual"}, headers=env.headers
            )
        )
        entry = _last_entry(env)
        # Move the middle row out of band.
        stale_ft, stale_dfn, stale_tx_id = seeds[1]
        env.txdb.update_category(stale_ft, stale_dfn, "travel", "manual")

        resp = _revert(env, entry["id"])
        problem = assert_problem(resp, 409, "stale_revert")
        assert problem["details"]["stale_tx_ids"] == [stale_tx_id]
        # Nothing restored — the two non-stale rows are still dining.
        assert env.txdb.get_item(seeds[0][0], seeds[0][1])["Category"] == "dining"


# ---------------------------------------------------------------------------
# Capture linkage (L8): the revert is itself a reversible, linked entry
# ---------------------------------------------------------------------------


class TestRevertLinkage:
    def test_revert_marks_original_and_records_new_entry(self, env: Any) -> None:
        _ft, _dfn, tx_id = _seed_txn(env.txdb, file_name="link.eml", category="groceries")
        assert_ok(env.client.patch(f"/api/v1/transactions/{tx_id}", json={"category": "Dining"}, headers=env.headers))
        original = _last_entry(env)

        assert_ok(_revert(env, original["id"]))

        # The original is now stamped reverted.
        refreshed = env.store.get_entry(original["id"])
        assert refreshed is not None
        assert refreshed["reverted_at"] is not None

        # A new revert entry exists with the revert summary. It keeps its images
        # for transparency but is NOT reversible: revertActivity has no dispatch
        # entry (redo is out of scope), and a reversible flag the endpoint would
        # 409 on would render a dead button in the feed.
        revert_entries = [e for e in env.store.list_entries() if e["operation_id"] == "revertActivity"]
        assert len(revert_entries) == 1
        revert_entry = revert_entries[0]
        assert revert_entry["summary"] == f"revert of {original['id']}"
        assert revert_entry["reversible"] is False
        assert revert_entry["before_json"] is not None
        # reverted_by points at the new receipt's (pre-generated) id; no transient
        # linkage key ever leaks onto the persisted receipt.
        assert refreshed["reverted_by"] == revert_entry["id"]
        assert "revert_of" not in revert_entry

    def test_mark_reverted_is_synchronous_independent_of_capture(
        self, env: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The original is stamped reverted synchronously by the handler, not by
        the fire-and-forget receipt: even with capture dropped entirely, the
        original is marked and an immediate (undrained) second revert 409s."""
        _ft, _dfn, tx_id = _seed_txn(env.txdb, file_name="sync.eml", category="groceries")
        assert_ok(env.client.patch(f"/api/v1/transactions/{tx_id}", json={"category": "Dining"}, headers=env.headers))
        original = _last_entry(env)

        # Drop the capture receipt entirely — the linkage must not depend on it.
        monkeypatch.setattr(activity_module, "_dispatch_record", lambda s, entry: None)

        assert_ok(_revert(env, original["id"]))
        refreshed = env.store.get_entry(original["id"])
        assert refreshed is not None
        # Stamped synchronously despite no receipt being written.
        assert refreshed["reverted_at"] is not None
        assert refreshed["reverted_by"] is not None
        # Immediate second revert (no drain, no receipt landed) is still rejected.
        assert_problem(_revert(env, original["id"]), 409)
        # And indeed no revert receipt was ever recorded (capture was a no-op).
        assert [e for e in env.store.list_entries() if e["operation_id"] == "revertActivity"] == []


# ---------------------------------------------------------------------------
# FIX 1 — recursive normalization: nested Decimals vs float after-images
# ---------------------------------------------------------------------------


class _NestedDecimalBudgetService:
    """Budget service whose stored ``Data`` nests Decimals (DynamoDB-shaped read).

    The real DynamoDB budget service persists targets/groups through
    ``_floats_to_decimals``, so a live read returns Decimals nested inside
    dicts/lists while the ledger after-image (JSON) carries plain floats.
    """

    def __init__(self, targets_data: Any, groups_data: Any) -> None:
        self._targets = {"Data": targets_data, "Version": 3}
        self._groups = {"Data": groups_data, "Version": 5}
        self.puts: list[tuple[str, Any, Any]] = []

    def get_targets(self, year: int) -> dict[str, Any]:
        return self._targets

    def get_groups(self, year: int) -> dict[str, Any]:
        return self._groups

    def put_targets(self, year: int, data: dict[str, Any], expected_version: int | None) -> int:
        self.puts.append(("targets", data, expected_version))
        return (expected_version or 0) + 1

    def put_groups(self, year: int, data: Any, expected_version: int | None) -> int:
        self.puts.append(("groups", data, expected_version))
        return (expected_version or 0) + 1


def _budget_entry(after: dict[str, Any], before: dict[str, Any]) -> dict[str, Any]:
    return {
        "operation_id": "putBudgetConfig",
        "resource_id": None,
        "before_json": json.dumps(before),
        "after_json": json.dumps(after),
        "reversible": True,
    }


class TestNestedDecimalStaleGuard:
    def _services(self, budget_svc: Any) -> RevertServices:
        return RevertServices(
            transactions_db=None,  # type: ignore[arg-type]
            override_service=None,  # type: ignore[arg-type]
            merchant_alias_service=None,  # type: ignore[arg-type]
            budget_service=budget_svc,
        )

    def test_unchanged_nested_decimal_state_is_not_stale(self) -> None:
        after = {
            "targets": {"groceries": {"target": 720.5}},
            "groups": [{"name": "Essentials", "categories": ["groceries"]}],
            "year": _YEAR,
        }
        before = {
            "targets": {"groceries": {"target": 500.25}},
            "groups": [{"name": "Essentials", "categories": ["groceries"]}],
            "year": _YEAR,
        }
        # Live state equals ``after`` but as nested Decimals — a top-level-only
        # _norm would spuriously 409 here on the non-integer target.
        svc = _NestedDecimalBudgetService(
            targets_data={"groceries": {"target": Decimal("720.5")}},
            groups_data=[{"name": "Essentials", "categories": ["groceries"]}],
        )
        result = revert_put_budget_config(_budget_entry(after, before), self._services(svc), False)
        assert "restored budget config" in result
        # The before document was re-put — the stale guard did not block it.
        assert [kind for kind, *_ in svc.puts] == ["targets", "groups"]

    def test_genuine_nested_mismatch_still_409s(self) -> None:
        after = {
            "targets": {"groceries": {"target": 720.5}},
            "groups": [{"name": "Essentials", "categories": ["groceries"]}],
            "year": _YEAR,
        }
        before = {
            "targets": {"groceries": {"target": 500.25}},
            "groups": [{"name": "Essentials", "categories": ["groceries"]}],
            "year": _YEAR,
        }
        # Live target moved on to a different value → genuinely stale.
        svc = _NestedDecimalBudgetService(
            targets_data={"groceries": {"target": Decimal("999.99")}},
            groups_data=[{"name": "Essentials", "categories": ["groceries"]}],
        )
        with pytest.raises(ApiException) as exc:
            revert_put_budget_config(_budget_entry(after, before), self._services(svc), False)
        assert (exc.value.status_code, exc.value.code) == (409, "stale_revert")
        assert svc.puts == []


# ---------------------------------------------------------------------------
# FIX 4 — honest 409 when a revert cannot restore a null prior value
# ---------------------------------------------------------------------------


class TestRevertUnsupportedNullRestore:
    def test_patch_revert_null_prior_category_is_409(self, env: Any) -> None:
        ft, dfn, tx_id = _seed_txn(env.txdb, file_name="nullcat.eml", category="dining")
        cur = env.txdb.get_item(ft, dfn)
        # Craft an entry whose edit populated a previously-empty category. after
        # mirrors the live state so the stale guard passes and we reach the axis.
        entry_id = env.store.record(
            {
                "operation_id": "patchTransaction",
                "method": "PATCH",
                "path": f"/api/v1/transactions/{tx_id}",
                "resource_id": tx_id,
                "reversible": True,
                "before_json": json.dumps(
                    {"Category": None, "Ignored": cur.get("Ignored"), "DeletedAt": cur.get("DeletedAt")}
                ),
                "after_json": json.dumps(
                    {"Category": cur.get("Category"), "Ignored": cur.get("Ignored"), "DeletedAt": cur.get("DeletedAt")}
                ),
            }
        )
        problem = assert_problem(_revert(env, entry_id), 409, "revert_unsupported")
        assert "no category" in problem["error"]
        # Untouched — the 409 fires before any axis is applied.
        assert env.txdb.get_item(ft, dfn)["Category"] == cur.get("Category")

    def test_fields_revert_null_prior_category_is_409(self, env: Any) -> None:
        ft, dfn, tx_id = _seed_txn(
            env.txdb, file_name="nullfields.eml", company="Store B", amount=30.0, category="dining"
        )
        cur = env.txdb.get_item(ft, dfn)
        entry_id = env.store.record(
            {
                "operation_id": "updateTransactionFields",
                "method": "PUT",
                "path": f"/api/v1/transactions/{tx_id}/fields",
                "resource_id": tx_id,
                "reversible": True,
                "before_json": json.dumps(
                    {
                        "company": cur.get("Company"),
                        "amount": float(cur["Amount"]),
                        "transaction_type": cur.get("TransactionType"),
                        "category": None,
                    }
                ),
                "after_json": json.dumps(
                    {
                        "company": cur.get("Company"),
                        "amount": float(cur["Amount"]),
                        "transaction_type": cur.get("TransactionType"),
                        "category": cur.get("Category"),
                    }
                ),
            }
        )
        problem = assert_problem(_revert(env, entry_id), 409, "revert_unsupported")
        assert "no category" in problem["error"]
        assert env.txdb.get_item(ft, dfn)["Category"] == cur.get("Category")

    def test_fields_revert_null_unchanged_axis_reverts_other_axes(self, env: Any) -> None:
        # category is None in BOTH images (unchanged) — must NOT 409 and must not
        # block reverting the changed company axis. force skips the stale guard so
        # this isolates the null-restore rule from the (live-category) stale check.
        ft, dfn, tx_id = _seed_txn(env.txdb, file_name="mixed.eml", company="Store B", amount=30.0, category="dining")
        cur = env.txdb.get_item(ft, dfn)
        entry_id = env.store.record(
            {
                "operation_id": "updateTransactionFields",
                "method": "PUT",
                "path": f"/api/v1/transactions/{tx_id}/fields",
                "resource_id": tx_id,
                "reversible": True,
                "before_json": json.dumps(
                    {
                        "company": "Store A",
                        "amount": float(cur["Amount"]),
                        "transaction_type": cur.get("TransactionType"),
                        "category": None,
                    }
                ),
                "after_json": json.dumps(
                    {
                        "company": cur.get("Company"),
                        "amount": float(cur["Amount"]),
                        "transaction_type": cur.get("TransactionType"),
                        "category": None,
                    }
                ),
            }
        )
        assert_ok(_revert(env, entry_id, force=True))
        restored = env.txdb.get_item(ft, dfn)
        assert restored["Company"] == "Store A"
        # category (None in both images) left as-is.
        assert restored["Category"] == cur.get("Category")
