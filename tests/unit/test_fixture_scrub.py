"""Unit tests for src.finance.fixture_scrub — PII redaction for fixture bodies.

The always-on hard redactions (emails, card numbers, To:/From: headers,
forwarded_to) run with no ``.pii-patterns`` present; the optional patterns file
adds project-specific rules (names) on top. Dollar amounts must survive both.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.finance.fixture_scrub as fixture_scrub
from src.finance.fixture_scrub import scan_for_pii, scrub_body, write_fixture_pair

_BODY = """From: John Doe <john.doe@personalmail.com>
To: mira.forward@example.com

Hello John Doe,

A purchase of $1,234.56 was charged to your card ending 4111 1111 1111 1111.
Questions? Reach us at support@bigbank.example or john.doe@personalmail.com.
"""


def test_hard_redactions_apply_without_patterns_file(tmp_path: Path) -> None:
    # Point the patterns resolver at a nonexistent file → only hard redactions.
    scrubbed = scrub_body(_BODY, patterns_path=tmp_path / "absent.pii-patterns")

    # Email addresses gone, replaced with the synthetic placeholder.
    assert "john.doe@personalmail.com" not in scrubbed
    assert "support@bigbank.example" not in scrubbed
    assert "redacted@example.com" in scrubbed

    # 16-digit card number redacted to the synthetic placeholder.
    assert "4111 1111 1111 1111" not in scrubbed
    assert "0000 0000 0000 0000" in scrubbed

    # To:/From: header values blanked.
    assert "From: [redacted]" in scrubbed
    assert "To: [redacted]" in scrubbed

    # Dollar amount preserved for the fixture to assert against.
    assert "$1,234.56" in scrubbed


def test_pii_patterns_file_redacts_names(tmp_path: Path, monkeypatch) -> None:
    patterns = tmp_path / ".pii-patterns"
    patterns.write_text("# a comment\n\nJohn Doe\n", encoding="utf-8")
    # Patch the repo-root resolver so the injected file is discovered.
    monkeypatch.setattr(fixture_scrub, "_pii_patterns_path", lambda: patterns)

    scrubbed = scrub_body(_BODY)

    assert "John Doe" not in scrubbed
    assert "[redacted]" in scrubbed
    # Amount still survives even with the patterns file present.
    assert "$1,234.56" in scrubbed


def test_forwarded_to_token_redacted() -> None:
    body = "Alert for account forwarded via inbox+tag@relay.example today."
    scrubbed = scrub_body(
        body,
        forwarded_to="inbox+tag@relay.example",
        patterns_path=Path("/nonexistent/.pii-patterns"),
    )
    assert "inbox+tag@relay.example" not in scrubbed


def test_extra_patterns_applied() -> None:
    scrubbed = scrub_body(
        "Cardholder MAPLE-9931 spent $42.00",
        extra_patterns=[r"MAPLE-\d+"],
        patterns_path=Path("/nonexistent/.pii-patterns"),
    )
    assert "MAPLE-9931" not in scrubbed
    assert "$42.00" in scrubbed


def test_empty_body_is_passthrough() -> None:
    assert scrub_body("", patterns_path=Path("/nonexistent")) == ""


def test_amount_like_digit_runs_survive() -> None:
    # A 9-digit money amount must not be mistaken for a card number.
    body = "Balance is $417,124.99 as of today."
    scrubbed = scrub_body(body, patterns_path=Path("/nonexistent"))
    assert "$417,124.99" in scrubbed
    assert "0000 0000 0000 0000" not in scrubbed


# ---------------------------------------------------------------------------
# scan_for_pii — the checklist's PII scan, sharing the scrubber's own regexes
# ---------------------------------------------------------------------------


def test_scan_for_pii_flags_real_email_and_card() -> None:
    dirty = "Charged to 4111 1111 1111 1111; reply to john.doe@personalmail.com."
    hits = scan_for_pii(dirty, patterns_path=Path("/nonexistent"))
    assert "john.doe@personalmail.com" in hits
    assert "4111 1111 1111 1111" in hits


def test_scan_for_pii_ignores_scrubber_placeholders() -> None:
    # A body straight out of scrub_body is full of placeholders — it must scan
    # clean, not re-flag "redacted@example.com" / "0000 0000 0000 0000".
    scrubbed = scrub_body(_BODY, patterns_path=Path("/nonexistent"))
    assert scan_for_pii(scrubbed, patterns_path=Path("/nonexistent")) == []


def test_scan_for_pii_applies_patterns_file(tmp_path: Path, monkeypatch) -> None:
    patterns = tmp_path / ".pii-patterns"
    patterns.write_text("# names\nJohn Doe\n", encoding="utf-8")
    monkeypatch.setattr(fixture_scrub, "_pii_patterns_path", lambda: patterns)
    hits = scan_for_pii("A note about John Doe.")
    assert "John Doe" in hits


def test_scan_for_pii_empty_text() -> None:
    assert scan_for_pii("", patterns_path=Path("/nonexistent")) == []


# ---------------------------------------------------------------------------
# Card last-4 masking (ending in / Card number: contexts)
# ---------------------------------------------------------------------------

_NONE = Path("/nonexistent")


def test_last4_masked_ending_in() -> None:
    scrubbed = scrub_body("Your card ending in 4242 was charged $50.00.", patterns_path=_NONE)
    assert "ending in 4242" not in scrubbed
    assert "ending in 0000" in scrubbed
    # Amount untouched.
    assert "$50.00" in scrubbed


def test_last4_masked_card_number_context() -> None:
    scrubbed = scrub_body("Card number: ****4242", patterns_path=_NONE)
    assert "4242" not in scrubbed
    assert "Card number: ****0000" in scrubbed


def test_bare_four_digits_not_masked() -> None:
    # A dollar amount and a bare year must survive — no last-4 context, no mask.
    body = "Order total $1234.00 placed in 2024."
    scrubbed = scrub_body(body, patterns_path=_NONE)
    assert "$1234.00" in scrubbed
    assert "2024" in scrubbed
    assert "0000" not in scrubbed


# ---------------------------------------------------------------------------
# Interac e-Transfer reference masking (only in an INTERAC body)
# ---------------------------------------------------------------------------


def test_interac_ref_masked_when_interac_body() -> None:
    body = "INTERAC e-Transfer received.\nReference: A1Bcdefgh234"
    scrubbed = scrub_body(body, patterns_path=_NONE)
    assert "A1Bcdefgh234" not in scrubbed
    assert "[INTERAC_REF]" in scrubbed


def test_interac_ref_untouched_without_interac_context() -> None:
    # Same ref shape, but no INTERAC keyword → the rule does not fire.
    body = "Reference: A1Bcdefgh234 (no bank keyword here)"
    scrubbed = scrub_body(body, patterns_path=_NONE)
    assert "A1Bcdefgh234" in scrubbed


def test_scan_for_pii_ignores_new_placeholders() -> None:
    # A body straight out of scrub_body — masked last-4 (0000) and masked Interac
    # ref ([INTERAC_REF]) must both scan clean.
    body = "INTERAC e-Transfer received.\nSent to the card ending in 4242.\nReference number: C1Ab3Kf9TrQ2\n"
    scrubbed = scrub_body(body, patterns_path=_NONE)
    assert scan_for_pii(scrubbed, patterns_path=_NONE) == []


def test_scan_for_pii_flags_unknown_last4_and_ref() -> None:
    dirty = "INTERAC transfer, card ending in 4444, ref Z9Testref001 posted."
    hits = scan_for_pii(dirty, patterns_path=_NONE)
    assert any("4444" in h for h in hits)
    assert "Z9Testref001" in hits


def test_scan_for_pii_allows_synthetic_last4_and_ref() -> None:
    # Allowlisted last-4 (locked fixture value) + allowlisted Interac ref.
    clean = "INTERAC transfer, card ending in 2210, ref C1Ab3Kf9TrQ2 posted."
    assert scan_for_pii(clean, patterns_path=_NONE) == []


# ---------------------------------------------------------------------------
# write_fixture_pair — the shared fixture writer (no HTTP concerns)
# ---------------------------------------------------------------------------


def test_write_fixture_pair_writes_scrubbed_pair(tmp_path: Path) -> None:
    txt_path, json_path = write_fixture_pair(
        test_data_root=tmp_path,
        dir_slug="maple_trust",
        file_slug="purchase_sample_1",
        scrubbed_body="A purchase of $12.34 was made.",
        institution="Maple Trust",
    )
    # Returned paths are always canonical repo-relative, regardless of the root.
    assert txt_path == "tests/test_data/maple_trust/purchase_sample_1.txt"
    assert json_path == "tests/test_data/maple_trust/purchase_sample_1.json"

    txt_file = tmp_path / "maple_trust" / "purchase_sample_1.txt"
    json_file = tmp_path / "maple_trust" / "purchase_sample_1.json"
    assert txt_file.read_text(encoding="utf-8") == "A purchase of $12.34 was made."

    skeleton = json.loads(json_file.read_text(encoding="utf-8"))
    assert skeleton == {
        "institution": "Maple Trust",
        "name": "TODO",
        "amount": "TODO",
        "company": "TODO",
        "transaction_type": "TODO",
        "email_filepath": "tests/test_data/maple_trust/purchase_sample_1.txt",
    }
    # Byte shape: pretty-printed with a trailing newline (matches load_test_data).
    assert json_file.read_text(encoding="utf-8").endswith("}\n")


def test_write_fixture_pair_raises_on_collision(tmp_path: Path) -> None:
    kwargs = {
        "test_data_root": tmp_path,
        "dir_slug": "maple_trust",
        "file_slug": "dup",
        "scrubbed_body": "body",
        "institution": "Maple Trust",
    }
    write_fixture_pair(**kwargs)
    with pytest.raises(FileExistsError):
        write_fixture_pair(**kwargs)
