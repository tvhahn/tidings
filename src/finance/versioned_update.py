"""Shared optimistic-lock read-modify-write mechanic.

Config/budget mutations follow one shape: read the current item, extract its
optimistic-lock ``Version``, transform the payload, then put it back guarded by
that version. This module centralizes the write/retry/skip mechanics so the
category-cascade helpers and the backup-import applier stop hand-rolling it.

Two pieces, deliberately small and backend-agnostic (no HTTP, no FastAPI):

* :func:`item_version` — the ``int(item.get("Version", 0))`` extraction every
  cascade site repeats.
* :func:`versioned_update` — the write loop: run a caller-supplied ``plan``
  (read + transform → payload + version, or ``None`` to skip the write), then
  ``put`` it. Optionally retry once on :class:`VersionConflictError`, re-running
  ``plan`` so the version is re-read (the backup-import shape).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.finance.exceptions import VersionConflictError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


def item_version(item: Mapping[str, Any]) -> int:
    """Extract the optimistic-lock version from a storage item."""
    return int(item.get("Version", 0))


@dataclass(frozen=True)
class Update[T]:
    """A planned write: the payload plus the version guarding it.

    ``version`` is ``None`` on the create-from-defaults path (some services
    read ``expected_version is None`` as "create").
    """

    data: T
    version: int | None


def versioned_update[T, R](
    plan: Callable[[], Update[T] | None],
    put: Callable[[T, int | None], R],
    *,
    retry_on_conflict: bool = False,
) -> R | None:
    """Run a read-modify-write.

    ``plan`` reads current state and returns the :class:`Update` to write, or
    ``None`` to skip the write entirely (the no-change short-circuit). ``put``
    performs the version-guarded write and its result is returned.

    When ``retry_on_conflict`` is set, a :class:`VersionConflictError` from the
    first attempt re-runs ``plan`` (re-reading the version) and retries once;
    a second conflict propagates. Without it, any conflict propagates on the
    first attempt. Returns ``None`` when ``plan`` skipped.
    """
    attempts = 2 if retry_on_conflict else 1
    for attempt in range(attempts):
        try:
            update = plan()
            if update is None:
                return None
            return put(update.data, update.version)
        except VersionConflictError:
            if attempt == attempts - 1:
                raise
    return None  # unreachable: loop either returns or raises
