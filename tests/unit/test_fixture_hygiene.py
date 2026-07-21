"""Deterministic hygiene guards for the committed email test fixtures.

These lock in the PII-remediation invariants so future edits can't quietly
reintroduce real-transaction residue: message-id-shaped filenames, un-scrubbed
bodies, dangling ``email_filepath`` references, or a broken edge-case pair.

Every check is self-contained and reproducible on a public clone — the body
scan pins ``patterns_path`` to a non-existent file so it never reads a
developer's local ``.pii-patterns``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.finance.fixture_scrub import scan_for_pii

# tests/unit/test_fixture_hygiene.py -> tests/test_data
TEST_DATA_DIR = Path(__file__).resolve().parent.parent / "test_data"

# A message-id / SES-object-key shaped run: 35+ consecutive alphanumerics.
_MESSAGE_ID_SEGMENT_RE = re.compile(r"[a-z0-9]{35,}", re.IGNORECASE)

# A dollar amount like ``$3,250.00`` — capture the numeric part without the ``$``.
_DOLLAR_RE = re.compile(r"\$([\d,]+\.\d{2})")


def _fixture_files(suffix: str) -> list[Path]:
    """Return committed fixture files with ``suffix``, excluding the ``_private`` tree."""
    return sorted(p for p in TEST_DATA_DIR.rglob(f"*{suffix}") if p.is_file() and "_private" not in p.parts)


def _first_amount(path: Path) -> str:
    """Return the first ``$``-amount string (comma-grouped, no ``$``) in a fixture body."""
    match = _DOLLAR_RE.search(path.read_text(encoding="utf-8"))
    assert match is not None, f"no dollar amount found in {path}"
    return match.group(1)


def test_no_message_id_shaped_filenames() -> None:
    """No fixture filename carries a 35+ char alphanumeric segment (a real SES message id)."""
    offenders = [str(p) for p in _fixture_files("") if _MESSAGE_ID_SEGMENT_RE.search(p.name)]
    assert offenders == [], f"message-id-shaped fixture filenames: {offenders}"


def test_fixture_bodies_scan_clean() -> None:
    """Every fixture ``.txt`` body is free of PII per the always-on scrubber regexes.

    ``patterns_path`` is pinned to a non-existent path so the scan depends only on
    the built-in email/card rules and never on a local ``.pii-patterns`` file.
    """
    missing_patterns = TEST_DATA_DIR / "__does_not_exist__.pii-patterns"
    dirty = {
        str(p): hits
        for p in _fixture_files(".txt")
        if (hits := scan_for_pii(p.read_text(encoding="utf-8"), patterns_path=missing_patterns))
    }
    assert dirty == {}, f"fixtures with PII-shaped residue: {dirty}"


def test_json_email_filepath_resolves() -> None:
    """Every fixture ``.json`` that references an ``email_filepath`` points at a real file."""
    dangling = []
    for json_path in _fixture_files(".json"):
        data = json.loads(json_path.read_text(encoding="utf-8"))
        email_filepath = data.get("email_filepath")
        if email_filepath is None:
            continue  # Statement fixtures use a different schema.
        if not Path(email_filepath).exists():
            dangling.append((str(json_path), email_filepath))
    assert dangling == [], f"dangling email_filepath references: {dangling}"


def test_edge_case_pairs_preserved() -> None:
    """The two intentional edge-case relationships survive (README trap 4).

    The two ``2024.09.16`` e-transfers share one identical amount; the two
    ``2024.09.05`` withdrawals differ only by a leading ``4`` on the amount. Amounts
    are read from the ``.txt`` bodies because one e-transfer's ``.json`` is minimal
    (institution + ``email_filepath`` only, no ``amount`` field).
    """
    rbc = TEST_DATA_DIR / "rbc"

    etransfer_a = _first_amount(rbc / "2024.09.16_20.10_rbc707ggg808_rbc_e-transfer.txt")
    etransfer_b = _first_amount(rbc / "2024.09.16_20.10_rbc808hhh909_rbc_e-transfer.txt")
    assert etransfer_a == etransfer_b, f"e-transfer amounts diverged: {etransfer_a} != {etransfer_b}"

    withdrawal_small = _first_amount(rbc / "2024.09.05_09.25_rbc909jjj010_rbc_withdrawal.txt")
    withdrawal_large = _first_amount(rbc / "2024.09.05_09.25_rbc919kkk020_rbc_withdrawal.txt")
    assert withdrawal_large == f"4{withdrawal_small}", (
        f"withdrawal pair no longer differs by a leading 4: {withdrawal_small} vs {withdrawal_large}"
    )
