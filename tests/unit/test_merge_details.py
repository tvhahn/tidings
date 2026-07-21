"""Tests for merge_details in src/finance/parser_base.py — no mocks needed."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.finance.categorizer import extract_function_call_args
from src.finance.email_parser import (
    extract_email_body,
    extract_forwarded_message_details,
    finalize_email_details,
)
from src.finance.parser_base import merge_details

# ---------------------------------------------------------------------------
# merge_details
# ---------------------------------------------------------------------------


class TestMergeDetails:
    def test_merges_dicts(self):
        base = {"a": 1, "b": 2}
        extra = {"c": 3, "d": 4}
        result = merge_details(base, extra)
        assert result == {"a": 1, "b": 2, "c": 3, "d": 4}

    def test_additional_overwrites_base(self):
        base = {"a": 1, "b": 2}
        extra = {"b": 99}
        result = merge_details(base, extra)
        assert result["b"] == 99

    def test_none_additional_returns_base(self):
        base = {"a": 1}
        result = merge_details(base, None)
        assert result == {"a": 1}

    def test_empty_additional(self):
        base = {"a": 1}
        result = merge_details(base, {})
        assert result == {"a": 1}

    def test_empty_base(self):
        result = merge_details({}, {"x": 10})
        assert result == {"x": 10}


# ---------------------------------------------------------------------------
# extract_function_call_args
# ---------------------------------------------------------------------------


def _make_completion(arguments_json: str) -> SimpleNamespace:
    """Build a fake OpenAI completion object with the given tool-call arguments."""
    tool_call = SimpleNamespace(function=SimpleNamespace(arguments=arguments_json))
    message = SimpleNamespace(tool_calls=[tool_call])
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


class TestExtractFunctionCallArgs:
    def test_extracts_args(self):
        completion = _make_completion('{"category": "Groceries"}')
        result = extract_function_call_args(completion)
        assert result == {"category": "Groceries"}

    def test_extracts_bool_arg(self):
        completion = _make_completion('{"true_or_false": "True"}')
        result = extract_function_call_args(completion)
        assert result == {"true_or_false": "True"}

    def test_no_tool_calls_returns_none(self):
        message = SimpleNamespace(tool_calls=None)
        choice = SimpleNamespace(message=message)
        completion = SimpleNamespace(choices=[choice])
        result = extract_function_call_args(completion)
        assert result is None

    def test_empty_tool_calls_returns_none(self):
        message = SimpleNamespace(tool_calls=[])
        choice = SimpleNamespace(message=message)
        completion = SimpleNamespace(choices=[choice])
        result = extract_function_call_args(completion)
        assert result is None

    def test_invalid_json_raises(self):
        completion = _make_completion("not-json")
        with pytest.raises(Exception, match="Expecting value"):
            extract_function_call_args(completion)

    def test_missing_choices_raises(self):
        completion = SimpleNamespace(choices=[])
        with pytest.raises(Exception, match="index out of range"):
            extract_function_call_args(completion)


# ---------------------------------------------------------------------------
# extract_forwarded_message_details
# ---------------------------------------------------------------------------


class TestExtractForwardedMessageDetails:
    def test_no_forwarded_section(self):
        body = "This is a regular email body with no forwarded message."
        result = extract_forwarded_message_details(body)
        assert result == {}

    def test_extracts_from_name_and_email(self):
        body = (
            "Some preamble.\n"
            "---------- Forwarded message ---------\n"
            "From: John Smith <john@example.com>\n"
            "Date: Mon, 15 Jan 2026 14:30:00 -0800\n"
            "Subject: Transaction Alert\n"
            "To: <user@example.com>\n"
            "\nBody of forwarded message."
        )
        result = extract_forwarded_message_details(body)
        assert result["from_name"] == "John Smith"
        assert result["from_email"] == "john@example.com"
        assert result["to_email"] == "user@example.com"
        assert result["subject"] == "Transaction Alert"
        assert result["date"] is not None

    def test_date_with_timezone_offset(self):
        body = (
            "---------- Forwarded message ---------\n"
            "From: Sender <s@test.com>\n"
            "Date: Mon, 15 Jan 2026 17:30:00 -0500\n"
            "Subject: Test\n"
            "To: <r@test.com>\n"
        )
        result = extract_forwarded_message_details(body)
        # The function formats the date but preserves original timezone
        assert "01/15/2026" in result["date"]
        assert "17:30" in result["date"]

    def test_date_without_timezone_assumes_pacific(self):
        body = (
            "---------- Forwarded message ---------\n"
            "From: Sender <s@test.com>\n"
            "Date: Wed, 15 Jan 2026 10:00:00\n"
            "Subject: Test\n"
            "To: <r@test.com>\n"
        )
        result = extract_forwarded_message_details(body)
        assert "01/15/2026" in result["date"]
        assert "10:00" in result["date"]

    def test_missing_fields_are_absent(self):
        body = "---------- Forwarded message ---------\nSome text without standard headers.\n"
        result = extract_forwarded_message_details(body)
        # Nothing matched, so dict should be empty
        assert "from_name" not in result

    def test_empty_string_body(self):
        result = extract_forwarded_message_details("")
        assert result == {}

    def test_naive_date_uses_configured_app_timezone(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A naive date in a forwarded email assumes the configured tz, not Pacific."""
        import json as _json

        import src.finance.app_config as app_config

        tmp_config = tmp_path / "config.json"
        monkeypatch.setattr(app_config, "_CONFIG_PATH", tmp_config)
        tmp_config.write_text(_json.dumps({"timezone": "Europe/Berlin"}))
        app_config.invalidate_config_cache()
        try:
            body = (
                "---------- Forwarded message ---------\n"
                "From: Sender <s@test.com>\n"
                "Date: Wed, 15 Jan 2026 10:00:00\n"  # naive
                "Subject: Test\n"
                "To: <r@test.com>\n"
            )
            result = extract_forwarded_message_details(body)
            # Jan in Berlin = CET, not PST. Confirms the tz was attached from config.
            assert "CET" in result["date"]
            assert "PST" not in result["date"]
        finally:
            app_config.invalidate_config_cache()


# ---------------------------------------------------------------------------
# finalize_email_details
# ---------------------------------------------------------------------------


class TestFinalizeEmailDetails:
    def test_sets_body(self):
        basic = {"from_email": "a@b.com", "body": ""}
        result = finalize_email_details(basic, "Hello World", {})
        assert result["body"] == "Hello World"

    def test_merges_forwarded_details(self):
        basic = {"from_email": "a@b.com", "body": ""}
        forwarded = {"from_email": "fw@test.com", "subject": "Fwd: Alert"}
        result = finalize_email_details(basic, "body text", forwarded)
        assert result["from_email"] == "fw@test.com"
        assert result["subject"] == "Fwd: Alert"
        assert result["body"] == "body text"

    def test_empty_forwarded_details(self):
        basic = {"from_email": "a@b.com", "body": "", "subject": "Original"}
        result = finalize_email_details(basic, "body text", {})
        assert result["subject"] == "Original"
        assert result["body"] == "body text"

    def test_mutates_basic_details_in_place(self):
        basic = {"body": ""}
        result = finalize_email_details(basic, "new body", {})
        assert basic is result  # same object
        assert basic["body"] == "new body"


# ---------------------------------------------------------------------------
# extract_email_body
# ---------------------------------------------------------------------------


class TestExtractEmailBody:
    def test_plain_text_email(self):
        """Non-multipart plain text email should return body directly."""
        from email.message import EmailMessage

        msg = EmailMessage()
        msg.set_content("Hello, this is a plain text email.")
        result = extract_email_body(msg)
        assert "Hello, this is a plain text email." in result

    def test_html_email(self):
        """Non-multipart HTML email should strip tags."""
        from email.message import EmailMessage

        msg = EmailMessage()
        msg.set_content(
            "<html><body><p>Transaction of $50.00</p></body></html>",
            subtype="html",
        )
        result = extract_email_body(msg)
        assert "Transaction of $50.00" in result
        assert "<html>" not in result

    def test_multipart_prefers_plain_text(self):
        """Multipart email with both text and HTML should prefer text/plain."""
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText("Plain text body", "plain"))
        msg.attach(MIMEText("<p>HTML body</p>", "html"))

        # Parse through BytesParser to get proper EmailMessage
        from email.parser import BytesParser
        from email.policy import default as default_policy

        parsed = BytesParser(policy=default_policy).parsebytes(msg.as_bytes())
        result = extract_email_body(parsed)
        assert "Plain text body" in result

    def test_html_br_replaced_with_newline(self):
        """<br> tags should be replaced with newline characters."""
        from email.message import EmailMessage

        msg = EmailMessage()
        msg.set_content(
            "<html><body>Line 1<br>Line 2<br/>Line 3</body></html>",
            subtype="html",
        )
        result = extract_email_body(msg)
        assert "Line 1" in result
        assert "Line 2" in result

    def test_empty_body(self):
        """Email with empty body should return empty string."""
        from email.message import EmailMessage

        msg = EmailMessage()
        msg.set_content("")
        result = extract_email_body(msg)
        assert isinstance(result, str)

    def test_html_entities_decoded(self):
        """HTML entities like &amp; should be decoded."""
        from email.message import EmailMessage

        msg = EmailMessage()
        msg.set_content(
            "<html><body>AT&amp;T Wireless</body></html>",
            subtype="html",
        )
        result = extract_email_body(msg)
        assert "AT&T Wireless" in result
