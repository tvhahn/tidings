"""CSV formula-injection guard for exported free-text cells.

Merchant names, notes and email fields can originate in inbound email, so a
value like ``=HYPERLINK(...)`` would run as a formula when an export is opened
in a spreadsheet. :func:`csv_safe_text` prefixes such values with ``'`` (the
OWASP-recommended neutralizer). Apply it only to free-text columns — never to
numeric or date columns, whose leading ``-`` is meaningful.

The backup CSV is re-importable, so :func:`csv_unguard_text` reverses exactly
that prefix on import. Values that already begin with ``'`` ahead of a trigger
character get one more ``'`` on export, which keeps the pair lossless: every
text value round-trips byte-identical.
"""

from __future__ import annotations

import re
from typing import Any

# A value that (after any leading quotes) starts with a spreadsheet formula
# trigger: = + - @ tab CR.
_NEEDS_GUARD_RE = re.compile(r"^'*[=+\-@\t\r]")


def csv_safe_text(value: Any) -> Any:
    """Prefix ``'`` to a string that a spreadsheet would read as a formula; other values pass through."""
    if isinstance(value, str) and _NEEDS_GUARD_RE.match(value):
        return "'" + value
    return value


def csv_unguard_text(value: str) -> str:
    """Remove the ``'`` that :func:`csv_safe_text` added; any other value is returned unchanged."""
    if value.startswith("'") and _NEEDS_GUARD_RE.match(value[1:]):
        return value[1:]
    return value
