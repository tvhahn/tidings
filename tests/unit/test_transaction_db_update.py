"""Tests for TransactionsDB.update_category() and mark_category_reviewed()."""

from decimal import Decimal

from tests.factories import make_transactions_db as _make_db


class TestUpdateCategory:
    """Tests for update_category() method."""

    def test_returns_old_category(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {"Category": "groceries"}}
        old = db.update_category("user@example.com", "2026.01.15_14.30_test.eml", "Restaurant/Dining")
        assert old == "groceries"

    def test_returns_none_when_no_previous_category(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        old = db.update_category("user@example.com", "2026.01.15_14.30_test.eml", "Groceries")
        assert old is None

    def test_lowercases_new_category(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.update_category("user@example.com", "2026.01.15_14.30_test.eml", "Restaurant/Dining")

        call_kwargs = table.update_item.call_args.kwargs
        assert call_kwargs["ExpressionAttributeValues"][":cat"] == "restaurant/dining"

    def test_uses_correct_key(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.update_category("user@example.com", "2026.01.15_14.30_test.eml", "Groceries")

        call_kwargs = table.update_item.call_args.kwargs
        assert call_kwargs["Key"] == {
            "ForwardedTo": "user@example.com",
            "DateFileName": "2026.01.15_14.30_test.eml",
        }

    def test_sets_category_audit_metadata(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.update_category("user@example.com", "2026.01.15_14.30_test.eml", "Groceries", source="override")

        call_kwargs = table.update_item.call_args.kwargs
        audit = call_kwargs["ExpressionAttributeValues"][":audit"]
        assert audit["source"] == "override"
        assert "reviewed_at" in audit

    def test_update_expression_sets_category_and_audit(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.update_category("user@example.com", "2026.01.15_14.30_test.eml", "Groceries")

        call_kwargs = table.update_item.call_args.kwargs
        assert "SET Category = :cat" in call_kwargs["UpdateExpression"]
        assert "CategoryAudit = :audit" in call_kwargs["UpdateExpression"]
        assert call_kwargs["ReturnValues"] == "UPDATED_OLD"

    def test_default_source_is_manual(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.update_category("user@example.com", "2026.01.15_14.30_test.eml", "Groceries")

        call_kwargs = table.update_item.call_args.kwargs
        audit = call_kwargs["ExpressionAttributeValues"][":audit"]
        assert audit["source"] == "manual"


class TestEnrichTransaction:
    """Tests for enrich_transaction() method."""

    def test_returns_old_company_and_category(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {"Company": "—", "Category": "miscellaneous"}}
        result = db.enrich_transaction(
            "user@example.com", "2026.01.15_14.30_test.eml", "North Mobile", "Communication/Cell"
        )
        # Return dict now carries category_preserved (overwrite path here per the
        # enrich precedence rule — non-manual existing + real incoming category).
        assert result == {"old_company": "—", "old_category": "miscellaneous", "category_preserved": False}

    def test_lowercases_new_category(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.enrich_transaction("user@example.com", "2026.01.15_14.30_test.eml", "North Mobile", "Communication/Cell")
        call_kwargs = table.update_item.call_args.kwargs
        assert call_kwargs["ExpressionAttributeValues"][":cat"] == "communication/cell"

    def test_sets_company_value(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.enrich_transaction("user@example.com", "2026.01.15_14.30_test.eml", "North Mobile", "Communication/Cell")
        call_kwargs = table.update_item.call_args.kwargs
        assert call_kwargs["ExpressionAttributeValues"][":comp"] == "North Mobile"

    def test_sets_audit_with_statement_enrich_source(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.enrich_transaction("user@example.com", "2026.01.15_14.30_test.eml", "North Mobile", "Communication/Cell")
        call_kwargs = table.update_item.call_args.kwargs
        audit = call_kwargs["ExpressionAttributeValues"][":audit"]
        assert audit["source"] == "statement_enrich"
        assert "reviewed_at" in audit

    def test_custom_source(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.enrich_transaction("user@example.com", "2026.01.15_14.30_test.eml", "Test", "Groceries", source="custom")
        call_kwargs = table.update_item.call_args.kwargs
        audit = call_kwargs["ExpressionAttributeValues"][":audit"]
        assert audit["source"] == "custom"

    def test_update_expression_sets_all_three_fields(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.enrich_transaction("user@example.com", "2026.01.15_14.30_test.eml", "Test", "Groceries")
        call_kwargs = table.update_item.call_args.kwargs
        expr = call_kwargs["UpdateExpression"]
        assert "Company = :comp" in expr
        assert "Category = :cat" in expr
        assert "CategoryAudit = :audit" in expr
        assert call_kwargs["ReturnValues"] == "UPDATED_OLD"

    def test_uses_correct_key(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.enrich_transaction("a@b.com", "2026.01.17_00.00_stmt_RBC_abc.pdf", "Test", "Groceries")
        call_kwargs = table.update_item.call_args.kwargs
        assert call_kwargs["Key"] == {
            "ForwardedTo": "a@b.com",
            "DateFileName": "2026.01.17_00.00_stmt_RBC_abc.pdf",
        }

    def test_sets_statement_source_when_provided(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.enrich_transaction(
            "user@example.com",
            "2026.01.15_14.30_test.eml",
            "North Mobile",
            "Communication/Cell",
            statement_source="RBC_Chequing_2025-12",
        )
        call_kwargs = table.update_item.call_args.kwargs
        assert "StatementSource = :src" in call_kwargs["UpdateExpression"]
        assert call_kwargs["ExpressionAttributeValues"][":src"] == "RBC_Chequing_2025-12"

    def test_omits_statement_source_when_none(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.enrich_transaction("user@example.com", "2026.01.15_14.30_test.eml", "Test", "Groceries")
        call_kwargs = table.update_item.call_args.kwargs
        assert "StatementSource" not in call_kwargs["UpdateExpression"]
        assert ":src" not in call_kwargs["ExpressionAttributeValues"]


class TestUpdateFields:
    """Tests for update_fields() method — the generic multi-field editor."""

    KEY = ("user@example.com", "2026.01.15_14.30_test.eml")

    def test_empty_fields_returns_none_without_calling_update(self):
        db, table = _make_db()
        result = db.update_fields(*self.KEY, fields={})
        assert result is None
        assert table.update_item.call_count == 0

    def test_empty_fields_with_category_still_returns_none(self):
        # Current contract: empty `fields` short-circuits even if `category` is set
        db, table = _make_db()
        result = db.update_fields(*self.KEY, fields={}, category="Groceries")
        assert result is None
        assert table.update_item.call_count == 0

    def test_company_only_sets_company_and_audit(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {"Company": "Old Co"}}
        result = db.update_fields(*self.KEY, fields={"company": "New Co"})

        kwargs = table.update_item.call_args.kwargs
        assert "Company = :comp" in kwargs["UpdateExpression"]
        assert "CategoryAudit = :audit" in kwargs["UpdateExpression"]
        assert kwargs["ExpressionAttributeValues"][":comp"] == "New Co"
        assert kwargs["ReturnValues"] == "UPDATED_OLD"
        assert result is not None
        assert result["old_company"] == "Old Co"

    def test_amount_is_converted_to_decimal(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {"Amount": Decimal("99.99")}}
        result = db.update_fields(*self.KEY, fields={"amount": 12.34})

        kwargs = table.update_item.call_args.kwargs
        assert kwargs["ExpressionAttributeValues"][":amt"] == Decimal("12.34")
        assert "Amount = :amt" in kwargs["UpdateExpression"]
        # decimal_to_float conversion in return value
        assert result is not None
        assert result["old_amount"] == 99.99

    def test_transaction_type_only(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {"TransactionType": "purchase"}}
        db.update_fields(*self.KEY, fields={"transaction_type": "withdrawal"})

        kwargs = table.update_item.call_args.kwargs
        assert "TransactionType = :tt" in kwargs["UpdateExpression"]
        assert kwargs["ExpressionAttributeValues"][":tt"] == "withdrawal"

    def test_multi_field_update_sets_all_three(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.update_fields(
            *self.KEY,
            fields={"company": "Acme", "amount": 50.00, "transaction_type": "purchase"},
        )

        kwargs = table.update_item.call_args.kwargs
        expr = kwargs["UpdateExpression"]
        assert "Company = :comp" in expr
        assert "Amount = :amt" in expr
        assert "TransactionType = :tt" in expr
        assert "CategoryAudit = :audit" in expr

    def test_category_kwarg_is_lowercased_and_appended(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.update_fields(*self.KEY, fields={"company": "X"}, category="Restaurant/Dining")

        kwargs = table.update_item.call_args.kwargs
        assert "Category = :cat" in kwargs["UpdateExpression"]
        assert kwargs["ExpressionAttributeValues"][":cat"] == "restaurant/dining"

    def test_audit_source_is_manual_edit_with_iso_timestamp(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.update_fields(*self.KEY, fields={"company": "X"})

        audit = table.update_item.call_args.kwargs["ExpressionAttributeValues"][":audit"]
        assert audit["source"] == "manual_edit"
        assert "reviewed_at" in audit
        # ISO 8601 timestamp format check (YYYY-MM-DDTHH:MM:SS...)
        assert "T" in audit["reviewed_at"]

    def test_unknown_field_keys_are_silently_ignored(self):
        # Current contract: unknown keys don't raise; only recognized keys build the expression
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.update_fields(*self.KEY, fields={"foo": "bar", "bogus": 1})

        kwargs = table.update_item.call_args.kwargs
        # No recognized fields → only CategoryAudit is SET
        assert kwargs["UpdateExpression"] == "SET CategoryAudit = :audit"
        assert ":comp" not in kwargs["ExpressionAttributeValues"]
        assert ":amt" not in kwargs["ExpressionAttributeValues"]
        assert ":tt" not in kwargs["ExpressionAttributeValues"]

    def test_returns_all_old_values_including_none_fields(self):
        db, table = _make_db()
        table.update_item.return_value = {
            "Attributes": {
                "Company": "OldCo",
                "Amount": Decimal("10.00"),
                "TransactionType": "purchase",
                "Category": "groceries",
            }
        }
        result = db.update_fields(*self.KEY, fields={"company": "New"})

        assert result == {
            "old_company": "OldCo",
            "old_amount": 10.0,
            "old_transaction_type": "purchase",
            "old_category": "groceries",
        }

    def test_uses_correct_key(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.update_fields("a@b.com", "2026.03.01_10.00_email.eml", fields={"company": "X"})

        assert table.update_item.call_args.kwargs["Key"] == {
            "ForwardedTo": "a@b.com",
            "DateFileName": "2026.03.01_10.00_email.eml",
        }


class TestMarkCategoryReviewed:
    """Tests for mark_category_reviewed() method."""

    def test_sets_audit_without_changing_category(self):
        db, table = _make_db()
        db.mark_category_reviewed("user@example.com", "2026.01.15_14.30_test.eml")

        call_kwargs = table.update_item.call_args.kwargs
        assert call_kwargs["UpdateExpression"] == "SET CategoryAudit = :audit"
        assert ":cat" not in call_kwargs["ExpressionAttributeValues"]

    def test_default_source_is_audit(self):
        db, table = _make_db()
        db.mark_category_reviewed("user@example.com", "2026.01.15_14.30_test.eml")

        call_kwargs = table.update_item.call_args.kwargs
        audit = call_kwargs["ExpressionAttributeValues"][":audit"]
        assert audit["source"] == "audit"

    def test_custom_source(self):
        db, table = _make_db()
        db.mark_category_reviewed("user@example.com", "2026.01.15_14.30_test.eml", source="override")

        call_kwargs = table.update_item.call_args.kwargs
        audit = call_kwargs["ExpressionAttributeValues"][":audit"]
        assert audit["source"] == "override"

    def test_uses_correct_key(self):
        db, table = _make_db()
        db.mark_category_reviewed("a@b.com", "2026.02.01_10.00_email.eml")

        call_kwargs = table.update_item.call_args.kwargs
        assert call_kwargs["Key"] == {
            "ForwardedTo": "a@b.com",
            "DateFileName": "2026.02.01_10.00_email.eml",
        }
