"""TaxPackService — case-insensitive bucketing, evidence classification, seed loading."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

import src.finance.config_loader as config_module
from src.finance.config_loader import get_tax_line_mappings
from src.finance.tax_pack_service import TaxPackService
from src.finance.tx_id import composite_from_tx_id
from tests.factories import make_transaction_item

if TYPE_CHECKING:
    from pathlib import Path

YEAR = 2026

# The seven L12 lines in seed order, with the verbatim label/cra_ref strings.
SEED_LINES = [
    ("charitable", "Charitable donations", "Line 34900 (Schedule 9)"),
    ("medical", "Medical expenses", "Line 33099"),
    ("childcare", "Child care expenses", "Line 21400 (Form T778)"),
    ("moving", "Moving expenses", "Line 21900"),
    ("tuition", "Tuition and education", "Line 32300"),
    ("dues", "Union and professional dues", "Line 21200"),
    ("instalments", "Tax paid by instalments", "Line 47600"),
]


class FakeSummary:
    """query_month stub returning canned items per YYYY-MM month."""

    def __init__(self, items_by_month: dict[str, list[dict[str, Any]]]) -> None:
        self._months = items_by_month

    def query_month(self, year_month: str, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self._months.get(year_month, [])


class FakeAttachmentStore:
    """has_receipt stub over a fixed set of receipt-linked composites."""

    def __init__(self, receipt_keys: set[tuple[str, str]] | None = None) -> None:
        self.receipt_keys = receipt_keys or set()
        self.calls: list[set[tuple[str, str]]] = []

    def has_receipt(self, keys: set[tuple[str, str]]) -> set[tuple[str, str]]:
        self.calls.append(set(keys))
        return keys & self.receipt_keys


class FakeOverrideStore:
    """list_all stub over a fixed override map keyed by composite."""

    def __init__(self, overrides: dict[tuple[str, str], dict[str, str | None]] | None = None) -> None:
        self.overrides = overrides or {}

    def list_all(self) -> dict[tuple[str, str], dict[str, str | None]]:
        return dict(self.overrides)


def _service(
    items_by_month: dict[str, list[dict[str, Any]]],
    receipt_keys: set[tuple[str, str]] | None = None,
    overrides: dict[tuple[str, str], dict[str, str | None]] | None = None,
) -> TaxPackService:
    return TaxPackService(
        FakeSummary(items_by_month),
        FakeAttachmentStore(receipt_keys),
        FakeOverrideStore(overrides),
    )


def _line(pack: dict[str, Any], key: str) -> dict[str, Any]:
    return next(line for line in pack["lines"] if line["key"] == key)


class TestSeedLoader:
    def test_seed_lines_verbatim(self) -> None:
        """The packaged seed carries the L12 keys/labels/cra_refs verbatim, in order."""
        mapping = get_tax_line_mappings()
        assert mapping["version"] == 1
        assert mapping["country"] == "CA"
        assert [(line["key"], line["label"], line["cra_ref"]) for line in mapping["lines"]] == SEED_LINES
        medical = next(line for line in mapping["lines"] if line["key"] == "medical")
        assert medical["note"] == (
            "Only amounts not reimbursed by insurance qualify; "
            "a claim may use any 12-month period ending in the tax year."
        )
        assert medical["categories"] == ["Health Care", "Therapy"]

    def test_duplicate_category_across_lines_raises(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """A category claimed by two lines is a seed error — fail at load, loudly."""
        bad_seed = {
            "version": 1,
            "country": "CA",
            "lines": [
                {"key": "a", "label": "A", "cra_ref": "Line 1", "categories": ["Taxes"]},
                {"key": "b", "label": "B", "cra_ref": "Line 2", "categories": ["taxes"]},
            ],
        }
        (tmp_path / "tax_line_mappings.json").write_text(json.dumps(bad_seed))
        monkeypatch.setattr(config_module, "_PERSONAL_DIR", tmp_path)
        config_module._simple_caches.clear()
        with pytest.raises(ValueError, match="two lines"):
            get_tax_line_mappings()

    def test_personal_config_overrides_packaged_seed(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """A user copy in data/config/ wins over the tracked seed (two-tier read)."""
        personal_seed = {
            "version": 1,
            "country": "CA",
            "lines": [
                {"key": "custom", "label": "Custom line", "cra_ref": "Line 99999", "categories": ["Groceries"]},
            ],
        }
        (tmp_path / "tax_line_mappings.json").write_text(json.dumps(personal_seed))
        monkeypatch.setattr(config_module, "_PERSONAL_DIR", tmp_path)
        config_module._simple_caches.clear()

        item = make_transaction_item(Category="groceries")
        pack = _service({"2026-02": [item]}).get_tax_pack(YEAR)

        assert [line["key"] for line in pack["lines"]] == ["custom"]
        assert pack["lines"][0]["label"] == "Custom line"
        assert pack["lines"][0]["total"] == 42.50


class TestBucketing:
    def test_lowercase_rows_bucket_into_title_case_lines(self) -> None:
        """THE CASE TRAP: stored rows carry lowercase categories, the seed is display case."""
        items = [
            make_transaction_item(Category="charitable giving", Amount=Decimal("100.00")),
            make_transaction_item(
                Category="charitable giving",
                Amount=Decimal("25.50"),
                DateFileName="2026.02.16_09.00_b.eml",
            ),
        ]
        pack = _service({"2026-02": items}).get_tax_pack(YEAR)

        charitable = _line(pack, "charitable")
        assert charitable["total"] == 125.50
        assert charitable["transaction_count"] == 2
        assert pack["grand_total"] == 125.50

    def test_deleted_ignored_and_deposit_rows_excluded(self) -> None:
        items = [
            make_transaction_item(Category="charitable giving", DeletedAt="2026-03-01T00:00:00Z"),
            make_transaction_item(Category="charitable giving", Ignored=True, DateFileName="2026.02.16_09.00_b.eml"),
            make_transaction_item(
                Category="charitable giving",
                TransactionType="deposit",
                DateFileName="2026.02.17_09.00_c.eml",
            ),
        ]
        pack = _service({"2026-02": items}).get_tax_pack(YEAR)

        charitable = _line(pack, "charitable")
        assert charitable["total"] == 0
        assert charitable["transactions"] == []
        assert pack["grand_total"] == 0

    def test_unmapped_categories_absent_and_grand_total_sums_lines(self) -> None:
        items = [
            make_transaction_item(Category="groceries", Amount=Decimal("300.00")),
            make_transaction_item(Category="childcare", Amount=Decimal("80.00"), DateFileName="2026.03.02_09.00_b.eml"),
            make_transaction_item(Category="taxes", Amount=Decimal("1200.00"), DateFileName="2026.04.02_09.00_c.eml"),
        ]
        pack = _service({"2026-02": [items[0]], "2026-03": [items[1]], "2026-04": [items[2]]}).get_tax_pack(YEAR)

        all_companies = [t["company"] for line in pack["lines"] for t in line["transactions"]]
        assert len(all_companies) == 2  # the groceries row appears nowhere
        assert _line(pack, "childcare")["total"] == 80.00
        assert _line(pack, "instalments")["total"] == 1200.00
        assert pack["grand_total"] == sum(line["total"] for line in pack["lines"])
        assert pack["grand_total"] == 1280.00

    def test_medical_line_combines_health_care_and_therapy(self) -> None:
        items = [
            make_transaction_item(Category="health care", Amount=Decimal("60.00")),
            make_transaction_item(Category="therapy", Amount=Decimal("140.00"), DateFileName="2026.02.20_09.00_b.eml"),
        ]
        pack = _service({"2026-02": items}).get_tax_pack(YEAR)

        medical = _line(pack, "medical")
        assert medical["total"] == 200.00
        assert medical["transaction_count"] == 2
        assert medical["categories"] == ["Health Care", "Therapy"]

    def test_zero_claimables_year_keeps_all_lines(self) -> None:
        pack = _service({}).get_tax_pack(YEAR)

        assert pack["year"] == YEAR
        assert pack["grand_total"] == 0
        assert [line["key"] for line in pack["lines"]] == [key for key, _, _ in SEED_LINES]
        for line in pack["lines"]:
            assert line["total"] == 0
            assert line["transaction_count"] == 0
            assert line["transactions"] == []
            assert line["evidence_counts"] == {"receipt": 0, "email": 0, "statement": 0}


class TestEvidence:
    def test_evidence_classification_and_counts_sum(self) -> None:
        receipt_item = make_transaction_item(
            Category="health care", DateFileName="2026.02.10_09.00_a.eml", Amount=Decimal("10.00")
        )
        statement_item = make_transaction_item(
            Category="health care",
            DateFileName="2026.02.11_09.00_b.eml",
            Amount=Decimal("20.00"),
            StatementSource="RBC-chequing-2026-02",
        )
        email_item = make_transaction_item(
            Category="therapy", DateFileName="2026.02.12_09.00_c.eml", Amount=Decimal("30.00")
        )
        receipt_keys = {("user@example.com", "2026.02.10_09.00_a.eml")}
        pack = _service({"2026-02": [receipt_item, statement_item, email_item]}, receipt_keys).get_tax_pack(YEAR)

        medical = _line(pack, "medical")
        by_date = {t["date"]: t["evidence"] for t in medical["transactions"]}
        assert by_date == {"2026-02-10": "receipt", "2026-02-11": "statement", "2026-02-12": "email"}
        assert medical["evidence_counts"] == {"receipt": 1, "statement": 1, "email": 1}
        assert sum(medical["evidence_counts"].values()) == medical["transaction_count"]

    def test_has_receipt_called_once_with_all_claimable_keys(self) -> None:
        """The evidence probe is bulk — one call per pack, never per row."""
        store = FakeAttachmentStore()
        items = [
            make_transaction_item(Category="childcare", DateFileName="2026.02.10_09.00_a.eml"),
            make_transaction_item(Category="education", DateFileName="2026.05.10_09.00_b.eml"),
        ]
        TaxPackService(
            FakeSummary({"2026-02": [items[0]], "2026-05": [items[1]]}),
            store,
            FakeOverrideStore(),
        ).get_tax_pack(YEAR)

        assert len(store.calls) == 1
        assert store.calls[0] == {
            ("user@example.com", "2026.02.10_09.00_a.eml"),
            ("user@example.com", "2026.05.10_09.00_b.eml"),
        }


class TestOverrides:
    def test_include_forces_unmapped_row_into_mapped_line(self) -> None:
        """An include override lands an otherwise-unmapped row in the chosen line, marked manual."""
        item = make_transaction_item(
            Category="groceries",
            Amount=Decimal("75.00"),
            DateFileName="2026.02.10_09.00_a.eml",
        )
        overrides = {("user@example.com", "2026.02.10_09.00_a.eml"): {"mode": "include", "line_key": "medical"}}
        pack = _service({"2026-02": [item]}, overrides=overrides).get_tax_pack(YEAR)

        medical = _line(pack, "medical")
        assert medical["total"] == 75.00
        assert medical["transaction_count"] == 1
        txn = medical["transactions"][0]
        assert txn["manual"] is True
        assert txn["forwarded_to"] == "user@example.com"
        assert txn["date_file_name"] == "2026.02.10_09.00_a.eml"
        assert txn["category"] == "groceries"

    def test_include_into_other_appends_synthetic_line(self) -> None:
        """Include targeting 'other' (and an unknown key falling back to it) renders the synthetic line."""
        known = make_transaction_item(
            Category="groceries", Amount=Decimal("10.00"), DateFileName="2026.02.10_09.00_a.eml"
        )
        unknown = make_transaction_item(
            Category="dining", Amount=Decimal("5.00"), DateFileName="2026.03.10_09.00_b.eml"
        )
        overrides = {
            ("user@example.com", "2026.02.10_09.00_a.eml"): {"mode": "include", "line_key": "other"},
            ("user@example.com", "2026.03.10_09.00_b.eml"): {"mode": "include", "line_key": "nonsense"},
        }
        pack = _service(
            {"2026-02": [known], "2026-03": [unknown]},
            overrides=overrides,
        ).get_tax_pack(YEAR)

        other = _line(pack, "other")
        assert other["label"] == "Other claimable"
        assert other["cra_ref"] is None
        assert other["total"] == 15.00
        assert other["transaction_count"] == 2
        assert all(t["manual"] is True for t in other["transactions"])
        # "other" is appended after the seven seed lines.
        assert [line["key"] for line in pack["lines"]][-1] == "other"

    def test_exclude_moves_derived_row_out_of_total(self) -> None:
        """An exclude override drops a derived row into excluded_transactions, uncounted."""
        kept = make_transaction_item(
            Category="charitable giving", Amount=Decimal("100.00"), DateFileName="2026.02.10_09.00_a.eml"
        )
        excluded = make_transaction_item(
            Category="charitable giving", Amount=Decimal("40.00"), DateFileName="2026.02.11_09.00_b.eml"
        )
        overrides = {("user@example.com", "2026.02.11_09.00_b.eml"): {"mode": "exclude", "line_key": None}}
        pack = _service({"2026-02": [kept, excluded]}, overrides=overrides).get_tax_pack(YEAR)

        charitable = _line(pack, "charitable")
        assert charitable["total"] == 100.00
        assert charitable["transaction_count"] == 1
        assert charitable["evidence_counts"] == {"receipt": 0, "email": 1, "statement": 0}
        assert [t["date_file_name"] for t in charitable["excluded_transactions"]] == ["2026.02.11_09.00_b.eml"]
        assert pack["grand_total"] == 100.00

    def test_exclude_of_unmapped_row_drops_it_entirely(self) -> None:
        """Excluding a row with no derived line drops it — it appears nowhere."""
        item = make_transaction_item(
            Category="groceries", Amount=Decimal("50.00"), DateFileName="2026.02.10_09.00_a.eml"
        )
        overrides = {("user@example.com", "2026.02.10_09.00_a.eml"): {"mode": "exclude", "line_key": None}}
        pack = _service({"2026-02": [item]}, overrides=overrides).get_tax_pack(YEAR)

        assert all(not line["transactions"] and not line["excluded_transactions"] for line in pack["lines"])
        assert "other" not in [line["key"] for line in pack["lines"]]
        assert pack["grand_total"] == 0

    def test_other_line_absent_without_members(self) -> None:
        """With no include-to-other overrides, the synthetic line never renders."""
        pack = _service({}).get_tax_pack(YEAR)
        assert "other" not in [line["key"] for line in pack["lines"]]

    def test_derived_rows_are_not_manual(self) -> None:
        """A plain derived membership carries manual=False."""
        item = make_transaction_item(Category="charitable giving", DateFileName="2026.02.10_09.00_a.eml")
        pack = _service({"2026-02": [item]}).get_tax_pack(YEAR)
        txn = _line(pack, "charitable")["transactions"][0]
        assert txn["manual"] is False
        assert txn["forwarded_to"] == "user@example.com"
        assert txn["date_file_name"] == "2026.02.10_09.00_a.eml"


class TestEvidenceBodies:
    def test_with_evidence_returns_email_bodies_and_pack_stays_clean(self) -> None:
        """get_tax_pack_with_evidence exposes active email bodies; the pack never carries them."""
        email_item = make_transaction_item(
            Category="charitable giving",
            DateFileName="2026.02.10_09.00_a.eml",
            Body="Your donation of $42.50 was received.",
        )
        receipt_item = make_transaction_item(
            Category="charitable giving",
            DateFileName="2026.02.11_09.00_b.eml",
            Body="receipt-row body that must not surface as email evidence",
        )
        receipt_keys = {("user@example.com", "2026.02.11_09.00_b.eml")}
        svc = _service({"2026-02": [email_item, receipt_item]}, receipt_keys)

        pack, bodies = svc.get_tax_pack_with_evidence(YEAR)

        # Only the email-evidence row's body is exposed, keyed by composite.
        assert bodies == {("user@example.com", "2026.02.10_09.00_a.eml"): "Your donation of $42.50 was received."}

        # The pack matches get_tax_pack exactly and never leaks a Body field.
        assert pack == svc.get_tax_pack(YEAR)
        for line in pack["lines"]:
            for txn in line["transactions"]:
                assert "Body" not in txn
                assert "body" not in txn

    def test_with_evidence_excludes_statement_and_excluded_rows(self) -> None:
        """Only active email rows contribute bodies — statement rows and excluded rows do not."""
        statement_item = make_transaction_item(
            Category="charitable giving",
            DateFileName="2026.02.10_09.00_a.eml",
            Body="statement body",
            StatementSource="RBC-2026-02",
        )
        excluded_item = make_transaction_item(
            Category="charitable giving",
            DateFileName="2026.02.11_09.00_b.eml",
            Body="excluded body",
        )
        overrides = {("user@example.com", "2026.02.11_09.00_b.eml"): {"mode": "exclude", "line_key": None}}
        svc = _service({"2026-02": [statement_item, excluded_item]}, overrides=overrides)

        _pack, bodies = svc.get_tax_pack_with_evidence(YEAR)
        assert bodies == {}


class TestTransactionShape:
    def test_tx_id_roundtrips_and_date_is_normalized(self) -> None:
        item = make_transaction_item(Category="moving", DateFileName="2026.07.04_10.30_move.eml")
        pack = _service({"2026-07": [item]}).get_tax_pack(YEAR)

        txn = _line(pack, "moving")["transactions"][0]
        assert txn["date"] == "2026-07-04"
        assert txn["company"] == "Test Store"
        assert txn["amount"] == 42.50
        assert txn["category"] == "moving"
        assert composite_from_tx_id(txn["tx_id"]) == ("user@example.com", "2026.07.04_10.30_move.eml")

    def test_transactions_sorted_chronologically(self) -> None:
        items = [
            make_transaction_item(Category="education", DateFileName="2026.09.15_09.00_b.eml"),
            make_transaction_item(Category="education", DateFileName="2026.09.01_09.00_a.eml"),
        ]
        pack = _service({"2026-09": items}).get_tax_pack(YEAR)

        dates = [t["date"] for t in _line(pack, "tuition")["transactions"]]
        assert dates == ["2026-09-01", "2026-09-15"]
