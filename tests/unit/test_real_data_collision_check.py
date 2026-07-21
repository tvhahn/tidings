"""Unit tests for scripts/pii/real_data_collision_check.py — the inverse PII audit.

The script is a CLI under scripts/, not an importable package module, so it is
loaded by path via importlib (registered in sys.modules BEFORE exec so the
module's @dataclass definitions resolve their own namespace).

ALL data here is 100% synthetic — invented merchants ("Zephyrwick Plumbing"),
invented surnames, fake reference codes ("QQ7ZK41"). Nothing resembles a real
merchant or person. No credential-shaped literals appear. Never reads anything
under /workspace/data — every test scans a synthetic --target directory built in
tmp_path with a synthetic --csv.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "pii" / "real_data_collision_check.py"
_spec = importlib.util.spec_from_file_location("real_data_collision_check", _SCRIPT_PATH)
assert _spec is not None
assert _spec.loader is not None
collide = importlib.util.module_from_spec(_spec)
# Register before exec so @dataclass can resolve the module namespace.
sys.modules["real_data_collision_check"] = collide
_spec.loader.exec_module(collide)


# The exact real header row (order fixed; CategoryAudit omitted here — optional).
_HEADER = [
    "ForwardedTo",
    "DateFileName",
    "FileName",
    "Date",
    "UserId",
    "FromName",
    "FromEmail",
    "ToName",
    "ToEmail",
    "Institution",
    "Subject",
    "Body",
    "Name",
    "Amount",
    "Company",
    "TransactionType",
    "Category",
]


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_HEADER, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in _HEADER})


def _blank_row(**overrides: str) -> dict[str, str]:
    row = dict.fromkeys(_HEADER, "")
    row["Amount"] = "12.34"
    row.update(overrides)
    return row


def _run(
    tmp_path: Path,
    csv_rows: list[dict[str, str]],
    target_files: dict[str, str],
    *,
    dispositions: list[str] | None = None,
    include_matches: bool = False,
    extra_argv: list[str] | None = None,
) -> tuple[int, dict]:
    """Write CSV + target dir, run main(), return (exit_code, parsed JSON report)."""
    csv_path = tmp_path / "transactions.csv"
    _write_csv(csv_path, csv_rows)

    target = tmp_path / "target"
    target.mkdir(exist_ok=True)
    for rel, content in target_files.items():
        fp = target / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")

    dispo_path = tmp_path / ".pii-dispositions"
    dispo_path.write_text("\n".join(dispositions or []) + "\n", encoding="utf-8")

    output = tmp_path / "report"
    argv = [
        "--csv",
        str(csv_path),
        "--target",
        str(target),
        "--dispositions",
        str(dispo_path),
        "--output",
        str(output),
    ]
    if include_matches:
        argv.append("--include-matches")
    if extra_argv:
        argv.extend(extra_argv)

    code = collide.main(argv)
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    return code, report


def _all_finding_classes(report: dict) -> set[str]:
    return {entry["token_class"] for entry in report["findings"]}


# ---------------------------------------------------------------------------
# 1. full-string collision
# ---------------------------------------------------------------------------


def test_full_string_collision_found(tmp_path: Path) -> None:
    rows = [_blank_row(Company="Zephyrwick Plumbing Supplies")]
    code, report = _run(
        tmp_path,
        rows,
        {"fixtures/leak.py": "vendor = 'Zephyrwick Plumbing Supplies'\n"},
    )
    assert code == 1
    fulls = [e for e in report["findings"] if e["token_class"] == "full-string"]
    assert len(fulls) == 1
    matches = fulls[0]["matches"]
    assert len(matches) == 1
    assert matches[0]["file"] == "fixtures/leak.py"
    assert matches[0]["line"] == 1


# ---------------------------------------------------------------------------
# 2. truncation → prefix
# ---------------------------------------------------------------------------


def test_truncated_prefix_collision(tmp_path: Path) -> None:
    # 4-word merchant in the CSV; only the first two words leak into a comment.
    rows = [_blank_row(Name="Quillfeather Artisan Bakery Cafe")]
    code, report = _run(
        tmp_path,
        rows,
        {"src/note.py": "# legacy label: Quillfeather Artisan\n"},
    )
    assert code == 1
    prefixes = [e for e in report["findings"] if e["token_class"] == "prefix"]
    assert prefixes, "expected a prefix finding for the truncated merchant"
    assert prefixes[0]["matches"][0]["file"] == "src/note.py"


# ---------------------------------------------------------------------------
# 3. transposition → word-variant
# ---------------------------------------------------------------------------


def test_transposition_word_variant(tmp_path: Path) -> None:
    # CSV surname "Vandersloot"; the target carries a bank-side adjacent swap.
    rows = [_blank_row(FromName="Vandersloot")]
    # swap positions 4/5: Vand-re-sloot -> "vanderloot"? build the exact swap.
    original = "vandersloot"
    swapped = list(original)
    swapped[6], swapped[7] = swapped[7], swapped[6]  # ...sl -> ...ls
    variant = "".join(swapped)
    assert variant != original
    code, report = _run(
        tmp_path,
        rows,
        {"tests/fixtures/x.txt": f"payee {variant} on file\n"},
    )
    assert code == 1
    variants = [e for e in report["findings"] if e["token_class"] == "word-variant"]
    assert variants, "expected a word-variant finding"
    assert variants[0]["provenance"]["variant_of"] == original


# ---------------------------------------------------------------------------
# 4. stoplisted common word → no finding
# ---------------------------------------------------------------------------


def test_stoplisted_word_no_finding(tmp_path: Path) -> None:
    # "insurance" is a curated stoplist generic embedded in a multi-word merchant.
    # The full merchant string never appears in the target — only the generic
    # word does — so a correct stoplist yields NO finding. (If "insurance" were
    # not stoplisted it would become a word token and collide.)
    rows = [_blank_row(Company="Zephyrwick Insurance Brokers")]
    code, report = _run(
        tmp_path,
        rows,
        {"docs/readme.md": "we discuss insurance broadly here\n"},
    )
    assert code == 0
    assert report["findings"] == []


# ---------------------------------------------------------------------------
# 5. disposition suppresses
# ---------------------------------------------------------------------------


def test_disposition_suppresses(tmp_path: Path) -> None:
    # A single-word merchant produces a full-string token (and a same-text word
    # token); one disposition entry, matched by normalized text, suppresses both.
    rows = [_blank_row(Company="Zephyrwick")]
    code, report = _run(
        tmp_path,
        rows,
        {"fixtures/leak.py": "vendor = 'Zephyrwick'\n"},
        dispositions=["Zephyrwick"],
    )
    assert code == 0
    assert report["findings"] == []
    dispo_classes = {e["token_class"] for e in report["dispositioned"]}
    assert "full-string" in dispo_classes


# ---------------------------------------------------------------------------
# 6. email + reference
# ---------------------------------------------------------------------------


def test_email_and_reference_findings(tmp_path: Path) -> None:
    # Enough rows that the special ref appears in < 30% (else boilerplate-dropped).
    rows = [
        _blank_row(FromEmail="billing@zephyrwick.example", Subject="Order QQ7ZK41 shipped"),
        _blank_row(Subject="Weekly update alpha"),
        _blank_row(Subject="Weekly update beta"),
        _blank_row(Subject="Weekly update gamma"),
        _blank_row(Subject="Weekly update delta"),
    ]
    target = {
        "a/contact.py": "notify = 'billing@zephyrwick.example'\n",
        "a/ref.py": "trace_id = 'QQ7ZK41'\n",
    }
    code, report = _run(tmp_path, rows, target)
    assert code == 1
    classes = _all_finding_classes(report)
    assert "email" in classes
    assert "reference" in classes


# ---------------------------------------------------------------------------
# 7. amount proximity
# ---------------------------------------------------------------------------


def test_amount_proximity(tmp_path: Path) -> None:
    rows = [_blank_row(Company="Zephyrwick Plumbing Supplies", Amount="2647.35")]
    target = {
        # amount within 2 lines of the full-string finding -> amount finding.
        "near.py": ("line one\nvendor = 'Zephyrwick Plumbing Supplies'\ncost = 2647.35\n"),
        # same amount with NO other finding in the file -> no amount finding.
        "far.py": "unrelated = 2647.35\n",
    }
    code, report = _run(tmp_path, rows, target)
    assert code == 1
    amount_entries = [e for e in report["findings"] if e["token_class"] == "amount"]
    assert len(amount_entries) == 1
    matches = amount_entries[0]["matches"]
    assert len(matches) == 1
    assert matches[0]["file"] == "near.py"
    assert matches[0]["anchor"] == "near.py:2"


# ---------------------------------------------------------------------------
# 8. attribution allowlist
# ---------------------------------------------------------------------------


def test_attribution_line_not_flagged(tmp_path: Path) -> None:
    rows = [_blank_row(Company="Zephyrwick Plumbing Supplies")]
    target = {
        "README.md": "clone https://github.com/Zephyrwick Plumbing Supplies/repo\n",
    }
    code, report = _run(tmp_path, rows, target)
    assert code == 0
    assert report["findings"] == []


# ---------------------------------------------------------------------------
# 9. redaction
# ---------------------------------------------------------------------------


def test_redaction_default_and_include(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    token_text = "Zephyrwick Plumbing Supplies"
    rows = [_blank_row(Company=token_text)]
    target = {"fixtures/leak.py": f"vendor = '{token_text}'\n"}

    code, _ = _run(tmp_path, rows, target)
    assert code == 1
    report_text = (tmp_path / "report.json").read_text(encoding="utf-8")
    normalized = collide._normalize(token_text)
    assert token_text not in report_text
    assert normalized not in report_text
    captured = capsys.readouterr()
    assert token_text not in captured.out
    assert normalized not in captured.out
    assert "<REDACTED:" in report_text

    code, _ = _run(tmp_path, rows, target, include_matches=True)
    assert code == 1
    report_text = (tmp_path / "report.json").read_text(encoding="utf-8")
    assert normalized in report_text


# ---------------------------------------------------------------------------
# 10. --download deletion semantics
# ---------------------------------------------------------------------------


def test_download_deletes_csv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    csv_path = tmp_path / "dl.csv"
    rows = [_blank_row(Company="Zephyrwick Plumbing Supplies")]

    def fake_download(repo_root: Path) -> None:
        _write_csv(csv_path, rows)

    monkeypatch.setattr(collide, "_download", fake_download)

    target = tmp_path / "target"
    target.mkdir()
    (target / "clean.txt").write_text("nothing here\n", encoding="utf-8")
    dispo = tmp_path / ".pii-dispositions"
    dispo.write_text("\n", encoding="utf-8")

    argv = [
        "--download",
        "--csv",
        str(csv_path),
        "--target",
        str(target),
        "--dispositions",
        str(dispo),
        "--output",
        str(tmp_path / "r"),
    ]
    code = collide.main(argv)
    assert code == 0
    assert not csv_path.exists(), "--download without --keep-csv must delete the CSV"


def test_download_keep_csv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    csv_path = tmp_path / "dl.csv"
    rows = [_blank_row(Company="Zephyrwick Plumbing Supplies")]

    def fake_download(repo_root: Path) -> None:
        _write_csv(csv_path, rows)

    monkeypatch.setattr(collide, "_download", fake_download)

    target = tmp_path / "target"
    target.mkdir()
    (target / "clean.txt").write_text("nothing here\n", encoding="utf-8")
    dispo = tmp_path / ".pii-dispositions"
    dispo.write_text("\n", encoding="utf-8")

    argv = [
        "--download",
        "--keep-csv",
        "--csv",
        str(csv_path),
        "--target",
        str(target),
        "--dispositions",
        str(dispo),
        "--output",
        str(tmp_path / "r"),
    ]
    code = collide.main(argv)
    assert code == 0
    assert csv_path.exists(), "--keep-csv must retain the CSV"


def test_user_supplied_csv_not_deleted(tmp_path: Path) -> None:
    # No --download: a user-supplied CSV is never deleted.
    rows = [_blank_row(Company="Zephyrwick Plumbing Supplies")]
    csv_path = tmp_path / "transactions.csv"
    _write_csv(csv_path, rows)
    target = tmp_path / "target"
    target.mkdir()
    (target / "clean.txt").write_text("nothing\n", encoding="utf-8")
    dispo = tmp_path / ".pii-dispositions"
    dispo.write_text("\n", encoding="utf-8")

    code = collide.main(
        [
            "--csv",
            str(csv_path),
            "--target",
            str(target),
            "--dispositions",
            str(dispo),
            "--output",
            str(tmp_path / "r"),
        ]
    )
    assert code == 0
    assert csv_path.exists()


# ---------------------------------------------------------------------------
# 11. missing CSV → exit 3
# ---------------------------------------------------------------------------


def test_missing_csv_exit_3(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    code = collide.main(
        [
            "--csv",
            str(tmp_path / "does-not-exist.csv"),
            "--target",
            str(target),
            "--dispositions",
            str(tmp_path / ".pii-dispositions"),
            "--output",
            str(tmp_path / "r"),
        ]
    )
    assert code == 3


# ---------------------------------------------------------------------------
# 12. amount digit-boundary anchoring (regression: substring false positives)
# ---------------------------------------------------------------------------


def test_amount_not_matched_inside_longer_number(tmp_path: Path) -> None:
    # 200.00 must NOT match inside 3200.00; 2400.00's grouped form must still
    # match $2,400.00 exactly. Both amounts co-locate with the full-string anchor.
    rows = [
        _blank_row(Company="Zephyrwick Plumbing Supplies", Amount="200.00"),
        _blank_row(Company="Zephyrwick Plumbing Supplies", Amount="2400.00"),
    ]
    target = {
        "leak.py": (
            "vendor = 'Zephyrwick Plumbing Supplies'\n"  # line 1: full-string anchor
            "big = 3200.00\n"  # line 2: 200.00 is a substring here — must be rejected
            "grouped = $2,400.00\n"  # line 3: 2400.00 grouped form must match
        ),
    }
    code, report = _run(tmp_path, rows, target, include_matches=True)
    assert code == 1
    amount_tokens = {e["token"] for e in report["findings"] if e["token_class"] == "amount"}
    assert "2400.00" in amount_tokens, "grouped form must match $2,400.00"
    assert "200.00" not in amount_tokens, "must not match inside 3200.00"
    grouped = next(e for e in report["findings"] if e["token_class"] == "amount" and e["token"] == "2400.00")
    assert grouped["matches"][0]["line"] == 3


# ---------------------------------------------------------------------------
# 13. prefix generation — 1-char words suppressed in 2-word prefixes
# ---------------------------------------------------------------------------


def test_prefix_one_char_word_suppression(tmp_path: Path) -> None:
    rows = [
        _blank_row(Company="Q B Custom Woodworks"),
        _blank_row(Company="Custom Woodworks Fabrication Shop"),
        # Length alone would not filter "longmerchant x" (len 14 >= 7) — only the
        # 1-char-word rule does, so this proves the rule fires independent of length.
        _blank_row(Company="Longmerchant X Alpha Beta"),
    ]
    csv_path = tmp_path / "t.csv"
    _write_csv(csv_path, rows)
    reg, _ = collide.extract_tokens(csv_path, set())
    prefixes = {text for (cls, text) in reg if cls == "prefix"}

    # 2-word prefixes containing a 1-char word are not emitted.
    assert "q b" not in prefixes
    assert "longmerchant x" not in prefixes
    # A clean 2-word prefix still emits.
    assert "custom woodworks" in prefixes
    # A >= 3-word prefix emits even though it contains a 1-char word.
    assert "longmerchant x alpha" in prefixes


# ---------------------------------------------------------------------------
# 14. cross-class dedupe — full-string wins, one group per value
# ---------------------------------------------------------------------------


def test_cross_class_dedupe_full_string_wins(tmp_path: Path) -> None:
    # A single-word merchant becomes both a full-string and a same-text word token.
    # After dedupe only the full-string survives: one finding group, provenance
    # records the dropped word class.
    rows = [_blank_row(Company="Zephyrwick")]
    code, report = _run(
        tmp_path,
        rows,
        {"fixtures/leak.py": "vendor = 'Zephyrwick'\n"},
    )
    assert code == 1
    assert len(report["findings"]) == 1, "the value must collapse to a single group"
    entry = report["findings"][0]
    assert entry["token_class"] == "full-string"
    assert entry["provenance"].get("also_classes") == ["also word-class"]


# ---------------------------------------------------------------------------
# 15. summary key rename — match_lines_by_class + token_groups
# ---------------------------------------------------------------------------


def test_summary_keys_renamed(tmp_path: Path) -> None:
    rows = [_blank_row(Company="Zephyrwick Plumbing Supplies")]
    code, report = _run(
        tmp_path,
        rows,
        {"fixtures/leak.py": "vendor = 'Zephyrwick Plumbing Supplies'\n"},
    )
    assert code == 1
    # The raw-row counter is renamed; the old ambiguous name is gone.
    assert "match_lines_by_class" in report
    assert "findings_by_class" not in report
    # A separate collapsed-group count lives in the summary; it equals the number
    # of finding entries (one per token group), never the raw row count.
    assert "token_groups" in report["summary"]
    assert report["summary"]["token_groups"] == len(report["findings"])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
