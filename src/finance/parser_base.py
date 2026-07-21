from abc import ABC, abstractmethod
from typing import Any

__all__ = [
    "AMOUNT_PATTERN",
    "TransactionParser",
    "merge_details",
    "parse_amount",
]

# Matches a currency amount: comma-grouped ("1,234.56") or plain ("1000.00").
# The grouped branch requires at least one ",ddd" group so that plain 4+ digit
# amounts fall through to the \d+ branch instead of truncating after 3 digits
# ("$1000.00" must parse as 1000.00, not 100.0).
AMOUNT_PATTERN = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2})?"


class TransactionParser(ABC):
    @abstractmethod
    def parse_email(self, email_body_text: str, email_details: dict[str, Any]) -> dict[str, Any]:
        pass


def parse_amount(amount_str: str | None) -> float | None:
    """Parse a currency amount string to float, stripping commas.

    Returns None if the input is None or empty.
    Examples: "1,234.56" → 1234.56, "42.00" → 42.0, None → None
    """
    if not amount_str:
        return None
    return float(amount_str.replace(",", ""))


def merge_details(details: dict[str, Any], additional_data: dict[str, Any] | None) -> dict[str, Any]:
    """
    Merge email details with additional transaction data if available.

    Parameters
    ----------
    details : dict
        The base dictionary containing email metadata.
    additional_data : dict or None
        The transaction data to be merged, if available.

    Returns
    -------
    dict
        A dictionary containing both email metadata and transaction data.
    """
    if additional_data is not None:
        return {**details, **additional_data}
    return details
