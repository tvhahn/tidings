"""CSV formula-injection guard: export neutralizes, backup restore reverses it."""

from __future__ import annotations

import csv
import io
import zipfile
from decimal import Decimal

import pytest

from src.api.routers.tax import _line_csv
from src.finance import backup_export, backup_import
from src.finance.csv_safety import csv_safe_text, csv_unguard_text
from tests.factories import make_transaction_item

_TRICKY = [
    '=HYPERLINK("http://x","y")',
    "+15551234",
    "-2+3",
    "@SUM(A1:A2)",
    "\tcmd",
    "\rcmd",
    "'=already quoted",
    "''-twice quoted",
    "'plain quote",
    "plain",
    "",
    "a=b",
]


class TestGuardHelpers:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("=1+2", "'=1+2"),
            ("+1", "'+1"),
            ("-1", "'-1"),
            ("@x", "'@x"),
            ("\tx", "'\tx"),
            ("\rx", "'\rx"),
            ("'=x", "''=x"),
            ("'x", "'x"),
            ("x=1", "x=1"),
            ("", ""),
        ],
    )
    def test_csv_safe_text(self, value: str, expected: str) -> None:
        assert csv_safe_text(value) == expected

    @pytest.mark.parametrize("value", [None, 12.5, -3, Decimal("-4.20")])
    def test_non_strings_pass_through(self, value: object) -> None:
        assert csv_safe_text(value) is value

    @pytest.mark.parametrize("value", _TRICKY)
    def test_unguard_reverses_guard_exactly(self, value: str) -> None:
        assert csv_unguard_text(csv_safe_text(value)) == value


class TestTaxLineCsv:
    def test_company_neutralized_amount_untouched(self) -> None:
        text = _line_csv(
            [
                {
                    "date": "2026-02-15",
                    "company": "=cmd|' /C calc'!A0",
                    "amount": -12.5,
                    "category": "donations",
                    "evidence": "email",
                    "tx_id": "abc",
                }
            ]
        )
        rows = list(csv.reader(io.StringIO(text)))
        assert rows[1] == ["2026-02-15", "'=cmd|' /C calc'!A0", "-12.50", "donations", "email", "abc"]


class TestBackupRoundTrip:
    _TEXT_FIELDS = {
        "Company": "company",
        "Name": "name",
        "Comment": "comment",
        "Subject": "subject",
        "FromName": "from_name",
        "FromEmail": "from_email",
        "ToName": "to_name",
        "ToEmail": "to_email",
        "Body": "body",
    }

    @pytest.mark.parametrize("value", [v for v in _TRICKY if v])  # Company is required on import
    def test_backup_restores_original_text(self, value: str) -> None:
        item = make_transaction_item(**dict.fromkeys(self._TEXT_FIELDS, value), Amount=Decimal("-42.50"))
        payload = backup_export.build_backup_zip(
            transactions=[item],
            categories=None,
            overrides=None,
            merchant_aliases=None,
            budgets=None,
            storage_backend="sqlite",
        )

        csv_text = zipfile.ZipFile(io.BytesIO(payload)).read(backup_import.TRANSACTIONS_FILENAME).decode()
        exported = next(csv.DictReader(io.StringIO(csv_text)))
        assert exported["Amount"] == "-42.5"  # numeric column never guarded
        for col in self._TEXT_FIELDS:
            assert exported[col] == csv_safe_text(value)

        parsed = backup_import.parse_upload("backup.zip", payload, default_forwarded_to="user@example.com")
        assert parsed.invalid_rows == []
        row = parsed.transactions[0]
        assert row["amount"] == -42.5
        for key in self._TEXT_FIELDS.values():
            assert row[key] == value
