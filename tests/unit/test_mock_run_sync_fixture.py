"""Guards for the shared ``mock_run_sync`` fixture (tests/conftest.py).

The fixture patches ``src.api.routers.<name>.run_sync`` for a router name passed
via indirect parametrization. Its ``RouterName`` allowlist is what lets a typo
fail fast with a helpful message instead of an opaque ModuleNotFoundError — but
a hardcoded allowlist is exactly the kind of "maintained by hand" list that
drifts. This test makes it self-validating: the allowlist must equal the set of
router modules that actually expose ``run_sync``.
"""

from __future__ import annotations

import importlib
from pathlib import Path

from tests.conftest import _RUN_SYNC_ROUTERS

_ROUTERS_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "api" / "routers"


def _routers_exposing_run_sync() -> set[str]:
    """Router module stems whose namespace holds ``run_sync`` (i.e. patchable).

    Uses ``hasattr`` rather than a text grep because the fixture's patch target
    (``src.api.routers.<name>.run_sync``) resolves against the module's actual
    namespace — the only thing that decides whether the patch succeeds.
    """
    exposing: set[str] = set()
    for path in sorted(_ROUTERS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        module = importlib.import_module(f"src.api.routers.{path.stem}")
        if hasattr(module, "run_sync"):
            exposing.add(path.stem)
    return exposing


def test_run_sync_allowlist_matches_source() -> None:
    """``_RUN_SYNC_ROUTERS`` must list exactly the routers exposing run_sync.

    A router added with run_sync but missing here would be un-mockable via the
    fixture; a stale name here would mask a typo the fixture is meant to catch.
    """
    assert _routers_exposing_run_sync() == _RUN_SYNC_ROUTERS
