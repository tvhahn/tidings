"""Cross-backend exception types."""


class VersionConflictError(Exception):
    """Raised when an optimistic locking version check fails.

    Used by both DynamoDB (ConditionalCheckFailedException) and
    SQLite (UPDATE ... WHERE version = ? with rowcount == 0) backends.
    """
