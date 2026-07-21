"""Transaction hash generation for deduplication."""

import hashlib
from typing import Any

__all__ = ["bump_hash_occurrence", "generate_transaction_hash"]


def generate_transaction_hash(transaction_data: dict[str, Any]) -> str:
    """Generate a SHA-256 hash from core transaction fields for deduplication."""
    forwarded_to = transaction_data.get("forwarded_to") or ""
    institution = transaction_data.get("institution") or ""
    amount = transaction_data.get("amount")
    amount_str = f"{float(amount):.2f}" if amount is not None else ""
    company = transaction_data.get("company") or ""
    date = transaction_data.get("date") or ""
    transaction_type = transaction_data.get("transaction_type") or ""

    fields = [forwarded_to, institution, amount_str, company, date, transaction_type]
    key = "|".join(fields)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def bump_hash_occurrence(base_hash: str, occurrence: int) -> str:
    """Re-hash with an occurrence suffix so a second copy of the same transaction
    produces a distinct hash. Same pattern used by statement imports
    (see TransactionsDBBase._compute_statement_hash).
    """
    if occurrence <= 0:
        return base_hash
    key = f"{base_hash}|{occurrence}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
