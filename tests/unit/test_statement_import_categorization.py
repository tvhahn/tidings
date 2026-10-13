"""Statement import runs rows through the same tiered categorizer as email (issue #83).

`POST /statements/import` used to trust the upload-time reconciler's suggestion
verbatim, so a row whose merchant already had an override still landed as
`miscellaneous`. These tests pin the fix at both levels:

* the router — which rows get re-categorized, which are left alone, and that the
  resulting audit (tier / matched_rule / confidence) reaches the write call;
* both storage backends — that a full `category_audit` dict is persisted rather
  than a bare `build_audit(audit_source)`, and that a merchant auto-ignore rule
  fires on the statement write path the way it already does for email.

The override/ignore lookups are module-global cached reads from storage, so they
are patched at their import seam — these tests never touch real `data/` config.
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import src.finance.categorizer as categorizer_module
import src.finance.config_loader as config_module
from src.finance.transaction_db import TransactionsDB
from src.finance.transaction_db_local import TransactionsDBLocal
from tests.asserts import assert_ok

FORWARDED_TO = "test@example.com"

# A merchant the user has already pinned via an exact-match override — the
# mortgage/childcare/strata case from the issue report.
OVERRIDE_MERCHANT = "Northwind Energy Co"
OVERRIDE_CATEGORY = "utilities"


def _import_body(
    *,
    category: str,
    company: str = OVERRIDE_MERCHANT,
    statement_id: str | None = None,
) -> dict[str, Any]:
    """One-row import request; `category` is what the frontend echoes back."""
    body: dict[str, Any] = {
        "actions": [{"index": 0, "action": "import", "category": category, "company": company}],
        "metadata": {
            "institution": "RBC",
            "account_type": "chequing",
            "period_start": "2025-12-24",
            "period_end": "2026-01-23",
            "transaction_count": 1,
        },
        "transactions": [
            {
                "date": "2026-01-15",
                "description": "BillPayment WestlandUtilityCo",
                "amount": 98.75,
                "type": "withdrawal",
                "balance": 41685.40,
                "cleaned_description": company,
            },
        ],
        "filename": "test.pdf",
    }
    if statement_id:
        body["statement_id"] = statement_id
    return body


@pytest.fixture
def patch_overrides(monkeypatch: pytest.MonkeyPatch):
    """Pin the override context the categorizer resolves against."""

    def _set(overrides: dict[str, str], aliases: dict[str, str] | None = None) -> None:
        monkeypatch.setattr(categorizer_module, "get_override_context", lambda: (overrides, aliases or {}))

    return _set


@pytest.fixture
def write_calls(mock_run_sync: MagicMock) -> list[tuple[Any, ...]]:
    """Dispatch `run_sync` so the real categorizer runs and writes are captured.

    Returns the list that collects `(txn_data, audit_source, category_audit)`
    for every `add_statement_transaction` the handler attempts.
    """
    calls: list[tuple[Any, ...]] = []

    async def dispatch(func, *args: Any, **kwargs: Any) -> Any:
        name = getattr(func, "__name__", "")
        if name == "categorize_transactions":
            # Run the real tiered resolver — that's the behavior under test.
            return func(*args, **kwargs)
        if name == "add_statement_transaction":
            calls.append(args)
            return "2026.01.15_00.00_stmt_RBC_abc12345.pdf"
        return None

    mock_run_sync.side_effect = dispatch
    return calls


@pytest.fixture(autouse=True)
def no_ai_client():
    """No provider configured — isolates the override tiers from any network path."""
    with patch("src.finance.ai_client.get_ai_client", return_value=None):
        yield


# ---------------------------------------------------------------------------
# Router — which rows get re-categorized
# ---------------------------------------------------------------------------


@patch("src.api.routers.statements._append_import_history")
@patch("src.api.routers.statements._get_user_id", return_value="default")
@patch("src.api.routers.statements._get_forwarded_to", return_value=FORWARDED_TO)
@pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
class TestImportAppliesOverrides:
    def test_miscellaneous_row_picks_up_existing_override(
        self,
        mock_fwd: MagicMock,
        mock_uid: MagicMock,
        mock_history: MagicMock,
        mock_run_sync: MagicMock,
        write_calls: list[tuple[Any, ...]],
        patch_overrides,
        api_client,
    ) -> None:
        """The issue's core symptom: an overridden merchant must not land miscellaneous."""
        patch_overrides({OVERRIDE_MERCHANT: OVERRIDE_CATEGORY})

        body = assert_ok(api_client.post("/api/v1/statements/import", json=_import_body(category="miscellaneous")))
        assert body["imported"] == 1

        txn_data, audit_source, category_audit = write_calls[0]
        assert txn_data["category"] == OVERRIDE_CATEGORY
        assert audit_source == "statement_import"
        assert category_audit["source"] == "override"
        assert category_audit["tier"] == "exact"
        assert category_audit["matched_rule"] == OVERRIDE_MERCHANT

    def test_normalized_tier_override_applies(
        self,
        mock_fwd: MagicMock,
        mock_uid: MagicMock,
        mock_history: MagicMock,
        mock_run_sync: MagicMock,
        write_calls: list[tuple[Any, ...]],
        patch_overrides,
        api_client,
    ) -> None:
        """Statement rows carry store numbers email alerts don't — tier 1 must fire."""
        patch_overrides({"MiscPayment CARDCO #221": "shopping"})

        body = _import_body(category="miscellaneous", company="MiscPayment CARDCO #888")
        assert_ok(api_client.post("/api/v1/statements/import", json=body))

        _, _, category_audit = write_calls[0]
        assert write_calls[0][0]["category"] == "shopping"
        assert category_audit["tier"] == "normalized"

    def test_explicit_category_is_not_recategorized(
        self,
        mock_fwd: MagicMock,
        mock_uid: MagicMock,
        mock_history: MagicMock,
        mock_run_sync: MagicMock,
        write_calls: list[tuple[Any, ...]],
        patch_overrides,
        api_client,
    ) -> None:
        """A row the reconciler already categorized keeps that category, override or not."""
        patch_overrides({OVERRIDE_MERCHANT: OVERRIDE_CATEGORY})

        assert_ok(api_client.post("/api/v1/statements/import", json=_import_body(category="groceries")))

        txn_data, audit_source, category_audit = write_calls[0]
        assert txn_data["category"] == "groceries"
        assert audit_source == "statement_import"
        assert category_audit is None

    @pytest.mark.parametrize(
        ("ai_enabled", "expected_reason"),
        [(True, "no_client"), (False, "disabled")],
    )
    def test_no_override_leaves_row_miscellaneous_but_records_why(
        self,
        mock_fwd: MagicMock,
        mock_uid: MagicMock,
        mock_history: MagicMock,
        mock_run_sync: MagicMock,
        write_calls: list[tuple[Any, ...]],
        patch_overrides,
        monkeypatch: pytest.MonkeyPatch,
        api_client,
        ai_enabled: bool,
        expected_reason: str,
    ) -> None:
        """No override and no usable provider — the row stays miscellaneous, and says why.

        The fallback reason distinguishes "the user turned AI off" from "no
        provider is configured", which is what makes an un-categorized import
        row diagnosable instead of silently generic.
        """
        patch_overrides({})
        monkeypatch.setattr(categorizer_module, "get_config", lambda: {"ai_categorization_enabled": ai_enabled})

        assert_ok(api_client.post("/api/v1/statements/import", json=_import_body(category="miscellaneous")))

        txn_data, _, category_audit = write_calls[0]
        # The categorizer returns the display-cased fallback; storage lowercases it.
        assert txn_data["category"].lower() == "miscellaneous"
        assert category_audit["source"] == "ai_fallback"
        assert category_audit["fallback_reason"] == expected_reason


@patch("src.api.routers.statements._append_import_history")
@patch("src.api.routers.statements._get_user_id", return_value="default")
@patch("src.api.routers.statements._get_forwarded_to", return_value=FORWARDED_TO)
@pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
class TestManualPicksAreNotSecondGuessed:
    """A user who deliberately chose a category owns it — including "miscellaneous"."""

    def _with_edit(
        self, mock_run_sync: MagicMock, write_calls: list[tuple[Any, ...]], suggested: str, edited: str
    ) -> None:
        """Layer statement-row lookup (the category-edit seam) over the dispatch."""
        inner = mock_run_sync.side_effect

        async def dispatch(func, *args: Any, **kwargs: Any) -> Any:
            if getattr(func, "__name__", "") == "get_transactions":
                return [{"tx_index": 0, "suggested_category": suggested, "edited_category": edited}]
            return await inner(func, *args, **kwargs)

        mock_run_sync.side_effect = dispatch

    def test_deliberate_miscellaneous_pick_skips_the_resolver(
        self,
        mock_fwd: MagicMock,
        mock_uid: MagicMock,
        mock_history: MagicMock,
        mock_run_sync: MagicMock,
        write_calls: list[tuple[Any, ...]],
        patch_overrides,
        api_client,
    ) -> None:
        patch_overrides({OVERRIDE_MERCHANT: OVERRIDE_CATEGORY})
        self._with_edit(mock_run_sync, write_calls, suggested="groceries", edited="miscellaneous")

        body = _import_body(category="miscellaneous", statement_id="abcdef0123456789")
        assert_ok(api_client.post("/api/v1/statements/import", json=body))

        txn_data, audit_source, category_audit = write_calls[0]
        assert txn_data["category"] == "miscellaneous"
        assert audit_source == "manual"
        assert category_audit is None


@patch("src.api.routers.statements._append_import_history")
@patch("src.api.routers.statements._get_user_id", return_value="default")
@patch("src.api.routers.statements._get_forwarded_to", return_value=FORWARDED_TO)
@pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
class TestEnrichPathUntouched:
    """Acceptance: enriching an existing email transaction keeps the email-side category."""

    def test_enrich_does_not_recategorize_or_insert(
        self,
        mock_fwd: MagicMock,
        mock_uid: MagicMock,
        mock_history: MagicMock,
        mock_run_sync: MagicMock,
        patch_overrides,
        api_client,
    ) -> None:
        patch_overrides({OVERRIDE_MERCHANT: OVERRIDE_CATEGORY})
        seen: list[str] = []

        async def dispatch(func, *args: Any, **kwargs: Any) -> Any:
            seen.append(getattr(func, "__name__", ""))
            return None

        mock_run_sync.side_effect = dispatch

        body = _import_body(category="miscellaneous")
        body["actions"] = [
            {
                "index": 0,
                "action": "enrich",
                "category": "miscellaneous",
                "company": OVERRIDE_MERCHANT,
                "forwarded_to": FORWARDED_TO,
                "date_file_name": "2026.01.15_10.30_alert.eml",
            }
        ]

        result = assert_ok(api_client.post("/api/v1/statements/import", json=body))
        assert result["enriched"] == 1
        assert "categorize_transactions" not in seen
        assert "add_statement_transaction" not in seen
        assert "enrich_transaction" in seen


# ---------------------------------------------------------------------------
# Storage — the audit dict and auto-ignore reach both backends
# ---------------------------------------------------------------------------


def _stmt_txn(**overrides: Any) -> dict[str, Any]:
    data = {
        "forwarded_to": FORWARDED_TO,
        "date": "2026-01-15",
        "amount": 98.75,
        "company": OVERRIDE_MERCHANT,
        "raw_description": "BillPayment WestlandUtilityCo",
        "institution": "RBC",
        "transaction_type": "withdrawal",
        "category": OVERRIDE_CATEGORY,
        "statement_source": "RBC_Chequing_2026-01",
    }
    data.update(overrides)
    return data


def _override_audit() -> dict[str, Any]:
    from src.finance.category_audit import build_audit

    return build_audit("override", tier="exact", matched_rule=OVERRIDE_MERCHANT, confidence=1.0)


@pytest.fixture
def patch_ignore_rules(monkeypatch: pytest.MonkeyPatch):
    """Pin the ignore-rule context the statement write path resolves against."""

    def _set(patterns: list[str], aliases: dict[str, str] | None = None) -> None:
        monkeypatch.setattr(config_module, "get_ignore_context", lambda: (patterns, aliases or {}))

    return _set


class TestSqliteStatementWrite:
    @pytest.fixture
    def db(self, tmp_path: Path) -> TransactionsDBLocal:
        return TransactionsDBLocal(db_path=tmp_path / "t.db")

    def test_full_category_audit_is_persisted(self, db: TransactionsDBLocal, patch_ignore_rules) -> None:
        patch_ignore_rules([])
        dfn = db.add_statement_transaction(_stmt_txn(), "statement_import", _override_audit())
        assert isinstance(dfn, str)

        audit = db.get_item(FORWARDED_TO, dfn)["CategoryAudit"]
        assert audit["source"] == "override"
        assert audit["tier"] == "exact"
        assert audit["matched_rule"] == OVERRIDE_MERCHANT
        assert float(audit["confidence"]) == 1.0

    def test_bare_audit_source_still_works(self, db: TransactionsDBLocal, patch_ignore_rules) -> None:
        patch_ignore_rules([])
        dfn = db.add_statement_transaction(_stmt_txn())
        assert isinstance(dfn, str)

        audit = db.get_item(FORWARDED_TO, dfn)["CategoryAudit"]
        assert audit["source"] == "statement_import"
        assert audit.get("tier") is None

    def test_ignore_rule_match_arrives_ignored(self, db: TransactionsDBLocal, patch_ignore_rules) -> None:
        patch_ignore_rules(["MiscPayment CARDCO #221"])
        dfn = db.add_statement_transaction(_stmt_txn(company="MiscPayment CARDCO #888"))
        assert isinstance(dfn, str)
        assert db.get_item(FORWARDED_TO, dfn)["Ignored"] is True

    def test_non_matching_row_is_not_ignored(self, db: TransactionsDBLocal, patch_ignore_rules) -> None:
        patch_ignore_rules(["MiscPayment CARDCO #221"])
        dfn = db.add_statement_transaction(_stmt_txn())
        assert isinstance(dfn, str)
        assert db.get_item(FORWARDED_TO, dfn).get("Ignored", False) is False


class TestDynamoStatementWrite:
    @pytest.fixture
    def db_and_table(self) -> tuple[TransactionsDB, MagicMock]:
        table = MagicMock(name="table")
        table.query.return_value = {"Count": 0, "Items": []}
        table.put_item.return_value = {}
        dyn = MagicMock()
        dyn.Table.return_value = table
        return TransactionsDB(dyn), table

    def test_full_category_audit_is_persisted(
        self, db_and_table: tuple[TransactionsDB, MagicMock], patch_ignore_rules
    ) -> None:
        patch_ignore_rules([])
        db, table = db_and_table
        assert isinstance(db.add_statement_transaction(_stmt_txn(), "statement_import", _override_audit()), str)

        audit = table.put_item.call_args[1]["Item"]["CategoryAudit"]
        assert audit["source"] == "override"
        assert audit["tier"] == "exact"
        assert audit["matched_rule"] == OVERRIDE_MERCHANT

    def test_bare_audit_source_still_works(
        self, db_and_table: tuple[TransactionsDB, MagicMock], patch_ignore_rules
    ) -> None:
        patch_ignore_rules([])
        db, table = db_and_table
        assert isinstance(db.add_statement_transaction(_stmt_txn()), str)

        audit = table.put_item.call_args[1]["Item"]["CategoryAudit"]
        assert audit["source"] == "statement_import"
        assert "tier" not in audit

    def test_ignore_rule_match_arrives_ignored(
        self, db_and_table: tuple[TransactionsDB, MagicMock], patch_ignore_rules
    ) -> None:
        patch_ignore_rules(["MiscPayment CARDCO #221"])
        db, table = db_and_table
        assert isinstance(db.add_statement_transaction(_stmt_txn(company="MiscPayment CARDCO #888")), str)
        assert table.put_item.call_args[1]["Item"]["Ignored"] is True

    def test_non_matching_row_omits_ignored(
        self, db_and_table: tuple[TransactionsDB, MagicMock], patch_ignore_rules
    ) -> None:
        patch_ignore_rules(["MiscPayment CARDCO #221"])
        db, table = db_and_table
        assert isinstance(db.add_statement_transaction(_stmt_txn()), str)
        assert "Ignored" not in table.put_item.call_args[1]["Item"]
