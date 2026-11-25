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
    account_event_key,
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
    assert window_bounds("2026.04.20_03.29_abc.eml") == ("2026.04.19_21.29", "2026.04.20_03.29~")
    assert "2026.04.20_12.29_zzz" < "2026.04.20_12.29~"


def test_window_bounds_reach_back_to_the_start_of_the_day() -> None:
    """The account-event rule compares whole days, so the window never starts mid-day."""
    assert window_bounds("2026.04.20_12.29_abc.eml") == ("2026.04.20_00.00", "2026.04.20_12.29~")


def test_window_bounds_reject_a_key_without_a_minute() -> None:
    assert window_bounds("manual_entry") is None


class TestAccountEvent:
    """One card payment alerted to each cardholder on the account (issue #98)."""

    @staticmethod
    def _payment(key: str, **overrides: object) -> dict[str, object]:
        item: dict[str, object] = {
            "DateFileName": key,
            "TransactionHash": f"hash-{key}",
            "Institution": "MBNA",
            "Amount": Decimal("500.00"),
            "Company": "Payment",
            "TransactionType": "card-payment",
            "Body": f"Payment received for the card ending in {key[-4:]}.",
        }
        item.update(overrides)
        return item

    def test_second_cardholder_copy_is_marked(self) -> None:
        first = self._payment("2026.10.02_08.15_a_1111")
        second = self._payment("2026.10.02_08.16_b_2222")
        rows = [alert_row(first), alert_row(second)]
        assert find_duplicate_marks("2026.10.02_08.16_b_2222", rows) == {
            "2026.10.02_08.16_b_2222": "2026.10.02_08.15_a_1111"
        }

    def test_copy_later_the_same_day_is_marked(self) -> None:
        """Copies are compared by day, beyond the six-hour re-send window."""
        first = self._payment("2026.10.02_01.00_a_1111")
        second = self._payment("2026.10.02_19.00_b_2222")
        assert find_duplicate_marks(second["DateFileName"], [alert_row(first), alert_row(second)]) == {
            "2026.10.02_19.00_b_2222": "2026.10.02_01.00_a_1111"
        }

    def test_same_amount_on_another_day_is_kept(self) -> None:
        first = self._payment("2026.10.02_08.15_a_1111")
        second = self._payment("2026.10.03_08.15_b_2222")
        assert find_duplicate_marks(second["DateFileName"], [alert_row(first), alert_row(second)]) == {}

    @pytest.mark.parametrize(
        "change",
        [{"Amount": Decimal("250.00")}, {"Institution": "RBC"}],
    )
    def test_different_payment_is_kept(self, change: dict[str, object]) -> None:
        first = self._payment("2026.10.02_08.15_a_1111")
        second = self._payment("2026.10.02_08.16_b_2222", **change)
        assert find_duplicate_marks(second["DateFileName"], [alert_row(first), alert_row(second)]) == {}

    def test_purchases_on_two_cards_are_never_collapsed(self) -> None:
        """Two cardholders can really spend the same amount on the same day."""
        first = self._payment("2026.10.02_08.15_a_1111", TransactionType="purchase")
        second = self._payment("2026.10.02_08.16_b_2222", TransactionType="purchase")
        assert account_event_key(first) is None
        assert find_duplicate_marks(second["DateFileName"], [alert_row(first), alert_row(second)]) == {}

    def test_statement_and_manual_rows_never_take_part(self) -> None:
        assert alert_row(self._payment("2026.10.02_08.15_a_1111", StatementSource="s3://x")).account_event is None
        assert account_event_key(self._payment("2026.10.02_08.15_a_1111", Body=None)) is None

    def test_earlier_copy_is_never_re_hidden(self) -> None:
        """Only the newly written row is marked, so a restored original stays visible."""
        first = self._payment("2026.10.02_08.15_a_1111")
        second = self._payment("2026.10.02_08.16_b_2222")
        assert find_duplicate_marks(first["DateFileName"], [alert_row(first), alert_row(second)]) == {}
