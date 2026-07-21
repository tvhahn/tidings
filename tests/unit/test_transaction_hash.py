"""Tests for `src/finance/transaction_hash.py` — dedup hash generation."""

from decimal import Decimal

import pytest

from src.finance.transaction_hash import (
    bump_hash_occurrence,
    generate_transaction_hash,
)


def _base_txn() -> dict[str, object]:
    return {
        "forwarded_to": "user@example.com",
        "institution": "RBC",
        "amount": 10.0,
        "company": "Coffee Shop",
        "date": "2026-06-28",
        "transaction_type": "debit",
    }


def test_hash_is_sha256_hex() -> None:
    """A hash is a 64-char lowercase hex SHA-256 digest."""
    digest = generate_transaction_hash(_base_txn())
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_deterministic_same_input_same_hash() -> None:
    """Identical inputs produce identical hashes."""
    assert generate_transaction_hash(_base_txn()) == generate_transaction_hash(_base_txn())


def test_field_order_irrelevant_dict_insertion() -> None:
    """Hash depends on field values, not dict insertion order."""
    txn = _base_txn()
    reordered = {k: txn[k] for k in reversed(list(txn.keys()))}
    assert generate_transaction_hash(txn) == generate_transaction_hash(reordered)


@pytest.mark.parametrize(
    "field",
    ["forwarded_to", "institution", "amount", "company", "date", "transaction_type"],
)
def test_different_field_changes_hash(field: str) -> None:
    """Changing any contributing field changes the hash."""
    txn = _base_txn()
    base = generate_transaction_hash(txn)
    mutated = dict(txn)
    mutated[field] = 999.99 if field == "amount" else "different-value"
    assert generate_transaction_hash(mutated) != base


def test_unknown_keys_are_ignored() -> None:
    """Keys outside the core field set do not affect the hash."""
    txn = _base_txn()
    base = generate_transaction_hash(txn)
    extra = dict(txn)
    extra["category"] = "Dining"
    extra["notes"] = "anything"
    assert generate_transaction_hash(extra) == base


def test_missing_fields_treated_as_empty_string() -> None:
    """An empty dict hashes the same as one with all fields set to None/empty."""
    empty_hash = generate_transaction_hash({})
    explicit_none = generate_transaction_hash(
        {
            "forwarded_to": None,
            "institution": None,
            "amount": None,
            "company": None,
            "date": None,
            "transaction_type": "",
        }
    )
    assert empty_hash == explicit_none


def test_none_amount_is_empty_not_zero() -> None:
    """A None amount is distinct from a 0.0 amount (None -> '', 0.0 -> '0.00')."""
    none_amount = generate_transaction_hash({"amount": None})
    zero_amount = generate_transaction_hash({"amount": 0.0})
    assert none_amount != zero_amount


def test_falsy_string_fields_normalize_to_empty() -> None:
    """`None` and `""` for a field collapse to the same '' contribution."""
    txn_none = _base_txn()
    txn_none["company"] = None
    txn_empty = _base_txn()
    txn_empty["company"] = ""
    assert generate_transaction_hash(txn_none) == generate_transaction_hash(txn_empty)


def test_decimal_and_float_amount_equivalent() -> None:
    """Decimal('10.00') and 10.0 normalize via float()/'.2f' to the same hash."""
    txn_float = _base_txn()
    txn_float["amount"] = 10.0
    txn_decimal = _base_txn()
    txn_decimal["amount"] = Decimal("10.00")
    assert generate_transaction_hash(txn_float) == generate_transaction_hash(txn_decimal)


def test_amount_int_and_float_equivalent() -> None:
    """Integer 10 and float 10.0 both format to '10.00'."""
    txn_int = _base_txn()
    txn_int["amount"] = 10
    txn_float = _base_txn()
    txn_float["amount"] = 10.0
    assert generate_transaction_hash(txn_int) == generate_transaction_hash(txn_float)


def test_amount_string_numeric_equivalent_to_float() -> None:
    """A numeric string amount is float()-coerced, matching the float hash."""
    txn_str = _base_txn()
    txn_str["amount"] = "10.00"
    txn_float = _base_txn()
    txn_float["amount"] = 10.0
    assert generate_transaction_hash(txn_str) == generate_transaction_hash(txn_float)


def test_amount_rounds_to_two_decimals() -> None:
    """Amounts differing only beyond two decimals collide ('.2f' truncation)."""
    txn_a = _base_txn()
    txn_a["amount"] = 10.001
    txn_b = _base_txn()
    txn_b["amount"] = 10.004
    assert generate_transaction_hash(txn_a) == generate_transaction_hash(txn_b)


# --- bump_hash_occurrence -------------------------------------------------


def test_bump_zero_returns_base_unchanged() -> None:
    """Occurrence 0 is the original transaction — base hash returned as-is."""
    base = generate_transaction_hash(_base_txn())
    assert bump_hash_occurrence(base, 0) == base


def test_bump_negative_returns_base_unchanged() -> None:
    """Negative occurrences are treated like 0 (no re-hash)."""
    base = generate_transaction_hash(_base_txn())
    assert bump_hash_occurrence(base, -3) == base


def test_bump_positive_produces_distinct_hash() -> None:
    """A positive occurrence re-hashes into a distinct digest."""
    base = generate_transaction_hash(_base_txn())
    bumped = bump_hash_occurrence(base, 1)
    assert bumped != base
    assert len(bumped) == 64
    assert all(c in "0123456789abcdef" for c in bumped)


def test_bump_distinct_per_occurrence() -> None:
    """Each occurrence index yields a different hash for duplicate transactions."""
    base = generate_transaction_hash(_base_txn())
    hashes = {bump_hash_occurrence(base, i) for i in range(1, 6)}
    # 5 distinct bumped hashes (base itself is excluded since occurrence>=1).
    assert len(hashes) == 5
    assert base not in hashes


def test_bump_is_deterministic() -> None:
    """Bumping the same base+occurrence twice yields the same hash."""
    base = generate_transaction_hash(_base_txn())
    assert bump_hash_occurrence(base, 2) == bump_hash_occurrence(base, 2)


def test_bump_matches_explicit_suffix_contract() -> None:
    """Bump hashes SHA-256 of 'base|occurrence' — verify against direct compute."""
    import hashlib

    base = generate_transaction_hash(_base_txn())
    expected = hashlib.sha256(f"{base}|3".encode()).hexdigest()
    assert bump_hash_occurrence(base, 3) == expected
