"""Attachments API — upload, list, download, link, delete, and demo gating."""

from __future__ import annotations

import io
import json
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from src.finance.tx_id import tx_id_from_composite
from tests.asserts import assert_ok, assert_problem, assert_status
from tests.factories import make_transaction_item

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.testclient import TestClient

FORWARDED_TO = "user@example.com"
DATE_FILE_NAME = "2026.02.15_10.30_test.eml"
TX_ID = tx_id_from_composite(FORWARDED_TO, DATE_FILE_NAME)


@pytest.fixture(autouse=True)
def _isolate_attachment_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Any]:
    """Redirect the AttachmentStore singleton + raw dir to a per-test tmp path.

    Mirrors ``_isolate_statement_store`` (tests/unit/conftest.py): without it the
    pytest guard fires on the default ``data/attachments.db`` path and uploads
    would write real files into the working tree.
    """
    import src.api.dependencies as deps
    import src.api.routers.attachments as attachments_router
    from src.finance import app_config
    from src.finance.attachment_store import AttachmentStore

    tmp_store = AttachmentStore(db_path=tmp_path / "attachments.db")
    tmp_raw = tmp_path / "raw" / "attachments"
    monkeypatch.setattr(deps, "_attachment_store", tmp_store)
    monkeypatch.setattr(attachments_router, "ATTACHMENTS_RAW_DIR", tmp_raw)
    # Non-demo tests must not inherit a developer machine's demo_mode:true config;
    # the demo-gate tests opt back in via _force_demo (which replaces get_config).
    # Likewise pin the receipt-parse consent OFF so a host data/config.json with
    # ai_receipt_parsing_enabled:true can't leak in and defuse the consent-off
    # test; consent-on tests opt in explicitly via _enable_receipt_parsing.
    non_demo_cfg = dict(app_config.get_config())
    non_demo_cfg["demo_mode"] = False
    non_demo_cfg["ai_receipt_parsing_enabled"] = False
    monkeypatch.setattr(app_config, "_cache", non_demo_cfg)
    return tmp_store


def _force_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.finance.app_config as app_config

    monkeypatch.setattr(
        app_config,
        "get_config",
        lambda: {"user_id": "default", "storage": "sqlite", "demo_mode": True},
    )


def _jpeg_bytes(color: tuple[int, int, int] = (200, 30, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (12, 12), color).save(buffer, format="JPEG")
    return buffer.getvalue()


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (12, 12), (10, 120, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


class TestUpload:
    def test_upload_unlinked(self, api_client: TestClient, _isolate_attachment_store: Any) -> None:
        resp = api_client.post(
            "/api/v1/attachments",
            files={"file": ("receipt.jpg", _jpeg_bytes(), "image/jpeg")},
        )
        body = assert_ok(resp)
        assert body["tx_id"] is None
        assert body["content_type"] == "image/jpeg"
        assert body["kind"] == "receipt"

        row = _isolate_attachment_store.get_attachment(body["id"])
        assert row is not None
        assert row["forwarded_to"] is None
        assert Path(row["file_path"]).is_file()

    def test_upload_with_tx_id_links(self, api_client: TestClient, _isolate_attachment_store: Any) -> None:
        resp = api_client.post(
            "/api/v1/attachments",
            files={"file": ("receipt.jpg", _jpeg_bytes(), "image/jpeg")},
            data={"tx_id": TX_ID},
        )
        body = assert_ok(resp)
        assert body["tx_id"] == TX_ID
        row = _isolate_attachment_store.get_attachment(body["id"])
        assert row["forwarded_to"] == FORWARDED_TO
        assert row["date_file_name"] == DATE_FILE_NAME

    def test_upload_document_kind(self, api_client: TestClient) -> None:
        resp = api_client.post(
            "/api/v1/attachments",
            files={"file": ("invoice.pdf", b"%PDF-1.4 x", "application/pdf")},
            data={"kind": "document"},
        )
        body = assert_ok(resp)
        assert body["kind"] == "document"
        assert body["content_type"] == "application/pdf"

    def test_reject_oversize(self, api_client: TestClient) -> None:
        big = b"\x00" * (11 * 1024 * 1024)
        resp = api_client.post(
            "/api/v1/attachments",
            files={"file": ("big.pdf", big, "application/pdf")},
        )
        assert_problem(resp, 400)

    def test_reject_disallowed_extension(self, api_client: TestClient) -> None:
        resp = api_client.post(
            "/api/v1/attachments",
            files={"file": ("malware.exe", b"MZ\x90", "application/octet-stream")},
        )
        assert_problem(resp, 400)

    def test_reject_content_type_extension_mismatch(self, api_client: TestClient) -> None:
        resp = api_client.post(
            "/api/v1/attachments",
            files={"file": ("receipt.png", _png_bytes(), "application/pdf")},
        )
        assert_problem(resp, 400)

    def test_reject_bad_kind(self, api_client: TestClient) -> None:
        resp = api_client.post(
            "/api/v1/attachments",
            files={"file": ("receipt.jpg", _jpeg_bytes(), "image/jpeg")},
            data={"kind": "banana"},
        )
        assert_problem(resp, 400)

    def test_upload_bad_tx_id_404(self, api_client: TestClient) -> None:
        resp = api_client.post(
            "/api/v1/attachments",
            files={"file": ("receipt.jpg", _jpeg_bytes(), "image/jpeg")},
            data={"tx_id": "!!!not-valid!!!"},
        )
        assert_problem(resp, 404)

    def test_heic_stored_as_jpeg(self, api_client: TestClient, _isolate_attachment_store: Any) -> None:
        try:
            buffer = io.BytesIO()
            Image.new("RGB", (16, 16), (40, 60, 200)).save(buffer, format="HEIF")
            heic = buffer.getvalue()
        except Exception:
            pytest.skip("HEIC/HEIF encoding not available in this build")
        resp = api_client.post(
            "/api/v1/attachments",
            files={"file": ("receipt.heic", heic, "image/heic")},
        )
        body = assert_ok(resp)
        assert body["content_type"] == "image/jpeg"
        assert body["original_filename"] == "receipt.heic"


class TestListAndDownload:
    def test_list_and_filters(self, api_client: TestClient) -> None:
        api_client.post(
            "/api/v1/attachments",
            files={"file": ("a.jpg", _jpeg_bytes((1, 2, 3)), "image/jpeg")},
        )
        api_client.post(
            "/api/v1/attachments",
            files={"file": ("b.pdf", b"%PDF-1.4 y", "application/pdf")},
            data={"kind": "document", "tx_id": TX_ID},
        )
        all_body = assert_ok(api_client.get("/api/v1/attachments"))
        assert all_body["count"] == 2

        unlinked = assert_ok(api_client.get("/api/v1/attachments?unlinked=true"))
        assert unlinked["count"] == 1
        assert unlinked["attachments"][0]["kind"] == "receipt"

        docs = assert_ok(api_client.get("/api/v1/attachments?kind=document"))
        assert docs["count"] == 1

    def test_list_for_transaction(self, api_client: TestClient) -> None:
        api_client.post(
            "/api/v1/attachments",
            files={"file": ("a.jpg", _jpeg_bytes(), "image/jpeg")},
            data={"tx_id": TX_ID},
        )
        body = assert_ok(api_client.get(f"/api/v1/transactions/{TX_ID}/attachments"))
        assert body["count"] == 1
        assert body["attachments"][0]["tx_id"] == TX_ID

    def test_download_inline(self, api_client: TestClient) -> None:
        content = _jpeg_bytes((9, 9, 9))
        up = assert_ok(
            api_client.post(
                "/api/v1/attachments",
                files={"file": ("receipt.jpg", content, "image/jpeg")},
            )
        )
        resp = api_client.get(f"/api/v1/attachments/{up['id']}/file")
        assert_status(resp, 200)
        assert resp.content == content
        assert resp.headers["content-type"].startswith("image/jpeg")
        assert "inline" in resp.headers["content-disposition"]

    def test_download_unknown_404(self, api_client: TestClient) -> None:
        assert_problem(api_client.get("/api/v1/attachments/att_missing/file"), 404)


class TestLink:
    def test_link_then_unlink(self, api_client: TestClient) -> None:
        up = assert_ok(
            api_client.post(
                "/api/v1/attachments",
                files={"file": ("receipt.jpg", _jpeg_bytes(), "image/jpeg")},
            )
        )
        linked = assert_ok(api_client.post(f"/api/v1/attachments/{up['id']}/link", json={"tx_id": TX_ID}))
        assert linked["tx_id"] == TX_ID

        unlinked = assert_ok(api_client.post(f"/api/v1/attachments/{up['id']}/link", json={"tx_id": None}))
        assert unlinked["tx_id"] is None

    def test_link_bad_tx_id_404(self, api_client: TestClient) -> None:
        up = assert_ok(
            api_client.post(
                "/api/v1/attachments",
                files={"file": ("receipt.jpg", _jpeg_bytes(), "image/jpeg")},
            )
        )
        assert_problem(
            api_client.post(f"/api/v1/attachments/{up['id']}/link", json={"tx_id": "!!!bad!!!"}),
            404,
        )

    def test_link_unknown_attachment_404(self, api_client: TestClient) -> None:
        assert_problem(
            api_client.post("/api/v1/attachments/att_missing/link", json={"tx_id": None}),
            404,
        )


class TestDelete:
    def test_delete_removes_disk_file(self, api_client: TestClient, _isolate_attachment_store: Any) -> None:
        up = assert_ok(
            api_client.post(
                "/api/v1/attachments",
                files={"file": ("receipt.jpg", _jpeg_bytes(), "image/jpeg")},
            )
        )
        file_path = Path(_isolate_attachment_store.get_attachment(up["id"])["file_path"])
        assert file_path.is_file()

        body = assert_ok(api_client.delete(f"/api/v1/attachments/{up['id']}"))
        assert body["status"] == "deleted"
        assert not file_path.exists()
        assert _isolate_attachment_store.get_attachment(up["id"]) is None

    def test_delete_unknown_404(self, api_client: TestClient) -> None:
        assert_problem(api_client.delete("/api/v1/attachments/att_missing"), 404)


def _enable_receipt_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn the consent on for the router's ``app_config.get_config`` read."""
    import src.finance.app_config as app_config

    monkeypatch.setattr(
        app_config,
        "get_config",
        lambda: {"demo_mode": False, "ai_receipt_parsing_enabled": True},
    )


def _upload_receipt(api_client: TestClient) -> str:
    body = assert_ok(
        api_client.post(
            "/api/v1/attachments",
            files={"file": ("receipt.jpg", _jpeg_bytes(), "image/jpeg")},
        )
    )
    return body["id"]


class _FakeSummary:
    def __init__(self, items_by_month: dict[str, list[dict[str, Any]]]) -> None:
        self._m = items_by_month

    def query_month(self, year_month: str, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self._m.get(year_month, [])


class _FakeAliasService:
    def get_aliases_map(self) -> dict[str, str]:
        return {}


def _override_matcher_deps(items_by_month: dict[str, list[dict[str, Any]]]) -> None:
    from src.api.dependencies import get_merchant_alias_service, get_spending_summary
    from src.api.main import app

    app.dependency_overrides[get_spending_summary] = lambda: _FakeSummary(items_by_month)
    app.dependency_overrides[get_merchant_alias_service] = lambda: _FakeAliasService()


class TestParseReceipt:
    def test_consent_off_returns_422_with_settings_hint(self, api_client: TestClient) -> None:
        att_id = _upload_receipt(api_client)
        resp = api_client.post(f"/api/v1/attachments/{att_id}/parse")
        body = assert_problem(resp, 422)
        assert "Settings" in body["error"]
        assert "Intelligence" in body["error"]

    def test_parse_success_persists_parsed_and_json(
        self, api_client: TestClient, _isolate_attachment_store: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enable_receipt_parsing(monkeypatch)
        att_id = _upload_receipt(api_client)
        parsed = {
            "merchant": "Booster Juice",
            "date": "2026-02-15",
            "total": 42.50,
            "provenance": {"method": "ai_receipt", "provider": "codex", "model": "codex", "schema_version": 1},
        }
        with patch(
            "src.api.routers.attachments.parse_receipt",
            new=AsyncMock(return_value=parsed),
        ):
            body = assert_ok(api_client.post(f"/api/v1/attachments/{att_id}/parse"))
        assert body["parse_status"] == "parsed"
        assert body["parse_json"]["merchant"] == "Booster Juice"
        row = _isolate_attachment_store.get_attachment(att_id)
        assert row["parse_status"] == "parsed"
        assert json.loads(row["parse_json"])["total"] == 42.50

    def test_parse_failure_persists_failed_and_422(
        self, api_client: TestClient, _isolate_attachment_store: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.finance.receipt_parser_ai import ReceiptAIError

        _enable_receipt_parsing(monkeypatch)
        att_id = _upload_receipt(api_client)
        with patch(
            "src.api.routers.attachments.parse_receipt",
            new=AsyncMock(side_effect=ReceiptAIError("The receipt total does not appear")),
        ):
            resp = api_client.post(f"/api/v1/attachments/{att_id}/parse")
        assert_problem(resp, 422)
        row = _isolate_attachment_store.get_attachment(att_id)
        assert row["parse_status"] == "failed"
        assert "does not appear" in row["parse_error"]

    def test_parse_blocked_in_demo(self, api_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _force_demo(monkeypatch)
        assert_problem(api_client.post("/api/v1/attachments/att_x/parse"), 403)


class TestReceiptCandidates:
    def _mark_parsed(self, store: Any, att_id: str) -> None:
        store.set_parse_result(
            att_id,
            status="parsed",
            parse_json=json.dumps({"merchant": "Booster Juice", "date": "2026-02-15", "total": 42.50}),
            error=None,
        )

    def test_candidates_on_unparsed_returns_409(self, api_client: TestClient) -> None:
        att_id = _upload_receipt(api_client)
        assert_problem(api_client.get(f"/api/v1/attachments/{att_id}/candidates"), 409)

    def test_single_t1_unlinked_signals_auto_link_without_writing(
        self, api_client: TestClient, _isolate_attachment_store: Any
    ) -> None:
        att_id = _upload_receipt(api_client)
        self._mark_parsed(_isolate_attachment_store, att_id)
        item = make_transaction_item(
            DateFileName="2026.02.15_10.30_a.eml",
            Amount=Decimal("42.50"),
            Company="Booster Juice",
        )
        _override_matcher_deps({"2026-02": [item]})
        body = assert_ok(api_client.get(f"/api/v1/attachments/{att_id}/candidates"))
        assert body["auto_link_candidate"] is True
        assert body["candidates"][0]["tier"] == 1
        # The GET is pure — it signals the client should link but performs no write.
        row = _isolate_attachment_store.get_attachment(att_id)
        assert row["forwarded_to"] is None
        assert row["date_file_name"] is None

    def test_single_t1_signal_stable_across_repeat_gets(
        self, api_client: TestClient, _isolate_attachment_store: Any
    ) -> None:
        # Because the GET never links, the signal stays true on every call — a
        # read-scope token polling this endpoint can never mutate state.
        att_id = _upload_receipt(api_client)
        self._mark_parsed(_isolate_attachment_store, att_id)
        item = make_transaction_item(
            DateFileName="2026.02.15_10.30_a.eml",
            Amount=Decimal("42.50"),
            Company="Booster Juice",
        )
        _override_matcher_deps({"2026-02": [item]})
        for _ in range(2):
            body = assert_ok(api_client.get(f"/api/v1/attachments/{att_id}/candidates"))
            assert body["auto_link_candidate"] is True
        assert _isolate_attachment_store.get_attachment(att_id)["date_file_name"] is None

    def test_two_t1s_no_signal_both_returned(self, api_client: TestClient, _isolate_attachment_store: Any) -> None:
        att_id = _upload_receipt(api_client)
        self._mark_parsed(_isolate_attachment_store, att_id)
        items = [
            make_transaction_item(
                DateFileName="2026.02.15_10.30_a.eml", Amount=Decimal("42.50"), Company="Booster Juice"
            ),
            make_transaction_item(
                DateFileName="2026.02.15_18.00_b.eml", Amount=Decimal("42.50"), Company="Booster Juice"
            ),
        ]
        _override_matcher_deps({"2026-02": items})
        body = assert_ok(api_client.get(f"/api/v1/attachments/{att_id}/candidates"))
        assert body["auto_link_candidate"] is False
        assert len(body["candidates"]) == 2
        assert all(c["tier"] == 1 for c in body["candidates"])
        # No link was performed.
        row = _isolate_attachment_store.get_attachment(att_id)
        assert row["date_file_name"] is None

    def test_candidates_pure_in_demo_mode(
        self, api_client: TestClient, _isolate_attachment_store: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The GET carries no ensure_not_demo guard because it is pure — it must
        # return 200 in demo mode and leave the (demo) row unwritten.
        att_id = _upload_receipt(api_client)
        self._mark_parsed(_isolate_attachment_store, att_id)
        item = make_transaction_item(
            DateFileName="2026.02.15_10.30_a.eml",
            Amount=Decimal("42.50"),
            Company="Booster Juice",
        )
        _override_matcher_deps({"2026-02": [item]})
        _force_demo(monkeypatch)
        body = assert_ok(api_client.get(f"/api/v1/attachments/{att_id}/candidates"))
        assert body["auto_link_candidate"] is True
        row = _isolate_attachment_store.get_attachment(att_id)
        assert row["forwarded_to"] is None
        assert row["date_file_name"] is None


class TestDemoGuard:
    def test_upload_blocked_in_demo(self, api_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _force_demo(monkeypatch)
        resp = api_client.post(
            "/api/v1/attachments",
            files={"file": ("receipt.jpg", _jpeg_bytes(), "image/jpeg")},
        )
        assert_problem(resp, 403)

    def test_link_blocked_in_demo(self, api_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _force_demo(monkeypatch)
        resp = api_client.post("/api/v1/attachments/att_x/link", json={"tx_id": None})
        assert_problem(resp, 403)

    def test_delete_blocked_in_demo(self, api_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _force_demo(monkeypatch)
        assert_problem(api_client.delete("/api/v1/attachments/att_x"), 403)
