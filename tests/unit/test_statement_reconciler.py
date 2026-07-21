"""Tests for the statement reconciler three-tier matching engine."""

from unittest.mock import MagicMock, patch

from src.finance.statement_reconciler import reconcile
from tests.factories import make_db_item as _make_db_item
from tests.factories import make_stmt_txn as _make_stmt_txn


@patch("src.finance.statement_reconciler.get_category_overrides", return_value={})
class TestTier1ExactMatch:
    def test_exact_match(self, mock_overrides: MagicMock) -> None:
        db_item = _make_db_item("2026-01-15", 50.0, "GROCERY STORE", "purchase")
        summary = MagicMock()
        summary.query_month.return_value = [db_item]

        txns = [_make_stmt_txn("2026-01-15", 50.0, "withdrawal")]
        result = reconcile(
            txns,
            ["Grocery Store"],
            ["InteracPurchase GROCERY STORE"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )

        assert len(result.matched) == 1
        assert len(result.ambiguous) == 0
        assert len(result.new) == 0
        assert result.matched[0].db_item is db_item

    def test_company_differs_flag(self, mock_overrides: MagicMock) -> None:
        db_item = _make_db_item("2026-01-15", 50.0, "WESTLANDUTILITYCO", "purchase")
        summary = MagicMock()
        summary.query_month.return_value = [db_item]

        txns = [_make_stmt_txn("2026-01-15", 50.0, "withdrawal")]
        result = reconcile(
            txns,
            ["Westland Utility Co"],
            ["BillPayment WestlandUtilityCo"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )

        assert len(result.matched) == 1
        assert result.matched[0].company_differs is True

    def test_company_matches_no_flag(self, mock_overrides: MagicMock) -> None:
        db_item = _make_db_item("2026-01-15", 50.0, "grocery store", "purchase")
        summary = MagicMock()
        summary.query_month.return_value = [db_item]

        txns = [_make_stmt_txn("2026-01-15", 50.0, "withdrawal")]
        result = reconcile(
            txns,
            ["Grocery Store"],
            ["InteracPurchase GROCERY STORE"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )

        assert result.matched[0].company_differs is False


@patch("src.finance.statement_reconciler.get_category_overrides", return_value={})
class TestTier2FuzzyMatch:
    def test_date_off_by_1_day(self, mock_overrides: MagicMock) -> None:
        db_item = _make_db_item("2026-01-16", 50.0, "STORE", "purchase")
        summary = MagicMock()
        summary.query_month.return_value = [db_item]

        txns = [_make_stmt_txn("2026-01-15", 50.0, "withdrawal")]
        result = reconcile(
            txns,
            ["Store"],
            ["Store"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )

        assert len(result.ambiguous) == 1
        assert "1 day" in result.ambiguous[0].reason

    def test_date_off_by_2_days(self, mock_overrides: MagicMock) -> None:
        db_item = _make_db_item("2026-01-17", 50.0, "STORE", "purchase")
        summary = MagicMock()
        summary.query_month.return_value = [db_item]

        txns = [_make_stmt_txn("2026-01-15", 50.0, "withdrawal")]
        result = reconcile(
            txns,
            ["Store"],
            ["Store"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )

        assert len(result.ambiguous) == 1
        assert "2 days" in result.ambiguous[0].reason


@patch("src.finance.statement_reconciler.get_category_overrides", return_value={})
class TestTier3NewTransaction:
    def test_no_match_creates_new(self, mock_overrides: MagicMock) -> None:
        summary = MagicMock()
        summary.query_month.return_value = []

        txns = [_make_stmt_txn("2026-01-15", 4.0, "withdrawal", "Monthlyfee")]
        result = reconcile(
            txns,
            ["Monthly fee"],
            ["Monthlyfee"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )

        assert len(result.new) == 1
        assert result.new[0].cleaned_description == "Monthly fee"
        assert result.new[0].raw_description == "Monthlyfee"
        assert result.new[0].suggested_category == "miscellaneous"

    def test_suggested_category_from_overrides(self, _mock_overrides: MagicMock) -> None:
        with patch(
            "src.finance.statement_reconciler.get_category_overrides",
            return_value={"Monthlyfee": "service charges/fees"},
        ):
            summary = MagicMock()
            summary.query_month.return_value = []

            txns = [_make_stmt_txn("2026-01-15", 4.0, "withdrawal")]
            result = reconcile(
                txns,
                ["Monthly fee"],
                ["Monthlyfee"],
                {"period_start": "2026-01-01", "period_end": "2026-01-31"},
                summary,
            )

            assert result.new[0].suggested_category == "service charges/fees"

    def test_suggest_category_exact_match(self, _mock_overrides: MagicMock) -> None:
        """_suggest_category delegates to resolve_override — exact hit lowercases the category."""
        from src.finance.statement_reconciler import _suggest_category

        with patch(
            "src.finance.statement_reconciler.get_override_context",
            return_value=({"AMAZON.CA": "Technology"}, {}),
        ):
            assert _suggest_category("AMAZON.CA") == "technology"

    def test_suggest_category_normalized_tier(self, _mock_overrides: MagicMock) -> None:
        """Tier 1 catches store-number variants via the resolver."""
        from src.finance.statement_reconciler import _suggest_category

        with patch(
            "src.finance.statement_reconciler.get_override_context",
            return_value=({"BOOSTER JUICE #232": "Restaurant/Dining"}, {}),
        ):
            assert _suggest_category("BOOSTER JUICE #999") == "restaurant/dining"

    def test_suggest_category_ambiguous_falls_back(self, _mock_overrides: MagicMock) -> None:
        """Blacklisted normalized groups fall back to miscellaneous."""
        from src.finance.statement_reconciler import _suggest_category

        with patch(
            "src.finance.statement_reconciler.get_override_context",
            return_value=(
                {
                    "SHOPPERS DRUG MART #123": "Health Care",
                    "SHOPPERS DRUG MART #456": "Groceries",
                },
                {},
            ),
        ):
            assert _suggest_category("SHOPPERS DRUG MART #789") == "miscellaneous"

    def test_suggest_category_alias_tier(self, _mock_overrides: MagicMock) -> None:
        """Tier 2 resolves when an alias redirects the cleaned form to an override key."""
        from src.finance.statement_reconciler import _suggest_category

        with patch(
            "src.finance.statement_reconciler.get_override_context",
            return_value=({"AMAZON.CA": "Miscellaneous"}, {"amzn mktp": "AMAZON.CA"}),
        ):
            assert _suggest_category("AMZN MKTP CA #8888") == "miscellaneous"


@patch("src.finance.statement_reconciler.get_category_overrides", return_value={})
class TestAmbiguousEnrichmentFields:
    def test_single_candidate_carries_description(self, mock_overrides: MagicMock) -> None:
        """Ambiguous with one candidate should carry cleaned/raw description."""
        db_item = _make_db_item("2026-01-16", 33.60, "—", "purchase")
        summary = MagicMock()
        summary.query_month.return_value = [db_item]

        txns = [_make_stmt_txn("2026-01-15", 33.60, "withdrawal")]
        result = reconcile(
            txns,
            ["North Mobile"],
            ["BillPayment NorthMobile"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )

        assert len(result.ambiguous) == 1
        a = result.ambiguous[0]
        assert a.cleaned_description == "North Mobile"
        assert a.raw_description == "BillPayment NorthMobile"
        assert a.suggested_category == "miscellaneous"

    def test_suggested_category_from_overrides(self, _mock_overrides: MagicMock) -> None:
        with patch(
            "src.finance.statement_reconciler.get_category_overrides",
            return_value={"BillPayment NorthMobile": "communication/cell"},
        ):
            db_item = _make_db_item("2026-01-16", 33.60, "—", "purchase")
            summary = MagicMock()
            summary.query_month.return_value = [db_item]

            txns = [_make_stmt_txn("2026-01-15", 33.60, "withdrawal")]
            result = reconcile(
                txns,
                ["North Mobile"],
                ["BillPayment NorthMobile"],
                {"period_start": "2026-01-01", "period_end": "2026-01-31"},
                summary,
            )

            assert result.ambiguous[0].suggested_category == "communication/cell"

    def test_multi_candidate_also_carries_description(self, mock_overrides: MagicMock) -> None:
        """Multiple same-amount matches still carry description fields."""
        db_item1 = _make_db_item("2026-01-15", 50.0, "STORE A", "purchase", date_file_name="2026.01.15_10.00_a.eml")
        db_item2 = _make_db_item("2026-01-15", 50.0, "STORE B", "purchase", date_file_name="2026.01.15_14.00_b.eml")
        summary = MagicMock()
        summary.query_month.return_value = [db_item1, db_item2]

        txns = [_make_stmt_txn("2026-01-15", 50.0, "withdrawal")]
        result = reconcile(
            txns,
            ["Some Store"],
            ["InteracPurchase SOMESTORE"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )

        assert len(result.ambiguous) == 1
        a = result.ambiguous[0]
        assert a.cleaned_description == "Some Store"
        assert a.raw_description == "InteracPurchase SOMESTORE"


@patch("src.finance.statement_reconciler.get_category_overrides", return_value={})
class TestMatchedSuggestedCategory:
    def test_company_differs_gets_override_category(self, _mock_overrides: MagicMock) -> None:
        with patch(
            "src.finance.statement_reconciler.get_category_overrides",
            return_value={"BillPayment WestlandUtilityCo": "utilities"},
        ):
            db_item = _make_db_item("2026-01-15", 98.75, "WESTLANDUTILITYCO", "purchase")
            summary = MagicMock()
            summary.query_month.return_value = [db_item]

            txns = [_make_stmt_txn("2026-01-15", 98.75, "withdrawal")]
            result = reconcile(
                txns,
                ["Westland Utility Co"],
                ["BillPayment WestlandUtilityCo"],
                {"period_start": "2026-01-01", "period_end": "2026-01-31"},
                summary,
            )

            assert result.matched[0].suggested_category == "utilities"

    def test_company_same_keeps_db_category(self, mock_overrides: MagicMock) -> None:
        db_item = _make_db_item("2026-01-15", 50.0, "grocery store", "purchase")
        db_item["Category"] = "groceries"
        summary = MagicMock()
        summary.query_month.return_value = [db_item]

        txns = [_make_stmt_txn("2026-01-15", 50.0, "withdrawal")]
        result = reconcile(
            txns,
            ["Grocery Store"],
            ["InteracPurchase GROCERY STORE"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )

        assert result.matched[0].company_differs is False
        assert result.matched[0].suggested_category == "groceries"


@patch("src.finance.statement_reconciler.get_category_overrides", return_value={})
class TestTypeMapping:
    def test_withdrawal_matches_purchase(self, mock_overrides: MagicMock) -> None:
        db_item = _make_db_item("2026-01-15", 50.0, "STORE", "purchase")
        summary = MagicMock()
        summary.query_month.return_value = [db_item]

        txns = [_make_stmt_txn("2026-01-15", 50.0, "withdrawal")]
        result = reconcile(
            txns,
            ["Store"],
            ["Store"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )
        assert len(result.matched) == 1

    def test_withdrawal_matches_preauth(self, mock_overrides: MagicMock) -> None:
        db_item = _make_db_item("2026-01-15", 50.0, "STORE", "preauth")
        summary = MagicMock()
        summary.query_month.return_value = [db_item]

        txns = [_make_stmt_txn("2026-01-15", 50.0, "withdrawal")]
        result = reconcile(
            txns,
            ["Store"],
            ["Store"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )
        assert len(result.matched) == 1

    def test_deposit_matches_etransfer(self, mock_overrides: MagicMock) -> None:
        db_item = _make_db_item("2026-01-15", 100.0, "JOHN DOE", "e-transfer")
        summary = MagicMock()
        summary.query_month.return_value = [db_item]

        txns = [_make_stmt_txn("2026-01-15", 100.0, "deposit")]
        result = reconcile(
            txns,
            ["John Doe"],
            ["InteracetransferFrom: John Doe"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )
        assert len(result.matched) == 1

    def test_withdrawal_does_not_match_etransfer(self, mock_overrides: MagicMock) -> None:
        """Withdrawal ≠ e-transfer should become a suspected duplicate, not new."""
        db_item = _make_db_item("2026-01-15", 50.0, "SOMEONE", "e-transfer")
        summary = MagicMock()
        summary.query_month.return_value = [db_item]

        txns = [_make_stmt_txn("2026-01-15", 50.0, "withdrawal")]
        result = reconcile(
            txns,
            ["Someone"],
            ["Someone"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )
        assert len(result.suspected_duplicates) == 1
        assert len(result.new) == 0


@patch("src.finance.statement_reconciler.get_category_overrides", return_value={})
class TestSameDayDuplicates:
    def test_multiple_same_amount_same_day_ambiguous(self, mock_overrides: MagicMock) -> None:
        db_item1 = _make_db_item("2026-01-15", 50.0, "STORE A", "purchase", date_file_name="2026.01.15_10.00_a.eml")
        db_item2 = _make_db_item("2026-01-15", 50.0, "STORE B", "purchase", date_file_name="2026.01.15_14.00_b.eml")
        summary = MagicMock()
        summary.query_month.return_value = [db_item1, db_item2]

        txns = [_make_stmt_txn("2026-01-15", 50.0, "withdrawal")]
        result = reconcile(
            txns,
            ["Some Store"],
            ["Some Store"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )
        assert len(result.ambiguous) == 1
        assert "multiple" in result.ambiguous[0].reason.lower()


@patch("src.finance.statement_reconciler.get_category_overrides", return_value={})
class TestCrossMonth:
    def test_queries_both_months(self, mock_overrides: MagicMock) -> None:
        summary = MagicMock(name="summary")
        summary.query_month.return_value = []

        txns = [_make_stmt_txn("2025-12-30", 10.0, "withdrawal")]
        reconcile(
            txns,
            ["Test"],
            ["Test"],
            {"period_start": "2025-12-24", "period_end": "2026-01-23"},
            summary,
        )

        called_months = [call[0][0] for call in summary.query_month.call_args_list]
        assert "2025-12" in called_months
        assert "2026-01" in called_months


@patch("src.finance.statement_reconciler.get_category_overrides", return_value={})
class TestUsedKeyTracking:
    def test_prevents_double_matching(self, mock_overrides: MagicMock) -> None:
        """One DB item should only match one statement transaction."""
        db_item = _make_db_item("2026-01-15", 50.0, "STORE", "purchase")
        summary = MagicMock()
        summary.query_month.return_value = [db_item]

        txns = [
            _make_stmt_txn("2026-01-15", 50.0, "withdrawal"),
            _make_stmt_txn("2026-01-15", 50.0, "withdrawal"),
        ]
        result = reconcile(
            txns,
            ["Store", "Store"],
            ["Store", "Store"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )

        # First should match, second should be new (only one DB item available)
        assert len(result.matched) == 1
        assert len(result.new) == 1


@patch("src.finance.statement_reconciler.get_category_overrides", return_value={})
class TestSuspectedDuplicates:
    def test_suspected_duplicate_has_db_item_details(self, mock_overrides: MagicMock) -> None:
        """Suspected duplicate should carry the matched DB item with correct fields."""
        db_item = _make_db_item("2026-01-15", 50.0, "SOMEONE", "e-transfer")
        summary = MagicMock()
        summary.query_month.return_value = [db_item]

        txns = [_make_stmt_txn("2026-01-15", 50.0, "withdrawal")]
        result = reconcile(
            txns,
            ["Someone"],
            ["Someone"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )

        assert len(result.suspected_duplicates) == 1
        sd = result.suspected_duplicates[0]
        assert sd.db_item is db_item
        assert sd.db_item["Company"] == "SOMEONE"
        assert sd.db_item["TransactionType"] == "e-transfer"
        assert sd.cleaned_description == "Someone"
        assert sd.raw_description == "Someone"

    def test_suspected_duplicate_reason_shows_types(self, mock_overrides: MagicMock) -> None:
        """Reason string should include both the statement and DB types."""
        db_item = _make_db_item("2026-01-15", 50.0, "SOMEONE", "e-transfer")
        summary = MagicMock()
        summary.query_month.return_value = [db_item]

        txns = [_make_stmt_txn("2026-01-15", 50.0, "withdrawal")]
        result = reconcile(
            txns,
            ["Someone"],
            ["Someone"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )

        sd = result.suspected_duplicates[0]
        assert "withdrawal" in sd.reason
        assert "e-transfer" in sd.reason

    def test_fuzzy_date_suspected_duplicate(self, mock_overrides: MagicMock) -> None:
        """Cross-type match with ±1 day offset should still be a suspected duplicate."""
        db_item = _make_db_item("2026-01-16", 50.0, "SOMEONE", "e-transfer")
        summary = MagicMock()
        summary.query_month.return_value = [db_item]

        txns = [_make_stmt_txn("2026-01-15", 50.0, "withdrawal")]
        result = reconcile(
            txns,
            ["Someone"],
            ["Someone"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )

        assert len(result.suspected_duplicates) == 1
        assert len(result.new) == 0

    def test_no_suspected_duplicate_when_types_compatible(self, mock_overrides: MagicMock) -> None:
        """Compatible types should match normally at Tier 1, not as suspected duplicate."""
        db_item = _make_db_item("2026-01-15", 50.0, "STORE", "purchase")
        summary = MagicMock()
        summary.query_month.return_value = [db_item]

        txns = [_make_stmt_txn("2026-01-15", 50.0, "withdrawal")]
        result = reconcile(
            txns,
            ["Store"],
            ["Store"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )

        assert len(result.matched) == 1
        assert len(result.suspected_duplicates) == 0

    def test_used_key_prevents_suspected_duplicate(self, mock_overrides: MagicMock) -> None:
        """A DB item already matched by Tier 1 should not be flagged as suspected duplicate."""
        # Two statement txns, one DB item with compatible type and one with incompatible
        db_purchase = _make_db_item("2026-01-15", 50.0, "STORE", "purchase", date_file_name="2026.01.15_10.00_a.eml")
        db_etransfer = _make_db_item(
            "2026-01-15",
            50.0,
            "PERSON",
            "e-transfer",
            date_file_name="2026.01.15_14.00_b.eml",
        )
        summary = MagicMock()
        summary.query_month.return_value = [db_purchase, db_etransfer]

        txns = [
            _make_stmt_txn("2026-01-15", 50.0, "withdrawal"),
            _make_stmt_txn("2026-01-15", 50.0, "withdrawal"),
        ]
        result = reconcile(
            txns,
            ["Store", "Person"],
            ["Store", "Person"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )

        # First should match the purchase, second should flag e-transfer as suspected dup
        assert len(result.matched) == 1
        assert len(result.suspected_duplicates) == 1
        assert result.suspected_duplicates[0].db_item is db_etransfer


@patch("src.finance.statement_reconciler.get_category_overrides", return_value={})
class TestDirectionFilter:
    def test_deposit_not_suspected_duplicate_of_withdrawal(self, mock_overrides: MagicMock) -> None:
        """Bug 2 regression: deposit $4 vs DB withdrawal $4 are opposite directions → new, not suspected dup."""
        db_item = _make_db_item("2026-01-15", 4.0, "MONTHLY FEE", "withdrawal")
        summary = MagicMock()
        summary.query_month.return_value = [db_item]

        txns = [_make_stmt_txn("2026-01-15", 4.0, "deposit", "MonthlyFeeRebate")]
        result = reconcile(
            txns,
            ["Monthly Fee Rebate"],
            ["MonthlyFeeRebate"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )

        assert len(result.suspected_duplicates) == 0
        assert len(result.new) == 1

    def test_deposit_not_suspected_duplicate_of_purchase(self, mock_overrides: MagicMock) -> None:
        """Deposit vs purchase are opposite directions → new."""
        db_item = _make_db_item("2026-01-15", 25.0, "STORE", "purchase")
        summary = MagicMock()
        summary.query_month.return_value = [db_item]

        txns = [_make_stmt_txn("2026-01-15", 25.0, "deposit")]
        result = reconcile(
            txns,
            ["Store Refund"],
            ["Store Refund"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )

        assert len(result.suspected_duplicates) == 0
        assert len(result.new) == 1

    def test_deposit_matches_etransfer_at_tier1(self, mock_overrides: MagicMock) -> None:
        """Deposit + e-transfer are type-compatible → Tier 1 match, not suspected dup."""
        db_item = _make_db_item("2026-01-15", 200.0, "JOHN DOE", "e-transfer")
        summary = MagicMock()
        summary.query_month.return_value = [db_item]

        txns = [_make_stmt_txn("2026-01-15", 200.0, "deposit")]
        result = reconcile(
            txns,
            ["John Doe"],
            ["etransfer John Doe"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )

        assert len(result.matched) == 1
        assert len(result.suspected_duplicates) == 0

    def test_withdrawal_not_suspected_duplicate_of_deposit(self, mock_overrides: MagicMock) -> None:
        """Withdrawal vs deposit are opposite directions → new."""
        db_item = _make_db_item("2026-01-15", 100.0, "PAYROLL", "deposit")
        summary = MagicMock()
        summary.query_month.return_value = [db_item]

        txns = [_make_stmt_txn("2026-01-15", 100.0, "withdrawal")]
        result = reconcile(
            txns,
            ["Payroll"],
            ["Payroll"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )

        assert len(result.suspected_duplicates) == 0
        assert len(result.new) == 1


@patch("src.finance.statement_reconciler.get_category_overrides", return_value={})
class TestCrossTypeBeforeFuzzy:
    def test_cross_type_preferred_over_fuzzy_compatible(self, mock_overrides: MagicMock) -> None:
        """Bug 1 regression: cross-type suspected dup should take priority over fuzzy type-compatible match.

        Statement: withdrawal $1275.50 on Jan 15
        DB has: withdrawal alert on Jan 14 (type-compatible, fuzzy) AND e-transfer on Jan 14 (cross-type).
        Should be suspected duplicate of e-transfer, NOT ambiguous with withdrawal alert.
        """
        db_withdrawal = _make_db_item(
            "2026-01-14",
            1275.50,
            "",
            "withdrawal",
            date_file_name="2026.01.14_10.00_withdrawal.eml",
        )
        db_etransfer = _make_db_item(
            "2026-01-14",
            1275.50,
            "NORTHWIND CONTRACTING LTD.",
            "e-transfer",
            date_file_name="2026.01.14_14.00_etransfer.eml",
        )
        summary = MagicMock()
        summary.query_month.return_value = [db_withdrawal, db_etransfer]

        txns = [_make_stmt_txn("2026-01-15", 1275.50, "withdrawal")]
        result = reconcile(
            txns,
            ["Northwind Contracting"],
            ["e-Transfersent NorthwindContracting"],
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            summary,
        )

        # Should be suspected duplicate of the e-transfer, not ambiguous with the withdrawal
        assert len(result.suspected_duplicates) == 1
        assert len(result.ambiguous) == 0
        assert result.suspected_duplicates[0].db_item is db_etransfer
        assert "e-transfer" in result.suspected_duplicates[0].reason


@patch("src.finance.statement_reconciler.get_category_overrides", return_value={})
class TestPreviouslyImported:
    def test_statement_source_matching(self, mock_overrides: MagicMock) -> None:
        """Transactions previously imported from this statement are classified as previously_imported."""
        db_item = _make_db_item("2026-01-15", 4.0, "Monthly fee", "withdrawal")
        db_item["StatementSource"] = "RBC_Chequing_2025-12"
        db_item["DateFileName"] = "2026.01.15_00.00_stmt_RBC_abc12345.pdf"
        summary = MagicMock()
        summary.query_month.side_effect = lambda m: [db_item] if m == "2026-01" else []

        txns = [_make_stmt_txn("2026-01-15", 4.0, "withdrawal", "Monthlyfee")]
        result = reconcile(
            txns,
            ["Monthly fee"],
            ["Monthlyfee"],
            {
                "period_start": "2025-12-24",
                "period_end": "2026-01-23",
                "institution": "RBC",
                "account_type": "chequing",
            },
            summary,
        )

        assert len(result.previously_imported) == 1
        assert len(result.matched) == 0
        assert len(result.new) == 0
        assert result.previously_imported[0].db_item is db_item

    def test_statement_source_takes_priority_over_tier1(self, mock_overrides: MagicMock) -> None:
        """Previously imported items are classified before Tier 1 matching."""
        # One item from statement import, one from email
        stmt_item = _make_db_item("2026-01-15", 50.0, "STORE", "withdrawal")
        stmt_item["StatementSource"] = "RBC_Chequing_2025-12"
        stmt_item["DateFileName"] = "2026.01.15_00.00_stmt_RBC_abc12345.pdf"

        email_item = _make_db_item("2026-01-15", 50.0, "STORE", "purchase")
        email_item["DateFileName"] = "2026.01.15_12.00_test.eml"

        summary = MagicMock()
        summary.query_month.side_effect = lambda m: [stmt_item, email_item] if m == "2026-01" else []

        txns = [_make_stmt_txn("2026-01-15", 50.0, "withdrawal")]
        result = reconcile(
            txns,
            ["Store"],
            ["Store"],
            {
                "period_start": "2025-12-24",
                "period_end": "2026-01-23",
                "institution": "RBC",
                "account_type": "chequing",
            },
            summary,
        )

        # The statement-sourced item should be previously_imported, not matched
        assert len(result.previously_imported) == 1
        assert result.previously_imported[0].db_item is stmt_item
        assert len(result.matched) == 0

    def test_non_matching_source_falls_through_to_tier1(self, mock_overrides: MagicMock) -> None:
        """Items with a different StatementSource fall through to normal matching."""
        db_item = _make_db_item("2026-01-15", 50.0, "STORE", "purchase")
        db_item["StatementSource"] = "CIBC_Chequing_2025-12"  # Different source
        summary = MagicMock()
        # Return item only for Jan month to avoid double-counting
        summary.query_month.side_effect = lambda m: [db_item] if m == "2026-01" else []

        txns = [_make_stmt_txn("2026-01-15", 50.0, "withdrawal")]
        result = reconcile(
            txns,
            ["Store"],
            ["Store"],
            {
                "period_start": "2025-12-24",
                "period_end": "2026-01-23",
                "institution": "RBC",
                "account_type": "chequing",
            },
            summary,
        )

        assert len(result.previously_imported) == 0
        assert len(result.matched) == 1


@patch("src.finance.statement_reconciler.get_category_overrides", return_value={})
class TestNoPeriod:
    def test_no_period_marks_all_new(self, mock_overrides: MagicMock) -> None:
        summary = MagicMock(name="summary")

        txns = [_make_stmt_txn("2026-01-15", 50.0, "withdrawal")]
        result = reconcile(
            txns,
            ["Test"],
            ["Test"],
            {"period_start": None, "period_end": None},
            summary,
        )

        assert len(result.new) == 1
        summary.query_month.assert_not_called()
