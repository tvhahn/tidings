"""In-process limiter for failed password verifications.

The ``/api/v1/auth/*`` prefix skips the auth middleware, so ``login``,
``set-password`` and ``sign-out-all`` verify caller-supplied passwords for
anyone who can reach the port. Each verification is a deliberately slow
argon2 call; without a limit, a guessing run gets unbounded attempts.

Two sliding windows bound that:

- **Per client** — keyed on the socket peer (``request.client.host``), never
  ``X-Forwarded-For``, which the caller controls. After ``per_client_limit``
  failures inside ``window_seconds``, that client is refused until its oldest
  failure ages out. A successful verification clears the client's count.
- **Global** — ``global_limit`` failures across all clients in the same
  window, so a guessing run spread over many addresses stays bounded too.

State is a dict of timestamp deques behind one lock. Expired entries are
pruned on every call, and a refused client records nothing, so live memory
stays at most ``global_limit`` timestamps. The clock is injectable for tests.

Concurrent requests that pass :meth:`LoginThrottle.retry_after` before either
records its failure can overshoot a limit by the number of in-flight
verifications; the dedicated two-worker password executor in
:mod:`src.api.dependencies` keeps that overshoot small.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable

PER_CLIENT_LIMIT: Final[int] = 5
GLOBAL_LIMIT: Final[int] = 50
WINDOW_SECONDS: Final[float] = 15 * 60


class LoginThrottle:
    """Sliding-window failure counter, per client and global. Thread-safe."""

    def __init__(
        self,
        *,
        per_client_limit: int = PER_CLIENT_LIMIT,
        global_limit: int = GLOBAL_LIMIT,
        window_seconds: float = WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.per_client_limit = per_client_limit
        self.global_limit = global_limit
        self.window_seconds = window_seconds
        self.clock = clock
        self._lock = threading.Lock()
        self._by_client: dict[str, deque[float]] = {}
        self._global: deque[float] = deque()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._global and self._global[0] <= cutoff:
            self._global.popleft()
        for client in list(self._by_client):
            failures = self._by_client[client]
            while failures and failures[0] <= cutoff:
                failures.popleft()
            if not failures:
                del self._by_client[client]

    def retry_after(self, client: str) -> int | None:
        """Seconds until ``client`` may verify a password again, or ``None`` if allowed now."""
        with self._lock:
            now = self.clock()
            self._prune(now)
            waits: list[float] = []
            failures = self._by_client.get(client)
            if failures is not None and len(failures) >= self.per_client_limit:
                waits.append(failures[-self.per_client_limit] + self.window_seconds - now)
            if len(self._global) >= self.global_limit:
                waits.append(self._global[-self.global_limit] + self.window_seconds - now)
            if not waits:
                return None
            return max(1, math.ceil(max(waits)))

    def record_failure(self, client: str) -> None:
        """Count one failed verification against ``client`` and the global window."""
        with self._lock:
            now = self.clock()
            self._prune(now)
            self._by_client.setdefault(client, deque()).append(now)
            self._global.append(now)

    def record_success(self, client: str) -> None:
        """Clear ``client``'s failure count. The global window keeps its entries."""
        with self._lock:
            self._by_client.pop(client, None)

    def clear(self) -> None:
        """Forget every recorded failure (tests)."""
        with self._lock:
            self._by_client.clear()
            self._global.clear()


# Process-wide instance used by the auth router.
login_throttle = LoginThrottle()
