"""Decimal conversion utilities."""

import json
from decimal import Decimal
from typing import Any

__all__ = [
    "DecimalEncoder",
    "decimal_to_float",
    "decimals_to_floats",
    "floats_to_decimals",
    "to_decimal",
]


def decimal_to_float(value: Any) -> float | None:
    """Convert a Decimal (or other numeric) to float, passing through None."""
    if value is None:
        return None
    return float(value)


def to_decimal(value: Any) -> Any:
    """Convert a float scalar to Decimal via str(), passing everything else through.

    This is the load-bearing DynamoDB write boundary: boto3 rejects Python
    floats, so numeric fields must be Decimal. Non-float values (str, int,
    Decimal, None, ...) are returned unchanged.
    """
    if isinstance(value, float):
        return Decimal(str(value))
    return value


def floats_to_decimals(obj: Any) -> Any:
    """Recursively convert float values to Decimal for DynamoDB compatibility.

    Recurses through dict values and list elements; float scalars become
    ``Decimal(str(value))`` and everything else passes through unchanged.
    """
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: floats_to_decimals(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [floats_to_decimals(v) for v in obj]
    return obj


def decimals_to_floats(obj: Any) -> Any:
    """Recursively convert Decimal values to float so the structure is JSON-safe.

    Recurses through dict values, list elements, and tuple elements (tuples
    are rebuilt as tuples). Decimal scalars become ``float(value)`` and
    everything else passes through unchanged.
    """
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: decimals_to_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [decimals_to_floats(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(decimals_to_floats(v) for v in obj)
    return obj


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that converts Decimal to float (for DynamoDB compatibility)."""

    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)
