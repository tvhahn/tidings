"""Date edge-case tests — leap-year, DST transitions, year boundaries.

The general-case timezone tests in ``test_email_extraction.py`` confirm
``extract_basic_details()`` normalizes dates to Pacific Time for ordinary
inputs. These tests exercise the boundaries where AI-generated code is
most likely to regress silently: the leap-day, the two DST transitions,
and the year rollover.
"""

from email.message import EmailMessage

from src.finance.email_parser import extract_basic_details


def _build_email(date: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = "alerts@rbc.com"
    msg["To"] = "user@example.com"
    msg["Subject"] = "Test"
    msg["Date"] = date
    return msg


class TestLeapYear:
    def test_feb_29_leap_year_parses(self):
        """2024 is a leap year; Feb 29 is a valid date."""
        # UTC 08:00 on Feb 29 2024 → PST 00:00
        msg = _build_email("Thu, 29 Feb 2024 08:00:00 +0000")
        result = extract_basic_details(msg)
        assert result["date"] == "02/29/2024 00:00 PST"

    def test_feb_29_non_leap_year_returns_none(self):
        """2025 is not a leap year; Feb 29 is unparseable → date is None."""
        msg = _build_email("Sat, 29 Feb 2025 08:00:00 +0000")
        result = extract_basic_details(msg)
        assert result["date"] is None


class TestDstTransitions:
    """DST boundaries in the America/Los_Angeles zone.

    Spring forward: 02:00 PST → 03:00 PDT on March 10 2024.
    Fall back:      02:00 PDT → 01:00 PST on November 3 2024.
    """

    def test_spring_forward_just_before_jump(self):
        """01:59 PST (UTC 09:59) is still PST — the 2am jump hasn't fired."""
        msg = _build_email("Sun, 10 Mar 2024 09:59:00 +0000")
        result = extract_basic_details(msg)
        assert result["date"] == "03/10/2024 01:59 PST"

    def test_spring_forward_just_after_jump(self):
        """03:01 PDT (UTC 10:01) — clocks have jumped; label is PDT, not PST."""
        msg = _build_email("Sun, 10 Mar 2024 10:01:00 +0000")
        result = extract_basic_details(msg)
        assert result["date"] == "03/10/2024 03:01 PDT"

    def test_fall_back_before_transition(self):
        """00:59 PDT (UTC 07:59) — before the 2am fall-back, still PDT."""
        msg = _build_email("Sun, 3 Nov 2024 07:59:00 +0000")
        result = extract_basic_details(msg)
        assert result["date"] == "11/03/2024 00:59 PDT"

    def test_fall_back_after_transition(self):
        """01:01 PST (UTC 09:01) — after 2am PDT fell back to 1am PST."""
        msg = _build_email("Sun, 3 Nov 2024 09:01:00 +0000")
        result = extract_basic_details(msg)
        assert result["date"] == "11/03/2024 01:01 PST"


class TestYearBoundary:
    def test_utc_late_dec_31_converts_to_earlier_pst_dec_31(self):
        """Dec 31 2024 23:55 UTC → Dec 31 2024 15:55 PST (stays in December)."""
        msg = _build_email("Tue, 31 Dec 2024 23:55:00 +0000")
        result = extract_basic_details(msg)
        assert result["date"] == "12/31/2024 15:55 PST"

    def test_pst_dec_31_late_stays_in_december(self):
        """Dec 31 2024 23:55 PST is UTC Jan 1 2025 07:55, but the Pacific-
        normalized value must stay Dec 31."""
        msg = _build_email("Tue, 31 Dec 2024 23:55:00 -0800")
        result = extract_basic_details(msg)
        assert result["date"] == "12/31/2024 23:55 PST"

    def test_pst_jan_1_early_stays_in_january(self):
        """Jan 1 2025 00:05 PST is already Pacific — no month shift."""
        msg = _build_email("Wed, 1 Jan 2025 00:05:00 -0800")
        result = extract_basic_details(msg)
        assert result["date"] == "01/01/2025 00:05 PST"
