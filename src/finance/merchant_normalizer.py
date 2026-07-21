"""Merchant name normalization: regex cleanup and alias resolution."""

import re
from collections.abc import Mapping

# Patterns to strip from merchant names (case-insensitive)
_CLEANUP_PATTERNS = [
    # Store/location numbers: "#1234", "# 1234", "Store 1234", "Loc 1234"
    r"\s*#\s*\d+\s*$",
    r"\s+(?:store|loc(?:ation)?|branch|unit)\s*#?\s*\d+\s*$",
    # Trailing province abbreviation: "... BC", "... ON"
    r"\s+(?:AB|BC|MB|NB|NL|NS|NT|NU|ON|PE|QC|SK|YT)\s*$",
    # Trailing country codes
    r"\s+(?:CA|CAN|US|USA)\s*$",
    # Trailing whitespace/punctuation artifacts
    r"[\s\-*#]+$",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _CLEANUP_PATTERNS]


def normalize_merchant(name: str, aliases: Mapping[str, str] | None = None) -> str:
    """Clean up a merchant name and apply alias mapping.

    1. Apply regex cleanup patterns (strip store numbers, locations, etc.)
    2. Look up in aliases dict (case-insensitive) for canonical name

    Args:
        name: Raw merchant/company name.
        aliases: Optional dict mapping raw names (lowercase) to canonical names.

    Returns:
        Cleaned or aliased merchant name.
    """
    if not name:
        return name

    cleaned = name.strip()
    changed = True
    while changed:
        changed = False
        for pattern in _COMPILED:
            result = pattern.sub("", cleaned).strip()
            if result != cleaned:
                cleaned = result
                changed = True

    if not cleaned:
        cleaned = name.strip()

    # Alias lookup (case-insensitive)
    if aliases:
        canonical = aliases.get(cleaned.lower())
        if canonical:
            return canonical

    return cleaned
