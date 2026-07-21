"""Tests for TransactionsDB.set_deleted() and permanently_delete()."""

from tests.factories import make_transactions_db as _make_db


class TestSetDeleted:
    """Tests for set_deleted() method."""

    def test_delete_uses_set_expression(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.set_deleted("user@example.com", "2026.01.15_14.30_test.eml", True)

        call_kwargs = table.update_item.call_args.kwargs
        assert "SET DeletedAt = :val" in call_kwargs["UpdateExpression"]
        assert ":val" in call_kwargs["ExpressionAttributeValues"]

    def test_restore_uses_remove_expression(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {"DeletedAt": "2026-01-15T00:00:00+00:00"}}
        db.set_deleted("user@example.com", "2026.01.15_14.30_test.eml", False)

        call_kwargs = table.update_item.call_args.kwargs
        assert "REMOVE DeletedAt" in call_kwargs["UpdateExpression"]

    def test_returns_old_deleted_at(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {"DeletedAt": "2026-01-15T00:00:00+00:00"}}
        old = db.set_deleted("user@example.com", "2026.01.15_14.30_test.eml", False)
        assert old == "2026-01-15T00:00:00+00:00"

    def test_returns_none_when_not_previously_set(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        old = db.set_deleted("user@example.com", "2026.01.15_14.30_test.eml", True)
        assert old is None

    def test_uses_correct_key(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.set_deleted("user@example.com", "2026.01.15_14.30_test.eml", True)

        call_kwargs = table.update_item.call_args.kwargs
        assert call_kwargs["Key"] == {
            "ForwardedTo": "user@example.com",
            "DateFileName": "2026.01.15_14.30_test.eml",
        }

    def test_returns_updated_old(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.set_deleted("user@example.com", "2026.01.15_14.30_test.eml", True)

        call_kwargs = table.update_item.call_args.kwargs
        assert call_kwargs["ReturnValues"] == "UPDATED_OLD"


class TestPermanentlyDelete:
    """Tests for permanently_delete() method."""

    def test_calls_delete_item(self):
        db, table = _make_db()
        table.delete_item.return_value = {
            "Attributes": {
                "ForwardedTo": "user@example.com",
                "DateFileName": "2026.01.15_14.30_test.eml",
                "Company": "Test Store",
            }
        }
        result = db.permanently_delete("user@example.com", "2026.01.15_14.30_test.eml")

        table.delete_item.assert_called_once_with(
            Key={"ForwardedTo": "user@example.com", "DateFileName": "2026.01.15_14.30_test.eml"},
            ReturnValues="ALL_OLD",
        )
        assert result is not None
        assert result["Company"] == "Test Store"

    def test_returns_none_when_not_found(self):
        db, table = _make_db()
        table.delete_item.return_value = {}
        result = db.permanently_delete("user@example.com", "2026.01.15_14.30_test.eml")
        assert result is None

    def test_returns_old_item(self):
        db, table = _make_db()
        old_item = {
            "ForwardedTo": "user@example.com",
            "DateFileName": "2026.01.15_14.30_test.eml",
            "Amount": 42,
        }
        table.delete_item.return_value = {"Attributes": old_item}
        result = db.permanently_delete("user@example.com", "2026.01.15_14.30_test.eml")
        assert result == old_item
