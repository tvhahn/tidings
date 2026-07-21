"""Unit tests for scripts/pii/audit_oss_release.py — the deterministic PII/secret audit.

The script is not an importable package module (it lives under scripts/ and is
run as a CLI), so it is loaded by path via importlib. Only obviously-fake,
constructed values are used here — never real-looking PII. `4111 1111 1111 1111`
is the industry-standard Luhn-valid *test* PAN.

Credential-shaped constants are assembled at runtime (string concatenation /
join) so this file never contains a literal that the audit's own patterns
match at rest — otherwise the release audit of the real tree flags its own
test suite. Do not "simplify" them back into single literals.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_AUDIT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "pii" / "audit_oss_release.py"
_spec = importlib.util.spec_from_file_location("audit_oss_release", _AUDIT_PATH)
assert _spec is not None
assert _spec.loader is not None
audit = importlib.util.module_from_spec(_spec)
# Register before exec so @dataclass can resolve the module's namespace.
sys.modules["audit_oss_release"] = audit
_spec.loader.exec_module(audit)


def _findings(line: str) -> list:
    """Scan a single line through the credential/email/phone patterns."""
    report = audit.Report(target="t")
    audit.scan_text_lines([(1, line)], "f.txt", None, report)
    return report.findings


# ---------------------------------------------------------------------------
# Luhn-graded card detection
# ---------------------------------------------------------------------------


def test_luhn_valid_pan_is_hit() -> None:
    findings = _findings("charged to card 4111 1111 1111 1111 today")
    cards = [f for f in findings if f.category == "card-number"]
    assert cards
    assert any(f.severity == "hit" for f in cards)


def test_luhn_invalid_16_digits_is_review() -> None:
    # 4111...1112 fails the checksum → review, never dropped, never a hit.
    findings = _findings("number 4111 1111 1111 1112 here")
    cards = [f for f in findings if f.category == "card-number"]
    assert cards
    assert all(f.severity == "review" for f in cards)
    assert not any(f.severity == "hit" for f in findings)


def test_float_decimal_digits_not_hit() -> None:
    # A decimal-fraction mantissa must not block, and the guard must not depend on
    # Luhn: 0.5195207601735179 is Luhn-invalid, so assemble a Luhn-VALID one too.
    findings = _findings("delta_percent = 0.5195207601735179")
    assert not any(f.severity == "hit" for f in findings)


def test_luhn_valid_float_mantissa_is_review_not_hit() -> None:
    # Regression: 0.9115646258503401 (= 268/294, a demo capture rate) has a
    # Luhn-VALID 16-digit mantissa. Before the decimal-fraction guard it graded as
    # a `hit` and blocked the pre-push audit. It must now be a surfaced `review`.
    assert audit.luhn_valid("9115646258503401"), "fixture assumption: mantissa is Luhn-valid"
    findings = _findings('  "rate": 0.9115646258503401')
    cards = [f for f in findings if f.category == "card-number"]
    assert cards, "the run must still surface (never silently dropped)"
    assert all(f.severity == "review" for f in cards)
    assert not any(f.severity == "hit" for f in findings)


# ---------------------------------------------------------------------------
# New credential shapes
# ---------------------------------------------------------------------------


def test_sk_ant_token_is_hit() -> None:
    token = "sk-ant-" + "abc012345678901234567890"  # assembled: see module docstring
    findings = _findings(f'key = "{token}"')
    assert any(f.category == "anthropic-key" and f.severity == "hit" for f in findings)
    # Deduped: the broad openai `sk-` pattern must not also record the same span.
    assert not any(f.category == "openai-key" for f in findings)


def test_jwt_is_hit() -> None:
    # assembled: see module docstring
    jwt = ".".join(["eyJhbGciOiJIUzI1NiJ9", "eyJzdWIiOiIxMjM0NTY3ODkwIn0", "dozjgNryP4J3jVmNHl0w5NqYQ"])
    findings = _findings(f"authorization: Bearer {jwt}")
    assert any(f.category == "jwt" and f.severity == "hit" for f in findings)


def test_arn_with_account_id_is_hit() -> None:
    arn = "arn:aws:iam:" + ":123456789012:role/AdminRole"  # assembled: see module docstring
    findings = _findings(f'resource = "{arn}"')
    assert any(f.category == "aws-arn-account" and f.severity == "hit" for f in findings)


def test_project_token_allowlisted_in_remote_allowlist_context() -> None:
    """A project token on a `github\\.com[:/]owner/repo` grep line (the pre-push
    hook's remote allowlist) is public attribution → allowlisted, not a hit."""
    import re

    project_re = re.compile("SOMEOWNER", re.IGNORECASE)
    report = audit.Report(target="t")
    line = "grep -qE 'github\\.com[:/]SOMEOWNER/somerepo(\\.git)?/?$'"
    audit.scan_text_lines([(1, line)], ".githooks/pre-push", project_re, report)
    pii = [f for f in report.findings if f.category == "project-pii"]
    assert pii
    assert all(f.severity == "allowlisted" for f in pii)


# ---------------------------------------------------------------------------
# Filename-token scan + clean-tree exit code
# ---------------------------------------------------------------------------


def test_long_token_filename_flagged(tmp_path: Path) -> None:
    sub = tmp_path / "tests" / "x"
    sub.mkdir(parents=True)
    token = "abcdefghij0123456789abcdefghij0123456789"  # 40 chars, lowercase alnum
    (sub / f"2024.01.01_00.00_{token}_x.txt").write_text("nothing sensitive here\n")

    report = audit.Report(target=str(tmp_path))
    audit.walk(tmp_path, None, report)
    assert any(f.category == "filename-token" for f in report.findings)


def test_include_matches_unredacts_markdown(tmp_path: Path) -> None:
    # A Luhn-invalid card-shaped run surfaces as a `review` finding. With
    # --include-matches the Markdown shows the value verbatim; without it, redacted.
    shaped = "4111 1111 1111 1112"
    (tmp_path / "notes.txt").write_text(f"number {shaped} here\n")

    report = audit.Report(target=str(tmp_path))
    audit.walk(tmp_path, None, report)

    base = tmp_path / "audit-report"
    audit.write_reports(report, base, include_matches=True)
    md = (base.parent / "audit-report.md").read_text()
    assert shaped in md
    assert "<REDACTED:" not in md
    assert "| Match |" in md

    audit.write_reports(report, base, include_matches=False)
    md = (base.parent / "audit-report.md").read_text()
    assert shaped not in md
    assert "<REDACTED:" in md
    assert "| Redacted |" in md


def test_clean_tree_exit_zero(tmp_path: Path) -> None:
    (tmp_path / "readme.txt").write_text("hello world\n")
    (tmp_path / "main.py").write_text("print('hi there')\n")

    report = audit.Report(target=str(tmp_path))
    audit.walk(tmp_path, None, report)
    code = audit.write_reports(report, tmp_path / "audit-report", False)
    assert code == 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
