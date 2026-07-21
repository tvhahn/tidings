"""Tests for the monthly-summary Lambda handler."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_COMPARISON_DATA = {
    "current": {
        "year_month": "2026-01",
        "total_spending": Decimal("2500.00"),
        "spending_count": 30,
        "deposit_total": Decimal("100.00"),
        "deposit_count": 2,
        "by_category": {},
        "by_company": {},
        "top_categories": [
            ("groceries", {"amount": Decimal("600.00"), "count": 12}),
            ("rent", {"amount": Decimal("1200.00"), "count": 1}),
        ],
    },
    "previous": {
        "year_month": "2025-12",
        "total_spending": Decimal("2200.00"),
        "spending_count": 25,
        "deposit_total": Decimal(0),
        "deposit_count": 0,
        "by_category": {},
        "by_company": {},
        "top_categories": [],
    },
    "delta_amount": Decimal("300.00"),
    "delta_percent": 13.6,
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSummaryHandler:
    @patch("docker.email_parsing.summary_handler.notification_service.send_raw")
    @patch("docker.email_parsing.summary_handler.SpendingSummary")
    @patch("docker.email_parsing.summary_handler.date")
    def test_handler_publishes_sms(
        self, mock_date: MagicMock, MockSummary: MagicMock, mock_send_raw: MagicMock
    ) -> None:
        """Handler queries previous month, formats SMS, and dispatches via notification_service."""
        from datetime import date as real_date

        mock_date.today.return_value = real_date(2026, 2, 8)
        mock_date.side_effect = lambda *a, **kw: real_date(*a, **kw)

        mock_instance = MagicMock(name="summary")
        MockSummary.return_value = mock_instance
        mock_instance.get_summary_with_comparison.return_value = SAMPLE_COMPARISON_DATA

        from docker.email_parsing import summary_handler

        result = summary_handler.handler({}, None)

        # Verify it queried January 2026
        mock_instance.get_summary_with_comparison.assert_called_once_with("2026-01")

        # Verify notification_service.send_raw was called with the formatted body
        mock_send_raw.assert_called_once()
        call_kwargs = mock_send_raw.call_args.kwargs
        assert call_kwargs["title"] == "Monthly Spending Summary"
        message = call_kwargs["body"]
        assert "January 2026" in message
        assert "$2,500.00" in message

        # Verify response
        assert result["statusCode"] == 200
        assert result["body"]["month"] == "2026-01"
        assert result["body"]["message_length"] > 0

    @patch("docker.email_parsing.summary_handler.notification_service.send_raw")
    @patch("docker.email_parsing.summary_handler.SpendingSummary")
    @patch("docker.email_parsing.summary_handler.date")
    def test_handler_uses_previous_month(
        self, mock_date: MagicMock, MockSummary: MagicMock, mock_send_raw: MagicMock
    ) -> None:
        """Handler computes the correct previous month from today's date."""
        from datetime import date as real_date

        mock_date.today.return_value = real_date(2026, 3, 8)
        mock_date.side_effect = lambda *a, **kw: real_date(*a, **kw)

        mock_instance = MagicMock(name="summary")
        MockSummary.return_value = mock_instance
        mock_instance.get_summary_with_comparison.return_value = SAMPLE_COMPARISON_DATA

        from docker.email_parsing import summary_handler

        summary_handler.handler({}, None)

        mock_instance.get_summary_with_comparison.assert_called_once_with("2026-02")

    @patch("docker.email_parsing.summary_handler.notification_service.send_raw")
    @patch("docker.email_parsing.summary_handler.SpendingSummary")
    @patch("docker.email_parsing.summary_handler.date")
    def test_handler_january_wraps_to_december(
        self, mock_date: MagicMock, MockSummary: MagicMock, mock_send_raw: MagicMock
    ) -> None:
        """When run in January, handler queries December of the previous year."""
        from datetime import date as real_date

        mock_date.today.return_value = real_date(2026, 1, 8)
        mock_date.side_effect = lambda *a, **kw: real_date(*a, **kw)

        mock_instance = MagicMock(name="summary")
        MockSummary.return_value = mock_instance
        mock_instance.get_summary_with_comparison.return_value = SAMPLE_COMPARISON_DATA

        from docker.email_parsing import summary_handler

        summary_handler.handler({}, None)

        mock_instance.get_summary_with_comparison.assert_called_once_with("2025-12")
