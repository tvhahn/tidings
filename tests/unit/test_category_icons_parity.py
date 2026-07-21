"""Guards that Python ALLOWED_ICON_NAMES stays in sync with the TS iconCatalog.

If these diverge, the backend will reject writes of icon names the frontend
has already committed to, or vice versa.
"""

import re
from pathlib import Path

from src.finance.category_icons import ALLOWED_ICON_NAMES

_ICON_CATALOG_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "iconCatalog.ts"


def _parse_ts_catalog() -> set[str]:
    """Extract icon names from the TS catalog by matching `{ name: "Foo", icon: ... }`."""
    text = _ICON_CATALOG_TS.read_text()
    return set(re.findall(r'\{\s*name:\s*"([A-Za-z0-9]+)"\s*,\s*icon:', text))


def test_python_and_ts_icon_allowlists_match():
    ts_names = _parse_ts_catalog()
    py_names = set(ALLOWED_ICON_NAMES)

    assert ts_names, "failed to parse any icon names from iconCatalog.ts"
    assert ts_names == py_names, (
        f"Icon allowlists drifted.\n"
        f"Only in TS: {sorted(ts_names - py_names)}\n"
        f"Only in Python: {sorted(py_names - ts_names)}"
    )
