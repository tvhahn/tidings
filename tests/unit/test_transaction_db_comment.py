"""Tests for TransactionsDB.set_comment()."""

from tests.factories import make_transactions_db as _make_db


class TestSetComment:
    """Tests for set_comment() method."""

    def test_set_comment_uses_set_expression(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.set_comment("user@example.com", "2026.01.15_14.30_test.eml", "split with roommate")

        call_kwargs = table.update_item.call_args.kwargs
        assert "SET #C = :val" in call_kwargs["UpdateExpression"]
        assert call_kwargs["ExpressionAttributeNames"]["#C"] == "Comment"
        assert call_kwargs["ExpressionAttributeValues"][":val"] == "split with roommate"

    def test_clear_comment_uses_remove_expression(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {"Comment": "old note"}}
        db.set_comment("user@example.com", "2026.01.15_14.30_test.eml", None)

        call_kwargs = table.update_item.call_args.kwargs
        assert "REMOVE #C" in call_kwargs["UpdateExpression"]
        assert call_kwargs["ExpressionAttributeNames"]["#C"] == "Comment"
        assert ":val" not in call_kwargs.get("ExpressionAttributeValues", {})

    def test_empty_string_uses_remove_expression(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.set_comment("user@example.com", "2026.01.15_14.30_test.eml", "")

        call_kwargs = table.update_item.call_args.kwargs
        assert "REMOVE #C" in call_kwargs["UpdateExpression"]
        assert call_kwargs["ExpressionAttributeNames"]["#C"] == "Comment"

    def test_returns_old_comment(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {"Comment": "previous note"}}
        old = db.set_comment("user@example.com", "2026.01.15_14.30_test.eml", "new note")
        assert old == "previous note"

    def test_returns_none_when_no_previous_comment(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        old = db.set_comment("user@example.com", "2026.01.15_14.30_test.eml", "first comment")
        assert old is None

    def test_uses_correct_key(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.set_comment("user@example.com", "2026.01.15_14.30_test.eml", "note")

        call_kwargs = table.update_item.call_args.kwargs
        assert call_kwargs["Key"] == {
            "ForwardedTo": "user@example.com",
            "DateFileName": "2026.01.15_14.30_test.eml",
        }

    def test_returns_updated_old(self):
        db, table = _make_db()
        table.update_item.return_value = {"Attributes": {}}
        db.set_comment("user@example.com", "2026.01.15_14.30_test.eml", "note")

        call_kwargs = table.update_item.call_args.kwargs
        assert call_kwargs["ReturnValues"] == "UPDATED_OLD"
