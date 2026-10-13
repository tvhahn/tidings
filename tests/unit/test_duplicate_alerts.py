"""Duplicate bank-alert decision rules (issue #86) — pure logic, no storage.

Storage-level behavior (both backends really marking rows) lives in
``TestTransactionsDBContract`` in ``test_dual_backend_contract.py``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.finance.duplicate_alerts import (
    RESEND_WINDOW,
    AlertRow,
    alert_fingerprint,
    alert_row,
    find_duplicate_marks,
    window_bounds,
)

BODY = "You've recently made a purchase with your card ending in [XXXX] for $4.50 at [MERCHANT]."


def _row(
    key: str,
    *,
    transaction_hash: str | None = None,
    fingerprint: str | None = None,
    deleted: bool = False,
    duplicate_of: str | None = None,
) -> AlertRow:
    return AlertRow(
        date_file_name=key,
        transaction_hash=transaction_hash,
        fingerprint=fingerprint,
        deleted=deleted,
        duplicate_of=duplicate_of,
    )


class TestSameHash:
    """One email written twice — two writers racing past the pre-write check."""

    def test_later_key_is_marked_when_it_is_the_new_row(self) -> None:
        rows = [_row("2026.09.26_10.27_a", transaction_hash="h"), _row("2026.09.26_10.27_b", transaction_hash="h")]
        assert find_duplicate_marks("2026.09.26_10.27_b", rows) == {"2026.09.26_10.27_b": "2026.09.26_10.27_a"}

    def test_writer_of_the_original_marks_the_racer(self) -> None:
        """The race resolves whichever writer reads last: here the original's writer."""
        rows = [_row("2026.09.26_10.27_a", transaction_hash="h"), _row("2026.09.26_10.27_b", transaction_hash="h")]
        assert find_duplicate_marks("2026.09.26_10.27_a", rows) == {"2026.09.26_10.27_b": "2026.09.26_10.27_a"}

    def test_already_marked_copy_is_left_alone(self) -> None:
        """A copy carrying DuplicateOf — e.g. one the user restored — is never re-hidden."""
        rows = [
            _row("2026.09.26_10.27_a", transaction_hash="h"),
            _row("2026.09.26_10.27_b", transaction_hash="h", duplicate_of="2026.09.26_10.27_a"),
        ]
        assert find_duplicate_marks("2026.09.26_10.27_a", rows) == {}

    def test_deleted_original_does_not_hide_the_copy(self) -> None:
        rows = [
            _row("2026.09.26_10.27_a", transaction_hash="h", deleted=True),
            _row("2026.09.26_10.27_b", transaction_hash="h"),
        ]
        assert find_duplicate_marks("2026.09.26_10.27_b", rows) == {}


class TestResend:
    """The bank sends the same alert again minutes or hours later."""

    def test_identical_alert_within_window_marks_the_new_row(self) -> None:
        rows = [_row("2026.04.20_08.57_a", fingerprint="f"), _row("2026.04.20_12.29_b", fingerprint="f")]
        assert find_duplicate_marks("2026.04.20_12.29_b", rows) == {"2026.04.20_12.29_b": "2026.04.20_08.57_a"}

    def test_identical_alert_the_next_day_is_a_new_purchase(self) -> None:
        """Alert text has no date: the same coffee tomorrow must stay a transaction."""
        rows = [_row("2026.04.20_08.00_a", fingerprint="f"), _row("2026.04.21_07.55_b", fingerprint="f")]
        assert find_duplicate_marks("2026.04.21_07.55_b", rows) == {}

    def test_window_edge_is_inclusive(self) -> None:
        later = f"2026.04.20_{8 + int(RESEND_WINDOW.total_seconds() // 3600):02d}.00_b"
        rows = [_row("2026.04.20_08.00_a", fingerprint="f"), _row(later, fingerprint="f")]
        assert find_duplicate_marks(later, rows) == {later: "2026.04.20_08.00_a"}

    def test_a_late_arriving_earlier_copy_never_hides_the_stored_one(self) -> None:
        """Only the new row is marked by the re-send rule — an existing row the
        user may have restored is never re-hidden."""
        rows = [_row("2026.04.20_08.57_a", fingerprint="f"), _row("2026.04.20_12.29_b", fingerprint="f")]
        assert find_duplicate_marks("2026.04.20_08.57_a", rows) == {}

    def test_third_copy_points_at_the_original_not_the_second(self) -> None:
        rows = [
            _row("2025.05.20_07.33_a", fingerprint="f"),
            _row("2025.05.20_09.25_b", fingerprint="f", duplicate_of="2025.05.20_07.33_a"),
            _row("2025.05.20_10.08_c", fingerprint="f"),
        ]
        assert find_duplicate_marks("2025.05.20_10.08_c", rows) == {"2025.05.20_10.08_c": "2025.05.20_07.33_a"}

    def test_different_text_is_not_a_resend(self) -> None:
        rows = [_row("2026.04.20_08.57_a", fingerprint="f"), _row("2026.04.20_09.00_b", fingerprint="g")]
        assert find_duplicate_marks("2026.04.20_09.00_b", rows) == {}

    def test_rows_without_a_body_never_match(self) -> None:
        rows = [_row("2026.04.20_08.57_a"), _row("2026.04.20_09.00_b")]
        assert find_duplicate_marks("2026.04.20_09.00_b", rows) == {}


def test_missing_new_row_marks_nothing() -> None:
    assert find_duplicate_marks("2026.04.20_09.00_b", [_row("2026.04.20_08.57_a", fingerprint="f")]) == {}


class TestFingerprint:
    def _item(self, **overrides: object) -> dict[str, object]:
        item: dict[str, object] = {
            "Body": BODY,
            "Institution": "CIBC",
            "Amount": Decimal("4.50"),
            "Company": "[MERCHANT]",
            "TransactionType": "purchase",
        }
        item.update(overrides)
        return item

    def test_whitespace_differences_do_not_split_one_alert(self) -> None:
        assert alert_fingerprint(self._item()) == alert_fingerprint(self._item(Body=BODY.replace(" ", "\n  ")))

    def test_amount_type_does_not_matter(self) -> None:
        """DynamoDB stores Decimal, SQLite float — the same alert must match."""
        assert alert_fingerprint(self._item()) == alert_fingerprint(self._item(Amount=4.5))

    @pytest.mark.parametrize(
        "change",
        [{"Amount": Decimal("4.51")}, {"Company": "Other"}, {"TransactionType": "credit"}, {"Institution": "RBC"}],
    )
    def test_parsed_fields_take_part(self, change: dict[str, object]) -> None:
        assert alert_fingerprint(self._item()) != alert_fingerprint(self._item(**change))

    def test_no_body_has_no_fingerprint(self) -> None:
        assert alert_fingerprint(self._item(Body="")) is None

    def test_statement_rows_never_take_part(self) -> None:
        row = alert_row({**self._item(), "DateFileName": "2026.04.20_08.57_a", "StatementSource": "RBC_Chequing"})
        assert row.fingerprint is None


def test_window_bounds_cover_the_window_and_the_whole_minute() -> None:
    assert window_bounds("2026.04.20_12.29_abc.eml") == ("2026.04.20_06.29", "2026.04.20_12.29~")
    assert "2026.04.20_12.29_zzz" < "2026.04.20_12.29~"


def test_window_bounds_reject_a_key_without_a_minute() -> None:
    assert window_bounds("manual_entry") is None
