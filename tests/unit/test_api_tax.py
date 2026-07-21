"""Tax pack API — pack shape, export zip contents, demo gating, year validation."""

from __future__ import annotations

import io
import zipfile
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from src.finance.tx_id import composite_from_tx_id, tx_id_from_composite
from tests.asserts import assert_ok, assert_problem, assert_status
from tests.factories import make_transaction_item

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from fastapi.testclient import TestClient

    from src.finance.attachment_store import AttachmentStore

FORWARDED_TO = "user@example.com"

# Three claimable rows for 2026: a receipt-linked donation, a statement-imported
# donation, and an email-evidence health-care charge.
RECEIPT_DFN = "2026.03.10_10.30_donation.eml"
STATEMENT_DFN = "2026.03.20_12.00_stmt_donation.eml"
EMAIL_DFN = "2026.04.05_09.15_pharmacy.eml"

EMAIL_BODY = "Your purchase of $55.00 at Shoppers Drug Mart was approved."


class _FakeSummary:
    def __init__(self, items_by_month: dict[str, list[dict[str, Any]]]) -> None:
        self._months = items_by_month

    def query_month(self, year_month: str, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self._months.get(year_month, [])


class _FakeDB:
    def __init__(self, items: dict[tuple[str, str], dict[str, Any]]) -> None:
        self._items = items
        self.get_item_calls: list[tuple[str, str]] = []

    def get_item(self, forwarded_to: str, date_file_name: str) -> dict[str, Any] | None:
        self.get_item_calls.append((forwarded_to, date_file_name))
        return self._items.get((forwarded_to, date_file_name))


def _year_items() -> dict[str, list[dict[str, Any]]]:
    receipt_row = make_transaction_item(
        DateFileName=RECEIPT_DFN,
        Amount=Decimal("100.00"),
        Company="United Way",
        Category="charitable giving",
    )
    statement_row = make_transaction_item(
        DateFileName=STATEMENT_DFN,
        Amount=Decimal("40.00"),
        Company="Red Cross",
        Category="charitable giving",
        StatementSource="RBC-chequing-2026-03",
    )
    email_row = make_transaction_item(
        DateFileName=EMAIL_DFN,
        Amount=Decimal("55.00"),
        Company="Shoppers Drug Mart",
        Category="health care",
        Body=EMAIL_BODY,
    )
    return {"2026-03": [receipt_row, statement_row], "2026-04": [email_row]}


@pytest.fixture(autouse=True)
def _isolate_tax_deps(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[AttachmentStore]:
    """Override the tax router's deps: tmp AttachmentStore, canned summary + db.

    Also pins ``demo_mode: False`` so a developer machine's real config can't
    flip the demo gate; the demo test opts back in via ``_force_demo``.
    """
    from src.api.dependencies import get_attachment_store, get_spending_summary, get_transactions_db
    from src.api.main import app
    from src.finance import app_config
    from src.finance.attachment_store import AttachmentStore

    store = AttachmentStore(db_path=tmp_path / "attachments.db")
    items = _year_items()
    all_items = {(FORWARDED_TO, i["DateFileName"]): i for month in items.values() for i in month}

    app.dependency_overrides[get_attachment_store] = lambda: store
    app.dependency_overrides[get_spending_summary] = lambda: _FakeSummary(items)
    app.dependency_overrides[get_transactions_db] = lambda: _FakeDB(all_items)

    non_demo_cfg = dict(app_config.get_config())
    non_demo_cfg["demo_mode"] = False
    monkeypatch.setattr(app_config, "_cache", non_demo_cfg)
    yield store
    app.dependency_overrides.clear()


def _link_receipt(store: AttachmentStore, tmp_path: Path) -> str:
    """Save a receipt file on disk + a linked receipt-kind row; returns the id."""
    file_path = tmp_path / "donation-receipt.jpg"
    file_path.write_bytes(b"\xff\xd8\xff fake jpeg bytes")
    return store.save_attachment(
        {
            "original_filename": "donation-receipt.jpg",
            "content_type": "image/jpeg",
            "size_bytes": file_path.stat().st_size,
            "sha256": "deadbeef" * 8,
            "file_path": str(file_path),
            "kind": "receipt",
            "forwarded_to": FORWARDED_TO,
            "date_file_name": RECEIPT_DFN,
        }
    )


def _force_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.finance.app_config as app_config

    monkeypatch.setattr(
        app_config,
        "get_config",
        lambda: {"user_id": "default", "storage": "sqlite", "demo_mode": True},
    )


class TestGetTaxPack:
    def test_pack_shape_and_tx_id_roundtrip(
        self, api_client: TestClient, _isolate_tax_deps: AttachmentStore, tmp_path: Path
    ) -> None:
        _link_receipt(_isolate_tax_deps, tmp_path)
        body = assert_ok(api_client.get("/api/v1/tax-pack?year=2026"))

        assert body["year"] == 2026
        assert [line["key"] for line in body["lines"]] == [
            "charitable",
            "medical",
            "childcare",
            "moving",
            "tuition",
            "dues",
            "instalments",
        ]
        assert body["grand_total"] == 195.00

        charitable = next(line for line in body["lines"] if line["key"] == "charitable")
        assert charitable["label"] == "Charitable donations"
        assert charitable["cra_ref"] == "Line 34900 (Schedule 9)"
        assert charitable["total"] == 140.00
        assert charitable["evidence_counts"] == {"receipt": 1, "email": 0, "statement": 1}
        receipt_txn = next(t for t in charitable["transactions"] if t["evidence"] == "receipt")
        assert receipt_txn["date"] == "2026-03-10"
        # tx_id round-trips through composite_from_tx_id back to the storage composite.
        assert composite_from_tx_id(receipt_txn["tx_id"]) == (FORWARDED_TO, RECEIPT_DFN)
        assert receipt_txn["tx_id"] == tx_id_from_composite(FORWARDED_TO, RECEIPT_DFN)

        medical = next(line for line in body["lines"] if line["key"] == "medical")
        assert medical["note"]
        assert "12-month period" in medical["note"]
        assert medical["transactions"][0]["evidence"] == "email"

    def test_bad_year_below_range_422(self, api_client: TestClient) -> None:
        assert_problem(api_client.get("/api/v1/tax-pack?year=1999"), 422)

    def test_non_numeric_year_422(self, api_client: TestClient) -> None:
        assert_problem(api_client.get("/api/v1/tax-pack?year=abc"), 422)

    def test_missing_year_422(self, api_client: TestClient) -> None:
        assert_problem(api_client.get("/api/v1/tax-pack"), 422)


class TestExportTaxPack:
    def test_export_zip_contents(
        self, api_client: TestClient, _isolate_tax_deps: AttachmentStore, tmp_path: Path
    ) -> None:
        attachment_id = _link_receipt(_isolate_tax_deps, tmp_path)
        resp = api_client.get("/api/v1/tax-pack/export?year=2026")
        assert_status(resp, 200)
        assert resp.headers["content-type"] == "application/zip"
        assert 'filename="tax-pack-2026.zip"' in resp.headers["content-disposition"]

        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        names = zf.namelist()

        assert "summary.csv" in names
        assert "lines/charitable.csv" in names
        assert "lines/medical.csv" in names

        # The receipt-linked row's file lands under evidence/<key>/ with the
        # date, sanitized company slug, and 8-char attachment id.
        id8 = attachment_id.removeprefix("att_")[:8]
        receipt_name = f"evidence/charitable/2026-03-10_United_Way_{id8}.jpg"
        assert receipt_name in names
        assert zf.read(receipt_name) == b"\xff\xd8\xff fake jpeg bytes"

        # The email-evidence row's body ships as a .txt under emails/.
        email_names = [n for n in names if n.startswith("evidence/medical/emails/") and n.endswith(".txt")]
        assert len(email_names) == 1
        assert "Shoppers_Drug_Mart" in email_names[0]
        assert zf.read(email_names[0]).decode() == EMAIL_BODY

        # Statement-evidence rows produce no email file (no source email exists).
        assert not any(n.startswith("evidence/charitable/emails/") for n in names)

        # The per-line CSV carries the exact columns from the plan.
        charitable_csv = zf.read("lines/charitable.csv").decode()
        header, *rows = [line for line in charitable_csv.splitlines() if line]
        assert header == "date,company,amount,category,evidence,tx_id"
        assert len(rows) == 2
        assert rows[0].startswith("2026-03-10,United Way,100.00,charitable giving,receipt,")

    def test_export_does_not_refetch_email_bodies_per_row(
        self, api_client: TestClient, _isolate_tax_deps: AttachmentStore
    ) -> None:
        """The export reuses bodies from the pack build — no per-row db.get_item.

        The email body still lands in the zip; it just arrives via the in-memory
        map the service already read, not a second round-trip per email row.
        """
        from src.api.dependencies import get_transactions_db
        from src.api.main import app

        spy_db = _FakeDB({(FORWARDED_TO, EMAIL_DFN): {"Body": "should not be read"}})
        app.dependency_overrides[get_transactions_db] = lambda: spy_db

        resp = api_client.get("/api/v1/tax-pack/export?year=2026")
        assert_status(resp, 200)

        # No per-email-row refetch happened.
        assert spy_db.get_item_calls == []

        # The email evidence is still present, sourced from the pack build.
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        email_names = [n for n in zf.namelist() if n.startswith("evidence/medical/emails/") and n.endswith(".txt")]
        assert len(email_names) == 1
        assert zf.read(email_names[0]).decode() == EMAIL_BODY

    def test_summary_csv_has_no_cra_ref_column(
        self, api_client: TestClient, _isolate_tax_deps: AttachmentStore, tmp_path: Path
    ) -> None:
        resp = api_client.get("/api/v1/tax-pack/export?year=2026")
        assert_status(resp, 200)
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        header = zf.read("summary.csv").decode().splitlines()[0]
        assert "cra_ref" not in header
        assert header == "line,label,total,transaction_count,receipts,emails,statements,note"

    def test_export_demo_mode_403(self, api_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _force_demo(monkeypatch)
        assert_problem(api_client.get("/api/v1/tax-pack/export?year=2026"), 403)

    def test_export_bad_year_422(self, api_client: TestClient) -> None:
        assert_problem(api_client.get("/api/v1/tax-pack/export?year=3000"), 422)


class TestTaxLines:
    def test_lines_include_seed_and_other(self, api_client: TestClient) -> None:
        body = assert_ok(api_client.get("/api/v1/tax-pack/lines"))
        keys = [opt["key"] for opt in body["lines"]]
        assert keys == ["charitable", "medical", "childcare", "moving", "tuition", "dues", "instalments", "other"]
        other = next(opt for opt in body["lines"] if opt["key"] == "other")
        assert other["label"] == "Other claimable"


class TestTaxOverrides:
    def test_include_moves_row_into_chosen_line(self, api_client: TestClient) -> None:
        """POST include reassigns the email health-care row from medical to childcare."""
        tx_id = tx_id_from_composite(FORWARDED_TO, EMAIL_DFN)
        resp = api_client.post(
            "/api/v1/tax-pack/items",
            json={"tx_id": tx_id, "mode": "include", "line_key": "childcare"},
        )
        assert_status(resp, 204)

        body = assert_ok(api_client.get("/api/v1/tax-pack?year=2026"))
        medical = next(line for line in body["lines"] if line["key"] == "medical")
        childcare = next(line for line in body["lines"] if line["key"] == "childcare")
        assert medical["total"] == 0
        assert childcare["total"] == 55.00
        moved = childcare["transactions"][0]
        assert moved["manual"] is True
        assert moved["date_file_name"] == EMAIL_DFN
        assert body["grand_total"] == 195.00

    def test_exclude_drops_row_from_total(self, api_client: TestClient) -> None:
        """POST exclude on the statement donation moves it to excluded_transactions."""
        tx_id = tx_id_from_composite(FORWARDED_TO, STATEMENT_DFN)
        resp = api_client.post(
            "/api/v1/tax-pack/items",
            json={"tx_id": tx_id, "mode": "exclude"},
        )
        assert_status(resp, 204)

        body = assert_ok(api_client.get("/api/v1/tax-pack?year=2026"))
        charitable = next(line for line in body["lines"] if line["key"] == "charitable")
        assert charitable["total"] == 100.00
        assert charitable["transaction_count"] == 1
        assert [t["date_file_name"] for t in charitable["excluded_transactions"]] == [STATEMENT_DFN]
        assert body["grand_total"] == 155.00

    def test_include_without_line_key_422(self, api_client: TestClient) -> None:
        tx_id = tx_id_from_composite(FORWARDED_TO, EMAIL_DFN)
        assert_problem(
            api_client.post("/api/v1/tax-pack/items", json={"tx_id": tx_id, "mode": "include"}),
            422,
        )

    def test_include_with_unknown_line_key_422(self, api_client: TestClient) -> None:
        tx_id = tx_id_from_composite(FORWARDED_TO, EMAIL_DFN)
        assert_problem(
            api_client.post(
                "/api/v1/tax-pack/items",
                json={"tx_id": tx_id, "mode": "include", "line_key": "nonsense"},
            ),
            422,
        )

    def test_delete_clears_override(self, api_client: TestClient) -> None:
        """After clearing an exclude, the row is counted again (derived)."""
        tx_id = tx_id_from_composite(FORWARDED_TO, STATEMENT_DFN)
        assert_status(api_client.post("/api/v1/tax-pack/items", json={"tx_id": tx_id, "mode": "exclude"}), 204)
        assert_status(api_client.delete(f"/api/v1/tax-pack/items/{tx_id}"), 204)

        body = assert_ok(api_client.get("/api/v1/tax-pack?year=2026"))
        charitable = next(line for line in body["lines"] if line["key"] == "charitable")
        assert charitable["total"] == 140.00
        assert charitable["excluded_transactions"] == []

    def test_post_demo_mode_403(self, api_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _force_demo(monkeypatch)
        tx_id = tx_id_from_composite(FORWARDED_TO, EMAIL_DFN)
        assert_problem(
            api_client.post("/api/v1/tax-pack/items", json={"tx_id": tx_id, "mode": "exclude"}),
            403,
        )

    def test_delete_demo_mode_403(self, api_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _force_demo(monkeypatch)
        tx_id = tx_id_from_composite(FORWARDED_TO, EMAIL_DFN)
        assert_problem(api_client.delete(f"/api/v1/tax-pack/items/{tx_id}"), 403)
