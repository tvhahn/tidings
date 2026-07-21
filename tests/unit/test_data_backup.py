"""Tests for data_backup — zip pack/unpack, CSV round-trip, dedup, staging."""

from __future__ import annotations

import io
import json
import zipfile
from typing import TYPE_CHECKING, Any

import pytest

from src.finance import backup_export, backup_import, staging_store
from src.finance.transaction_db_local import TransactionsDBLocal
from src.finance.transaction_hash import bump_hash_occurrence, generate_transaction_hash
from tests.factories import make_transaction_item

if TYPE_CHECKING:
    from pathlib import Path

    from src.finance.transaction_db_base import ImportStrategy

FORWARDED_TO = "user@example.com"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _txn_item(**overrides: Any) -> dict[str, Any]:
    """DynamoDB/row_to_item-shaped PascalCase item (the export format).

    Delegates the shared transaction shape to ``make_transaction_item`` and layers
    on the backup-export-specific fields (Comment, Ignored, CategoryAudit) plus
    this module's fixture values (a stable DateFileName/TransactionHash and a
    dollar-bearing Body). Overrides are applied last.
    """
    base = make_transaction_item(
        DateFileName="2026.02.15_10.30_a.eml",
        TransactionHash="hash-abc",
        Body="You spent $42.50",
        FileName="test.eml",
        Comment="Test comment",
        Ignored=False,
        CategoryAudit={"source": "manual_edit", "reviewed_at": "2026-02-20T10:00:00Z"},
    )
    base.update(overrides)
    return base


def _add_fixture(db: TransactionsDBLocal, **overrides: Any) -> Any:
    """Seed a transaction via the ingest path."""
    txn = {
        "forwarded_to": FORWARDED_TO,
        "file_name": "test.eml",
        "date": "02/15/2026 10:30 PST",
        "amount": 42.50,
        "company": "Test Store",
        "category": "groceries",
        "institution": "RBC",
        "transaction_type": "purchase",
        "subject": "Original",
        "body": "Original body",
    }
    txn.update(overrides)
    return db.add_transaction(txn)


@pytest.fixture
def local_db(tmp_path: Path) -> TransactionsDBLocal:
    return TransactionsDBLocal(db_path=tmp_path / "test.db")


@pytest.fixture(autouse=True)
def _use_tmp_stage_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(staging_store, "_STAGE_DIR", tmp_path / "imports")


# ---------------------------------------------------------------------------
# build_backup_zip
# ---------------------------------------------------------------------------


class TestBuildBackupZip:
    def test_contains_manifest_and_transactions(self):
        payload = backup_export.build_backup_zip(
            transactions=[_txn_item()],
            categories=["groceries", "rent"],
            overrides={"Starbucks": "restaurant/dining"},
            merchant_aliases={"sbux": "Starbucks"},
            budgets={"2026": {"targets": {}, "groups": {}}},
            storage_backend="sqlite",
        )
        zf = zipfile.ZipFile(io.BytesIO(payload))
        names = set(zf.namelist())
        assert backup_import.MANIFEST_FILENAME in names
        assert backup_import.TRANSACTIONS_FILENAME in names
        assert "config/categories.json" in names
        assert "config/overrides.json" in names
        assert "config/merchant_aliases.json" in names
        assert "config/budgets.json" in names

    def test_manifest_records_counts(self):
        payload = backup_export.build_backup_zip(
            transactions=[_txn_item(), _txn_item(DateFileName="2026.02.16_10.30_b.eml")],
            categories=["groceries"],
            overrides={"a": "b"},
            merchant_aliases={"c": "d"},
            budgets={"2026": {}},
            storage_backend="dynamodb",
        )
        zf = zipfile.ZipFile(io.BytesIO(payload))
        manifest = json.loads(zf.read(backup_import.MANIFEST_FILENAME))
        assert manifest["version"] == backup_import.MANIFEST_VERSION
        assert manifest["storage_backend"] == "dynamodb"
        assert manifest["counts"]["transactions"] == 2
        assert manifest["counts"]["categories"] == 1

    def test_omits_config_files_when_none(self):
        payload = backup_export.build_backup_zip(
            transactions=[_txn_item()],
            categories=None,
            overrides=None,
            merchant_aliases=None,
            budgets=None,
            storage_backend="sqlite",
        )
        zf = zipfile.ZipFile(io.BytesIO(payload))
        assert not any(n.startswith("config/") for n in zf.namelist())

    def test_csv_has_backup_columns(self):
        payload = backup_export.build_backup_zip(
            transactions=[_txn_item()],
            categories=None,
            overrides=None,
            merchant_aliases=None,
            budgets=None,
            storage_backend="sqlite",
        )
        zf = zipfile.ZipFile(io.BytesIO(payload))
        csv_text = zf.read(backup_import.TRANSACTIONS_FILENAME).decode()
        header = csv_text.splitlines()[0]
        # Sanity-check: superset of the Search-tab export
        assert "Date" in header
        assert "TransactionHash" in header
        assert "CategoryAuditSource" in header
        assert "Subject" in header
        assert "Body" in header


# ---------------------------------------------------------------------------
# parse_upload
# ---------------------------------------------------------------------------


class TestParseUpload:
    def test_parse_backup_zip_round_trip(self):
        payload = backup_export.build_backup_zip(
            transactions=[_txn_item()],
            categories=["groceries"],
            overrides={"X": "Y"},
            merchant_aliases=None,
            budgets=None,
            storage_backend="sqlite",
        )
        parsed = backup_import.parse_upload("backup.zip", payload, default_forwarded_to=FORWARDED_TO)
        assert parsed.source_kind == "backup_zip"
        assert len(parsed.transactions) == 1
        assert parsed.invalid_rows == []
        assert parsed.config is not None
        assert parsed.config.categories == ["groceries"]
        assert parsed.config.overrides == {"X": "Y"}

    def test_parse_plain_csv(self):
        csv_text = (
            '"Date","Amount","Company","Category","Institution","Type","Name","Comment","Statement Source","Ignored"\n'
            '"02/15/2026 10:30","42.50","Test Store","groceries","RBC","purchase","Alice","","","false"\n'
        )
        parsed = backup_import.parse_upload("tx.csv", csv_text.encode("utf-8"), default_forwarded_to=FORWARDED_TO)
        assert parsed.source_kind == "plain_csv"
        assert parsed.config is None
        assert len(parsed.transactions) == 1
        row = parsed.transactions[0]
        assert row["forwarded_to"] == FORWARDED_TO
        assert row["amount"] == 42.50
        # file_name synthesized from hash
        assert row["file_name"].startswith("imported_")

    def test_rejects_unsupported_extension(self):
        with pytest.raises(ValueError, match="Unsupported file type"):
            backup_import.parse_upload("foo.tar", b"", default_forwarded_to=FORWARDED_TO)

    def test_rejects_corrupt_zip(self):
        with pytest.raises(ValueError, match="zip"):
            backup_import.parse_upload("foo.zip", b"not a zip", default_forwarded_to=FORWARDED_TO)

    def test_rejects_zip_without_transactions_csv(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("other.json", "{}")
        with pytest.raises(ValueError, match=r"transactions\.csv"):
            backup_import.parse_upload("bad.zip", buf.getvalue(), default_forwarded_to=FORWARDED_TO)

    def test_invalid_rows_surfaced_separately(self):
        csv_text = (
            '"Date","Amount","Company"\n'
            '"","bad","Test"\n'  # missing date → invalid
            '"02/15/2026 10:30","42.50","Test Store"\n'
        )
        parsed = backup_import.parse_upload("tx.csv", csv_text.encode(), default_forwarded_to=FORWARDED_TO)
        assert len(parsed.transactions) == 1
        assert len(parsed.invalid_rows) == 1
        assert parsed.invalid_rows[0]["row_number"] == 2

    def test_preserves_category_audit(self):
        csv_text = (
            '"Date","Amount","Company","Category","Institution","Type","Name","Comment","Statement Source","Ignored","ForwardedTo","DateFileName","TransactionHash","CategoryAuditSource","CategoryAuditReviewedAt","CategoryAuditMatchedRule","CategoryAuditConfidence"\n'
            '"02/15/2026 10:30","42.50","Test Store","groceries","RBC","purchase","","","","false","user@example.com","2026.02.15_10.30_a.eml","h1","manual_edit","2026-02-20T10:00:00Z","rule-a","0.95"\n'
        )
        parsed = backup_import.parse_upload("tx.csv", csv_text.encode(), default_forwarded_to=FORWARDED_TO)
        row = parsed.transactions[0]
        audit = row["_category_audit"]
        assert audit["source"] == "manual_edit"
        assert audit["matched_rule"] == "rule-a"
        assert audit["confidence"] == 0.95

    def test_preserves_category_audit_v2_fields(self):
        # Full v2 backup CSV with all new audit columns.
        csv_text = (
            '"Date","Amount","Company","Category","Institution","Type","Name","Comment","Statement Source","Ignored",'
            '"ForwardedTo","DateFileName","TransactionHash",'
            '"CategoryAuditSource","CategoryAuditReviewedAt","CategoryAuditMatchedRule","CategoryAuditConfidence",'
            '"CategoryAuditTier","CategoryAuditPreviousCategory","CategoryAuditPreviousSource",'
            '"CategoryAuditModel","CategoryAuditFallbackReason","CategoryAuditSchemaVersion"\n'
            '"02/15/2026 10:30","42.50","Test Store","groceries","RBC","purchase","","","","false",'
            '"user@example.com","2026.02.15_10.30_a.eml","h1",'
            '"override","2026-02-20T10:00:00-08:00","rule-a","1.0",'
            '"alias","miscellaneous","ai_fallback",'
            '"gpt-5.4-nano","","2"\n'
        )
        parsed = backup_import.parse_upload("tx.csv", csv_text.encode(), default_forwarded_to=FORWARDED_TO)
        audit = parsed.transactions[0]["_category_audit"]
        assert audit["source"] == "override"
        assert audit["tier"] == "alias"
        assert audit["previous_category"] == "miscellaneous"
        assert audit["previous_source"] == "ai_fallback"
        assert audit["model"] == "gpt-5.4-nano"
        assert "fallback_reason" not in audit  # blank cell is skipped
        assert audit["schema_version"] == 2

    def test_parses_legacy_4_column_audit_header(self):
        """A legacy backup written before v2 columns existed still imports cleanly."""
        csv_text = (
            '"Date","Amount","Company","Category","Institution","Type","Name","Comment","Statement Source","Ignored",'
            '"ForwardedTo","DateFileName","TransactionHash",'
            '"CategoryAuditSource","CategoryAuditReviewedAt","CategoryAuditMatchedRule","CategoryAuditConfidence"\n'
            '"02/15/2026 10:30","42.50","Test Store","groceries","RBC","purchase","","","","false",'
            '"user@example.com","2026.02.15_10.30_a.eml","h1",'
            '"override_normalized","2026-02-20T10:00:00Z","rule-a","1.0"\n'
        )
        parsed = backup_import.parse_upload("tx.csv", csv_text.encode(), default_forwarded_to=FORWARDED_TO)
        audit = parsed.transactions[0]["_category_audit"]
        # Legacy source preserved on import; normalize_audit at API-read time
        # is what flattens it into the v2 shape.
        assert audit["source"] == "override_normalized"
        assert "tier" not in audit
        assert audit["matched_rule"] == "rule-a"


# ---------------------------------------------------------------------------
# Decompression-size cap on zip members (zip-bomb defense)
# ---------------------------------------------------------------------------


class TestMemberDecompressionCap:
    """A crafted backup zip must not be able to expand to unbounded memory.

    The per-member ceiling (`_MAX_MEMBER_DECOMPRESSED_BYTES`) is patched down to
    a few KB so the tests stay fast — the real 256 MiB constant would require
    building enormous fixtures to exercise.
    """

    def _make_backup_zip(self, csv_body: bytes) -> bytes:
        """A minimal-but-valid backup zip with the given transactions.csv bytes."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                backup_import.MANIFEST_FILENAME,
                json.dumps({"version": backup_import.MANIFEST_VERSION}),
            )
            zf.writestr(backup_import.TRANSACTIONS_FILENAME, csv_body)
        return buf.getvalue()

    def test_oversized_member_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Highly compressible payload: 1 MiB of a single byte deflates tiny but
        # decompresses well past the patched 4 KB cap.
        monkeypatch.setattr(backup_import, "_MAX_MEMBER_DECOMPRESSED_BYTES", 4 * 1024)
        payload = self._make_backup_zip(b"A" * (1024 * 1024))
        with pytest.raises(ValueError, match="too large to import"):
            backup_import.parse_upload("bomb.zip", payload, default_forwarded_to=FORWARDED_TO)

    def test_lying_header_rejected_mid_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A stub is used deliberately: a real ZipFile always writes a truthful
        # `file_size` header, so the fast reject fires first and the chunked
        # mid-read abort branch — which exists precisely because crafted zips can
        # lie — is unreachable through real zip bytes (forging them would add
        # needless complexity). This duck-typed fake claims a tiny 10-byte member
        # while streaming 64 KiB, forcing the read loop to catch the overflow.
        class _LyingMember:
            def getinfo(self, name: str) -> zipfile.ZipInfo:
                info = zipfile.ZipInfo(name)
                info.file_size = 10  # lie: far under the patched cap
                return info

            def open(self, name: str) -> io.BytesIO:
                return io.BytesIO(b"B" * (64 * 1024))  # truth: 64 KiB stream

        monkeypatch.setattr(backup_import, "_MAX_MEMBER_DECOMPRESSED_BYTES", 1024)
        with pytest.raises(ValueError, match="too large to import"):
            backup_import._read_member_capped(_LyingMember(), backup_import.TRANSACTIONS_FILENAME)  # type: ignore[arg-type]

    def test_normal_backup_passes_through_capped_reader(self) -> None:
        # A real export at the default 256 MiB cap parses cleanly through the
        # new reader — the green path guarding against an over-tight ceiling.
        payload = backup_export.build_backup_zip(
            transactions=[_txn_item()],
            categories=["groceries"],
            overrides={"X": "Y"},
            merchant_aliases=None,
            budgets=None,
            storage_backend="sqlite",
        )
        parsed = backup_import.parse_upload("backup.zip", payload, default_forwarded_to=FORWARDED_TO)
        assert parsed.source_kind == "backup_zip"
        assert len(parsed.transactions) == 1
        assert parsed.config is not None
        assert parsed.config.categories == ["groceries"]


# ---------------------------------------------------------------------------
# classify_duplicates + bulk_add_transactions (dedup strategies)
# ---------------------------------------------------------------------------


class TestDedupStrategies:
    def _import_rows(self, local_db: TransactionsDBLocal, strategy: ImportStrategy) -> dict[str, int]:
        # One duplicate of an existing row + one brand-new row.
        rows = [
            {
                "forwarded_to": FORWARDED_TO,
                "file_name": "reimport.eml",
                "date": "02/15/2026 10:30 PST",
                "amount": 42.50,
                "company": "Test Store",
                "category": "restaurant/dining",  # changed
                "institution": "RBC",
                "transaction_type": "purchase",
                "subject": "Imported subject",
                "comment": "imported comment",
                "_category_audit": {"source": "imported", "reviewed_at": "2026-03-01T00:00:00Z"},
            },
            {
                "forwarded_to": FORWARDED_TO,
                "file_name": "new.eml",
                "date": "02/16/2026 10:30 PST",
                "amount": 100.00,
                "company": "New Store",
                "category": "groceries",
                "institution": "RBC",
                "transaction_type": "purchase",
            },
        ]
        return local_db.bulk_add_transactions(rows, strategy=strategy)

    def test_skip_leaves_existing_untouched(self, local_db: TransactionsDBLocal):
        _add_fixture(local_db)
        counts = self._import_rows(local_db, "skip")
        assert counts == {"inserted": 1, "updated": 0, "skipped": 1, "invalid": 0, "errors": 0}
        # Original row still has its original category.
        existing_hash = generate_transaction_hash(
            {
                "forwarded_to": FORWARDED_TO,
                "institution": "RBC",
                "amount": 42.50,
                "company": "Test Store",
                "date": "02/15/2026 10:30 PST",
                "transaction_type": "purchase",
            }
        )
        dfn = local_db.find_date_file_name_by_hash(FORWARDED_TO, existing_hash)
        assert dfn is not None
        item = local_db.get_item(FORWARDED_TO, dfn)
        assert item is not None
        assert item["Category"] == "groceries"

    def test_overwrite_replaces_existing(self, local_db: TransactionsDBLocal):
        _add_fixture(local_db)
        counts = self._import_rows(local_db, "overwrite")
        assert counts == {"inserted": 1, "updated": 1, "skipped": 0, "invalid": 0, "errors": 0}
        # The replaced row takes the imported category + comment.
        h = generate_transaction_hash(
            {
                "forwarded_to": FORWARDED_TO,
                "institution": "RBC",
                "amount": 42.50,
                "company": "Test Store",
                "date": "02/15/2026 10:30 PST",
                "transaction_type": "purchase",
            }
        )
        dfn = local_db.find_date_file_name_by_hash(FORWARDED_TO, h)
        assert dfn is not None
        item = local_db.get_item(FORWARDED_TO, dfn)
        assert item is not None
        assert item["Category"] == "restaurant/dining"
        assert item["Comment"] == "imported comment"
        assert item["Subject"] == "Imported subject"

    def test_keep_both_creates_second_row(self, local_db: TransactionsDBLocal):
        _add_fixture(local_db)
        counts = self._import_rows(local_db, "keep_both")
        assert counts == {"inserted": 2, "updated": 0, "skipped": 0, "invalid": 0, "errors": 0}

        # Original row: plain hash.
        base_h = generate_transaction_hash(
            {
                "forwarded_to": FORWARDED_TO,
                "institution": "RBC",
                "amount": 42.50,
                "company": "Test Store",
                "date": "02/15/2026 10:30 PST",
                "transaction_type": "purchase",
            }
        )
        assert local_db.find_date_file_name_by_hash(FORWARDED_TO, base_h)

        # Duplicate: occurrence-bumped hash.
        occ_h = bump_hash_occurrence(base_h, 1)
        assert local_db.find_date_file_name_by_hash(FORWARDED_TO, occ_h)

    def test_invalid_rows_counted(self, local_db: TransactionsDBLocal):
        rows = [
            {"forwarded_to": FORWARDED_TO, "file_name": "x.eml", "date": "02/15/2026 10:30 PST"},
            # missing amount + company
        ]
        counts = local_db.bulk_add_transactions(rows, strategy="skip")
        assert counts["invalid"] == 1
        assert counts["inserted"] == 0


# ---------------------------------------------------------------------------
# classify_duplicates
# ---------------------------------------------------------------------------


class TestClassifyDuplicates:
    def test_identifies_matching_hashes(self, local_db: TransactionsDBLocal):
        _add_fixture(local_db)
        parsed = backup_import.parse_upload(
            "tx.csv",
            (
                b'"Date","Amount","Company","Category","Institution","Type","Name","Comment","Statement Source","Ignored"\n'
                b'"02/15/2026 10:30","42.50","Test Store","groceries","RBC","purchase","","","","false"\n'
                b'"02/16/2026 10:30","100.00","Fresh Row","groceries","RBC","purchase","","","","false"\n'
            ),
            default_forwarded_to=FORWARDED_TO,
        )
        dup_hashes = backup_import.classify_duplicates(local_db, parsed.transactions)
        assert len(dup_hashes) == 1


# ---------------------------------------------------------------------------
# Staging
# ---------------------------------------------------------------------------


class TestStaging:
    def test_round_trip(self):
        parsed = backup_import.ParsedUpload(
            filename="backup.zip",
            source_kind="backup_zip",
            transactions=[{"forwarded_to": FORWARDED_TO, "amount": 10.0}],
            invalid_rows=[],
            duplicate_hashes=[],
            config=backup_import.ParsedConfig(categories=["a"]),
        )
        token = staging_store.stage(parsed)
        loaded = staging_store.load(token)
        assert loaded is not None
        assert loaded.filename == "backup.zip"
        assert loaded.transactions[0]["amount"] == 10.0
        assert loaded.config is not None
        assert loaded.config.categories == ["a"]

    def test_expired_token_returns_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(staging_store, "_STAGE_TTL_SECONDS", 0)
        parsed = backup_import.ParsedUpload(filename="x.zip", source_kind="backup_zip")
        token = staging_store.stage(parsed)
        # With TTL=0, any file is instantly expired.
        import time

        time.sleep(0.01)
        assert staging_store.load(token) is None

    def test_invalid_token(self):
        assert staging_store.load("not-a-valid-token") is None

    def test_delete_removes_file(self):
        parsed = backup_import.ParsedUpload(filename="x.zip", source_kind="backup_zip")
        token = staging_store.stage(parsed)
        staging_store.delete(token)
        assert staging_store.load(token) is None


class TestReattachConfiguredTz:
    """The export strips the tz token; restore must reattach the CONFIGURED
    zone, not a hardcoded " PST" (which shifted non-Pacific installs' rows
    by the Pacific offset in configured-zone conversions)."""

    @pytest.fixture
    def isolated_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        import src.finance.app_config as app_config

        tmp_config = tmp_path / "config.json"
        monkeypatch.setattr(app_config, "_CONFIG_PATH", tmp_config)
        app_config.invalidate_config_cache()
        yield tmp_config
        app_config.invalidate_config_cache()

    def _set_timezone(self, config_path: Path, tz_name: str) -> None:
        import json as json_mod

        import src.finance.app_config as app_config

        config_path.write_text(json_mod.dumps({"timezone": tz_name}))
        app_config.invalidate_config_cache()

    def test_default_pacific_stamps_pst_in_winter(self, isolated_config: Path) -> None:
        from src.finance.backup_import import _reattach_configured_tz

        assert _reattach_configured_tz("02/15/2026 10:30") == "02/15/2026 10:30 PST"

    def test_default_pacific_stamps_pdt_in_summer(self, isolated_config: Path) -> None:
        from src.finance.backup_import import _reattach_configured_tz

        assert _reattach_configured_tz("07/15/2026 10:30") == "07/15/2026 10:30 PDT"

    def test_berlin_config_stamps_cet(self, isolated_config: Path) -> None:
        from src.finance.backup_import import _reattach_configured_tz

        self._set_timezone(isolated_config, "Europe/Berlin")
        assert _reattach_configured_tz("02/15/2026 10:30") == "02/15/2026 10:30 CET"
        assert _reattach_configured_tz("07/15/2026 10:30") == "07/15/2026 10:30 CEST"

    def test_berlin_round_trip_parses_back_to_berlin_wall_time(self, isolated_config: Path) -> None:
        """The stamped token must be parsable via get_tzinfos() and preserve
        the exported wall-clock time in the configured zone."""
        from dateutil.parser import parse as parse_date

        from src.finance.app_timezone import get_tzinfos
        from src.finance.backup_import import _reattach_configured_tz

        self._set_timezone(isolated_config, "Europe/Berlin")
        stamped = _reattach_configured_tz("02/15/2026 10:30")
        parsed = parse_date(stamped, tzinfos=get_tzinfos())
        assert parsed.tzinfo is not None
        assert (parsed.hour, parsed.minute) == (10, 30)
        assert parsed.utcoffset().total_seconds() == 3600  # CET = UTC+1

    def test_unparsable_date_passes_through(self, isolated_config: Path) -> None:
        from src.finance.backup_import import _reattach_configured_tz

        assert _reattach_configured_tz("02/30/2026 99:99") == "02/30/2026 99:99"


# ---------------------------------------------------------------------------
# Backup export → import timezone round-trip (Plan 001)
# ---------------------------------------------------------------------------


# (IANA zone, date string carrying that zone's strftime("%Z") token).
# Winter dates render the standard abbreviation, summer the DST one; the pairs
# are chosen so a round-trip through the configured zone reproduces the exact
# same token. Covers Pacific/Eastern (the only zones the old hardcoded regex
# knew) plus Mountain/Central/Atlantic/Newfoundland — a large share of this
# Canadian-bank product's audience.
_ROUND_TRIP_ZONES = [
    ("America/Los_Angeles", "01/15/2026 10:30 PST"),
    ("America/Los_Angeles", "07/15/2026 10:30 PDT"),
    ("America/New_York", "01/15/2026 10:30 EST"),
    ("America/Denver", "01/15/2026 10:30 MST"),
    ("America/Denver", "07/15/2026 10:30 MDT"),
    ("America/Chicago", "01/15/2026 10:30 CST"),
    ("America/Halifax", "01/15/2026 10:30 AST"),
    ("America/St_Johns", "01/15/2026 10:30 NST"),
]


class TestBackupTimezoneRoundTrip:
    """Backup export strips the tz token and import reattaches the configured
    zone. Both ends must recognize *every* zone token, not just Pacific/Eastern
    — otherwise a non-Pacific/Eastern self-hoster's dates survive export
    un-stripped, get double-stamped on import (e.g. "MST MDT"), and the changed
    date string re-keys the dedup hash so restore duplicates every row.
    """

    @pytest.fixture
    def isolated_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        import src.finance.app_config as app_config

        tmp_config = tmp_path / "config.json"
        monkeypatch.setattr(app_config, "_CONFIG_PATH", tmp_config)
        app_config.invalidate_config_cache()
        yield tmp_config
        app_config.invalidate_config_cache()

    def _set_timezone(self, config_path: Path, tz_name: str) -> None:
        import json as json_mod

        import src.finance.app_config as app_config

        config_path.write_text(json_mod.dumps({"timezone": tz_name}))
        app_config.invalidate_config_cache()

    def _export_then_import(self, date_str: str) -> dict[str, Any]:
        """Run one item through backup CSV export and back through import,
        returning the single normalized row."""
        from src.api.routers.search import _generate_csv

        item = make_transaction_item(Date=date_str)
        csv_text = "".join(_generate_csv([item], flavor="backup"))
        parsed = backup_import.parse_upload("backup.csv", csv_text.encode("utf-8"), default_forwarded_to=FORWARDED_TO)
        assert parsed.invalid_rows == []
        assert len(parsed.transactions) == 1
        return parsed.transactions[0]

    @staticmethod
    def _hash_of_date(date_str: str) -> str:
        return generate_transaction_hash(
            {
                "forwarded_to": FORWARDED_TO,
                "institution": "RBC",
                "amount": 42.50,
                "company": "Test Store",
                "date": date_str,
                "transaction_type": "purchase",
            }
        )

    @pytest.mark.parametrize(("tz_name", "date_str"), _ROUND_TRIP_ZONES)
    def test_round_trip_preserves_date_and_hash(self, isolated_config: Path, tz_name: str, date_str: str) -> None:
        """Per zone family: the exported→imported date string is byte-identical
        and the dedup hash is unchanged, so restore never duplicates rows."""
        self._set_timezone(isolated_config, tz_name)
        row = self._export_then_import(date_str)
        assert row["date"] == date_str
        assert generate_transaction_hash(row) == self._hash_of_date(date_str)

    def test_non_pacific_token_is_not_double_stamped(self, isolated_config: Path) -> None:
        """A date already carrying a non-Pacific/Eastern token must never be
        reattached again — no "MST MDT"."""
        self._set_timezone(isolated_config, "America/Denver")
        csv_text = (
            '"Date","Amount","Company","Category","Institution","Type","Name","Comment","Statement Source","Ignored"\n'
            '"07/15/2026 10:30 MST","42.50","Test Store","groceries","RBC","purchase","","","","false"\n'
        )
        parsed = backup_import.parse_upload("tx.csv", csv_text.encode("utf-8"), default_forwarded_to=FORWARDED_TO)
        assert parsed.transactions[0]["date"] == "07/15/2026 10:30 MST"

    def test_legacy_no_token_still_gets_configured_zone(self, isolated_config: Path) -> None:
        """A stripped CSV with no zone token still gets the configured zone
        reattached (current behavior, must not regress)."""
        # Default Pacific config (no timezone key written).
        csv_text = (
            '"Date","Amount","Company","Category","Institution","Type","Name","Comment","Statement Source","Ignored"\n'
            '"01/15/2026 10:30","42.50","Test Store","groceries","RBC","purchase","","","","false"\n'
        )
        parsed = backup_import.parse_upload("tx.csv", csv_text.encode("utf-8"), default_forwarded_to=FORWARDED_TO)
        assert parsed.transactions[0]["date"] == "01/15/2026 10:30 PST"

    def test_numeric_offset_round_trip_preserves_date_and_hash(self, isolated_config: Path) -> None:
        """Numeric-offset zones round-trip losslessly too. A "+04" token must
        SURVIVE the CSV export unstripped — reattaching it via the configured
        zone would render "+0400" (strftime "%z"), a different string that
        changes the dedup hash — and the import guard must recognize it and not
        reattach. Same date-string + hash identity as the alphabetic families."""
        from src.api.routers.search import _generate_csv

        self._set_timezone(isolated_config, "Asia/Dubai")
        date_str = "01/15/2026 10:30 +04"
        item = make_transaction_item(Date=date_str)
        csv_text = "".join(_generate_csv([item], flavor="backup"))
        # Export leaves the numeric token in place (unlike alphabetic tokens,
        # which _strip_tz removes because reattach reproduces them exactly).
        assert f'"{date_str}"' in csv_text
        parsed = backup_import.parse_upload("backup.csv", csv_text.encode("utf-8"), default_forwarded_to=FORWARDED_TO)
        row = parsed.transactions[0]
        assert row["date"] == date_str
        assert generate_transaction_hash(row) == self._hash_of_date(date_str)
