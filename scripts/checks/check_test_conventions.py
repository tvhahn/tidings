#!/usr/bin/env python3
"""Test-convention ratchet — makes two ad-hoc-pattern bans mechanical.

`docs/TESTS.md` / `tests/CLAUDE.md` require new API tests to use the shared
`api_client` fixture (not hand-rolled `TestClient(app)`) and the body-aware
`assert_ok` / `assert_problem` / `assert_status` helpers (not bare
`assert resp.status_code == ...`, whose failure message swallows the body).
The legacy files below predate the rules and are being migrated by
`scripts/checks/migrate_api_tests.py`; this gate pins their current counts so the
numbers can only go down:

- A file exceeding its pinned count fails.
- Any occurrence in a file not pinned here fails (new ad-hoc usage).
- `conftest.py` files are exempt — the sanctioned fixtures live there.
- A file dropping below its pinned count prints a reminder to lower the pin.

Runs in `make verify-backend` and the CI `backend-lint` job, stdlib only.

Origin: docs/specs/2026-07-15-basis-principles-audit/ (G3 — graduated from
the 2026-07-11 run's Tier 1 #6). The bare-status-assert pattern was added by
the 2026-07-16 Tier-2 test-debt sweep, which drove its baseline to zero.

Usage: python3 scripts/checks/check_test_conventions.py [--root PATH]
Exit 1 on any violation.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

# Pinned legacy counts as of 2026-07-17. The 2026-07-17 migration burned every
# pin down to zero: fresh-app tests moved to the `api_client_factory` fixture and
# shared-app tests to `api_client` (both in tests/conftest.py, exempt from this
# gate), so the baseline is now empty — any `TestClient(` reintroduction outside
# conftest fails the gate. Lower a number when migration shrinks a file; never
# raise one — fix the test to use `api_client` / `api_client_factory` instead.
BASELINE: dict[str, int] = {}

PATTERN = "TestClient("

# Bare `assert <resp>.status_code == <n>` swallows the response body on failure
# (see tests/asserts.py). New tests must use assert_ok/assert_problem/assert_status.
# The 2026-07-16 sweep migrated every occurrence, so this baseline is empty — any
# reintroduction fails the gate. The regex anchors on a line that *starts* with
# `assert` (after indentation) so prose/docstrings mentioning the pattern don't
# count, and matches only `==` (not `!=` / `in (...)`, which are legitimately
# left where a response isn't the JSON error envelope — redirects, HEAD, ranges).
STATUS_ASSERT_BASELINE: dict[str, int] = {}

STATUS_ASSERT_RE = re.compile(r"^[ \t]*assert\b.*\.status_code\s*==", re.MULTILINE)


def _ratchet(
    root: Path,
    *,
    counter: Callable[[str], int],
    baseline: dict[str, int],
    label: str,
    advice: str,
) -> list[str]:
    """Pin one per-file pattern count across tests/: fail when a file exceeds it."""
    errors: list[str] = []
    seen: dict[str, int] = {}
    for path in sorted((root / "tests").rglob("*.py")):
        if path.name == "conftest.py":
            continue
        rel = str(path.relative_to(root))
        count = counter(path.read_text())
        if count:
            seen[rel] = count
    for rel, count in seen.items():
        pinned = baseline.get(rel, 0)
        if count > pinned:
            errors.append(f"{rel}: {count} {label}, pinned at {pinned} — {advice}")
        elif count < pinned:
            print(
                f"note: {rel} is down to {count} {label} (pinned {pinned}) — "
                f"lower its pin in scripts/checks/check_test_conventions.py"
            )
    for rel in baseline:
        if rel not in seen and not (root / rel).exists():
            print(f"note: {rel} is gone — remove its pin from scripts/checks/check_test_conventions.py")
    return errors


def check(root: Path) -> list[str]:
    """Ratchet the ad-hoc `TestClient(` ban."""
    return _ratchet(
        root,
        counter=lambda text: text.count(PATTERN),
        baseline=BASELINE,
        label=f"`{PATTERN}` occurrence(s)",
        advice="use the `api_client` fixture (tests/conftest.py) instead",
    )


def check_status_asserts(root: Path) -> list[str]:
    """Ratchet the bare `assert …status_code ==` ban."""
    return _ratchet(
        root,
        counter=lambda text: len(STATUS_ASSERT_RE.findall(text)),
        baseline=STATUS_ASSERT_BASELINE,
        label="bare `assert …status_code ==`",
        advice="use assert_ok/assert_problem/assert_status (tests/asserts.py) instead",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()
    errors = check(root) + check_status_asserts(root)
    if errors:
        print(f"test-convention ratchet: {len(errors)} violation(s)")
        for err in errors:
            print(f"  {err}")
        return 1
    print("test-convention ratchet: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
