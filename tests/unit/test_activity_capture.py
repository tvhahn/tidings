"""Unit tests for the activity-ledger capture seam (Phase 3, src/api/activity.py).

Covers the pure predicate (:func:`should_capture`), the envelope assembly
(:func:`build_entry`) for both instrumented and uninstrumented writes, the
fail-open behavior of :func:`capture_activity`, and the fire-and-forget dispatch
draining a raising store without propagating (L3/L4/L7).

These tests never touch a real request path — they build minimal Starlette
requests so the predicate/envelope logic is exercised in isolation. End-to-end
capture through the middleware is covered in ``test_api_activity.py``.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.requests import Request

from src.api import activity as activity_module
from src.api.activity import (
    build_entry,
    capture_activity,
    drain_ledger_tasks,
    should_capture,
    stage_before,
)
from src.api.auth import Principal


def _make_request(
    method: str,
    path: str,
    *,
    operation_id: str | None = None,
    path_params: dict[str, Any] | None = None,
    principal: Principal | None = None,
) -> Request:
    """Build a minimal Starlette request with a resolved route + optional principal."""
    route = SimpleNamespace(operation_id=operation_id) if operation_id is not None else None
    scope: dict[str, Any] = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "route": route,
        "path_params": path_params or {},
    }
    request = Request(scope)
    if principal is not None:
        request.state.principal = principal
    return request


def _response(status_code: int) -> Any:
    return SimpleNamespace(status_code=status_code)


# ---------------------------------------------------------------------------
# should_capture — pure predicate (L4)
# ---------------------------------------------------------------------------


class TestShouldCapture:
    @pytest.mark.parametrize(
        ("method", "path", "operation_id", "status", "expected"),
        [
            # Read methods never captured.
            ("GET", "/api/v1/transactions", "listTransactions", 200, False),
            ("HEAD", "/api/v1/transactions", "listTransactions", 200, False),
            ("OPTIONS", "/api/v1/transactions", None, 200, False),
            # 2xx writes captured.
            ("POST", "/api/v1/transactions/bulk", "bulkUpdateTransactionCategory", 200, True),
            ("PUT", "/api/v1/overrides/foo", "putOverride", 200, True),
            ("PATCH", "/api/v1/transactions/abc", "patchTransaction", 201, True),
            ("DELETE", "/api/v1/overrides/foo", "deleteOverride", 204, True),
            # Non-2xx skipped: a failed write changed nothing; 3xx dodges the 308 double-fire.
            ("POST", "/api/v1/transactions/bulk", "bulkUpdateTransactionCategory", 422, False),
            ("POST", "/api/v1/transactions/bulk", "bulkUpdateTransactionCategory", 500, False),
            ("POST", "/api/v1/transactions/legacy", "patchTransaction", 308, False),
            # Auth-bootstrap prefix skipped.
            ("POST", "/api/v1/auth/login", "login", 200, False),
            # Non-API paths skipped.
            ("POST", "/not-api/thing", None, 200, False),
            # Exempt operation_ids skipped (all four members).
            ("POST", "/api/v1/config/test-openai", "testOpenAIKey", 200, False),
            ("POST", "/api/v1/transactions/search", "searchTransactionsByFilter", 200, False),
            ("GET", "/api/v1/data/export", "exportFullBackup", 200, False),
            ("POST", "/api/v1/data/import/preview", "previewBackupImport", 200, False),
            # A captured neighbor of an exempt op stays captured.
            ("POST", "/api/v1/data/import/commit", "commitBackupImport", 200, True),
        ],
    )
    def test_predicate(self, method: str, path: str, operation_id: str | None, status: int, expected: bool) -> None:
        request = _make_request(method, path, operation_id=operation_id)
        assert should_capture(request, _response(status)) is expected


# ---------------------------------------------------------------------------
# build_entry — envelope assembly (L3)
# ---------------------------------------------------------------------------


class TestBuildEntry:
    def test_uninstrumented_write_has_no_before_and_is_not_reversible(self) -> None:
        principal = Principal(kind="token", token_id="tok8", label="laptop", scope="read+write")
        request = _make_request(
            "PUT",
            "/api/v1/overrides/Costco",
            operation_id="putOverride",
            path_params={"company": "Costco"},
            principal=principal,
        )
        entry = build_entry(request, _response(200))

        assert entry["reversible"] is False
        assert entry["before_json"] is None
        assert entry["after_json"] is None
        assert entry["summary"] is None
        assert entry["principal_kind"] == "token"
        assert entry["principal_id"] == "tok8"
        assert entry["principal_label"] == "laptop"
        assert entry["operation_id"] == "putOverride"
        assert entry["method"] == "PUT"
        assert entry["path"] == "/api/v1/overrides/Costco"
        assert entry["resource_id"] == "Costco"

    def test_instrumented_write_carries_before_after_and_summary(self) -> None:
        request = _make_request(
            "PATCH",
            "/api/v1/transactions/xyz",
            operation_id="patchTransaction",
            path_params={"tx_id": "xyz"},
            principal=Principal(kind="tofu"),
        )
        stage_before(
            request,
            resource="transaction",
            before={"Category": "groceries"},
            after={"Category": "dining"},
            summary="updated transaction",
        )
        entry = build_entry(request, _response(200))

        assert entry["reversible"] is True
        assert entry["summary"] == "updated transaction"
        import json

        assert json.loads(entry["before_json"]) == {"Category": "groceries"}
        assert json.loads(entry["after_json"]) == {"Category": "dining"}
        # Non-token principal → null token fields.
        assert entry["principal_kind"] == "tofu"
        assert entry["principal_id"] is None

    def test_delete_shaped_after_is_none_but_reversible(self) -> None:
        request = _make_request(
            "DELETE",
            "/api/v1/overrides/Costco",
            operation_id="deleteOverride",
            path_params={"company": "Costco"},
        )
        stage_before(
            request,
            resource="override",
            before={"company": "Costco", "category": "groceries"},
            after=None,
            summary="removed category override for Costco",
        )
        entry = build_entry(request, _response(200))

        assert entry["reversible"] is True
        assert entry["after_json"] is None
        assert entry["before_json"] is not None

    def test_operation_id_falls_back_to_method_and_path(self) -> None:
        request = _make_request("POST", "/api/v1/mystery", operation_id=None)
        entry = build_entry(request, _response(200))
        assert entry["operation_id"] == "POST /api/v1/mystery"

    def test_resource_id_none_when_no_path_params(self) -> None:
        request = _make_request("POST", "/api/v1/transactions/bulk", operation_id="bulkUpdateTransactionCategory")
        entry = build_entry(request, _response(200))
        assert entry["resource_id"] is None


# ---------------------------------------------------------------------------
# capture_activity — fail-open (L7)
# ---------------------------------------------------------------------------


class TestCaptureFailOpen:
    def test_dispatch_failure_is_swallowed(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        def _boom(_store: Any, _entry: Any) -> None:
            raise RuntimeError("store exploded")

        monkeypatch.setattr(activity_module, "_dispatch_record", _boom)
        request = _make_request("PUT", "/api/v1/overrides/foo", operation_id="putOverride")

        with caplog.at_level(logging.WARNING, logger="src.api.activity"):
            # Must not raise even though dispatch blows up.
            capture_activity(request, _response(200))

        assert any("activity capture failed" in r.message for r in caplog.records)

    def test_non_capturable_request_is_a_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[Any] = []
        monkeypatch.setattr(activity_module, "_dispatch_record", lambda s, e: called.append(e))
        request = _make_request("GET", "/api/v1/transactions", operation_id="listTransactions")
        capture_activity(request, _response(200))
        assert called == []


# ---------------------------------------------------------------------------
# _dispatch_record + drain_ledger_tasks — real fire-and-forget path (L7)
# ---------------------------------------------------------------------------


class TestDispatchAndDrain:
    def test_dispatch_swallows_a_raising_store(self, caplog: pytest.LogCaptureFixture) -> None:
        class _RaisingStore:
            def record(self, entry: dict[str, Any]) -> str:
                raise RuntimeError("dynamodb down")

        async def driver() -> None:
            with caplog.at_level(logging.WARNING, logger="src.api.activity"):
                activity_module._dispatch_record(_RaisingStore(), {"operation_id": "x"})
                # Strong ref held so the bare task can't be GC'd mid-flight.
                assert len(activity_module._LEDGER_TASKS) == 1
                await drain_ledger_tasks()
                await asyncio.sleep(0)  # let done-callbacks run
            # Drained + discarded; the raising store never propagated.
            assert len(activity_module._LEDGER_TASKS) == 0
            assert any("activity ledger write failed" in r.message for r in caplog.records)

        asyncio.run(driver())

    def test_dispatch_records_a_healthy_store(self) -> None:
        class _RecordingStore:
            def __init__(self) -> None:
                self.entries: list[dict[str, Any]] = []

            def record(self, entry: dict[str, Any]) -> str:
                self.entries.append(entry)
                return "id1"

        store = _RecordingStore()

        async def driver() -> None:
            activity_module._dispatch_record(store, {"operation_id": "putOverride"})
            await drain_ledger_tasks()

        asyncio.run(driver())
        assert store.entries == [{"operation_id": "putOverride"}]
