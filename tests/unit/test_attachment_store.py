"""Tests for AttachmentStore — SQLite persistence for receipts and documents."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from src.finance.attachment_store import AttachmentStore, attachment_id_for

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def store(tmp_path: Path) -> AttachmentStore:
    return AttachmentStore(db_path=tmp_path / "attachments.db")


def _meta(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "original_filename": "receipt.jpg",
        "content_type": "image/jpeg",
        "size_bytes": 1234,
        "sha256": "a" * 64,
        "file_path": "data/raw/attachments/2026-07/att_x_receipt.jpg",
        "kind": "receipt",
    }
    base.update(overrides)
    return base


class TestUpsert:
    def test_same_bytes_and_name_same_id_one_row(self, store: AttachmentStore) -> None:
        id1 = store.save_attachment(_meta())
        id2 = store.save_attachment(_meta(size_bytes=9999))  # same sha + name
        assert id1 == id2
        assert len(store.list_attachments()) == 1

    def test_changed_filename_new_id(self, store: AttachmentStore) -> None:
        id1 = store.save_attachment(_meta(original_filename="a.jpg"))
        id2 = store.save_attachment(_meta(original_filename="b.jpg"))
        assert id1 != id2
        assert len(store.list_attachments()) == 2

    def test_id_matches_module_helper(self, store: AttachmentStore) -> None:
        att_id = store.save_attachment(_meta())
        assert att_id == attachment_id_for("a" * 64, "receipt.jpg")

    def test_upsert_preserves_created_at(self, store: AttachmentStore) -> None:
        att_id = store.save_attachment(_meta())
        created = store.get_attachment(att_id)["created_at"]  # type: ignore[index]
        store.save_attachment(_meta(size_bytes=5))
        row = store.get_attachment(att_id)
        assert row is not None
        assert row["created_at"] == created
        assert row["size_bytes"] == 5

    def test_plain_insert_defaults(self, store: AttachmentStore) -> None:
        """A first upload of a new id lands with the documented defaults."""
        att_id = store.save_attachment(_meta())
        row = store.get_attachment(att_id)
        assert row is not None
        assert row["kind"] == "receipt"
        assert row["forwarded_to"] is None
        assert row["date_file_name"] is None
        assert row["parse_status"] == "none"
        assert row["parse_json"] is None
        assert row["parse_error"] is None

    def test_reupload_without_link_preserves_link_and_parse(self, store: AttachmentStore) -> None:
        """Re-uploading the identical file (as the router does — no parse fields,
        no link) must NOT wipe an existing link or a completed AI parse."""
        att_id = store.save_attachment(_meta())
        store.set_link(att_id, "user@example.com", "2026.07.09_10.00_x.eml")
        store.set_parse_result(att_id, status="parsed", parse_json='{"total": 42}', error=None)

        # Router-shaped re-upload: link keys are None, no parse_* keys present.
        store.save_attachment(_meta(forwarded_to=None, date_file_name=None, size_bytes=777))

        row = store.get_attachment(att_id)
        assert row is not None
        # File metadata refreshed...
        assert row["size_bytes"] == 777
        # ...but the link and parse state survive.
        assert row["forwarded_to"] == "user@example.com"
        assert row["date_file_name"] == "2026.07.09_10.00_x.eml"
        assert row["parse_status"] == "parsed"
        assert row["parse_json"] == '{"total": 42}'
        assert row["parse_error"] is None

    def test_reupload_with_explicit_link_updates_link(self, store: AttachmentStore) -> None:
        """An upload carrying a tx link (non-None) links/relinks on re-upload."""
        att_id = store.save_attachment(_meta())
        store.set_link(att_id, "old@example.com", "2026.07.09_10.00_old.eml")

        store.save_attachment(_meta(forwarded_to="new@example.com", date_file_name="2026.07.10_11.00_new.eml"))

        row = store.get_attachment(att_id)
        assert row is not None
        assert row["forwarded_to"] == "new@example.com"
        assert row["date_file_name"] == "2026.07.10_11.00_new.eml"


class TestLinking:
    def test_link_unlink_round_trip(self, store: AttachmentStore) -> None:
        att_id = store.save_attachment(_meta())
        assert store.set_link(att_id, "user@example.com", "2026.07.09_10.00_x.eml") is True
        row = store.get_attachment(att_id)
        assert row is not None
        assert row["forwarded_to"] == "user@example.com"
        assert row["date_file_name"] == "2026.07.09_10.00_x.eml"

        assert store.set_link(att_id, None, None) is True
        row = store.get_attachment(att_id)
        assert row is not None
        assert row["forwarded_to"] is None
        assert row["date_file_name"] is None

    def test_set_link_unknown_id_returns_false(self, store: AttachmentStore) -> None:
        assert store.set_link("att_missing", "a@b.com", "x.eml") is False

    def test_list_unlinked_excludes_linked(self, store: AttachmentStore) -> None:
        linked = store.save_attachment(_meta(original_filename="linked.jpg"))
        unlinked = store.save_attachment(_meta(original_filename="unfiled.jpg"))
        store.set_link(linked, "user@example.com", "2026.07.09_10.00_x.eml")

        unlinked_rows = store.list_attachments(unlinked=True)
        assert [r["id"] for r in unlinked_rows] == [unlinked]

        linked_rows = store.list_attachments(unlinked=False)
        assert [r["id"] for r in linked_rows] == [linked]

    def test_list_filters_by_kind(self, store: AttachmentStore) -> None:
        store.save_attachment(_meta(original_filename="r.jpg", kind="receipt"))
        store.save_attachment(_meta(original_filename="d.pdf", kind="document"))
        receipts = store.list_attachments(kind="receipt")
        assert [r["kind"] for r in receipts] == ["receipt"]


class TestListForTransaction:
    def test_returns_only_that_composite(self, store: AttachmentStore) -> None:
        a = store.save_attachment(_meta(original_filename="a.jpg"))
        b = store.save_attachment(_meta(original_filename="b.jpg"))
        store.set_link(a, "user@example.com", "2026.07.09_10.00_a.eml")
        store.set_link(b, "user@example.com", "2026.07.09_11.00_b.eml")

        rows = store.list_for_transaction("user@example.com", "2026.07.09_10.00_a.eml")
        assert [r["id"] for r in rows] == [a]


class TestHasReceipt:
    def test_returns_exactly_present_keys(self, store: AttachmentStore) -> None:
        r = store.save_attachment(_meta(original_filename="r.jpg", kind="receipt"))
        d = store.save_attachment(_meta(original_filename="d.pdf", kind="document"))
        store.set_link(r, "user@example.com", "2026.07.09_10.00_r.eml")
        store.set_link(d, "user@example.com", "2026.07.09_11.00_d.eml")

        keys = {
            ("user@example.com", "2026.07.09_10.00_r.eml"),  # receipt hit
            ("user@example.com", "2026.07.09_11.00_d.eml"),  # document — not a receipt
            ("user@example.com", "2026.07.09_12.00_none.eml"),  # miss
        }
        assert store.has_receipt(keys) == {("user@example.com", "2026.07.09_10.00_r.eml")}

    def test_empty_input_returns_empty(self, store: AttachmentStore) -> None:
        assert store.has_receipt(set()) == set()


class TestDelete:
    def test_returns_row_then_none(self, store: AttachmentStore) -> None:
        att_id = store.save_attachment(_meta())
        row = store.delete_attachment(att_id)
        assert row is not None
        assert row["id"] == att_id
        assert row["file_path"] == _meta()["file_path"]
        assert store.delete_attachment(att_id) is None


class TestParseResult:
    def test_set_parse_result_round_trip(self, store: AttachmentStore) -> None:
        att_id = store.save_attachment(_meta())
        assert store.set_parse_result(att_id, status="parsed", parse_json='{"total": 1}', error=None) is True
        row = store.get_attachment(att_id)
        assert row is not None
        assert row["parse_status"] == "parsed"
        assert row["parse_json"] == '{"total": 1}'

    def test_set_parse_result_unknown_id_returns_false(self, store: AttachmentStore) -> None:
        assert store.set_parse_result("att_missing", status="failed", parse_json=None, error="x") is False


class TestBootstrap:
    def test_ensure_db_idempotent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "attachments.db"
        first = AttachmentStore(db_path=db_path)
        first.save_attachment(_meta())
        # Constructing again against the same path re-runs _ensure_db without loss.
        second = AttachmentStore(db_path=db_path)
        assert len(second.list_attachments()) == 1

    def test_pytest_guard_rejects_default_path(self) -> None:
        with pytest.raises(RuntimeError, match="tmp db_path under pytest"):
            AttachmentStore()
