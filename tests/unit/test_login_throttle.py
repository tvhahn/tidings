"""Unit tests for the in-process failed-password limiter."""

from __future__ import annotations

import threading

from src.api.login_throttle import GLOBAL_LIMIT, PER_CLIENT_LIMIT, WINDOW_SECONDS, LoginThrottle


class _FakeClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _throttle(clock: _FakeClock, **kwargs: int) -> LoginThrottle:
    return LoginThrottle(clock=clock, **kwargs)


class TestDefaults:
    def test_limits_match_documented_policy(self) -> None:
        assert PER_CLIENT_LIMIT == 5
        assert GLOBAL_LIMIT == 50
        assert WINDOW_SECONDS == 900


class TestPerClient:
    def test_allows_until_limit_then_refuses(self) -> None:
        clock = _FakeClock()
        throttle = _throttle(clock)
        for _ in range(PER_CLIENT_LIMIT):
            assert throttle.retry_after("10.0.0.1") is None
            throttle.record_failure("10.0.0.1")
        assert throttle.retry_after("10.0.0.1") == 900

    def test_retry_after_counts_down_from_oldest_failure(self) -> None:
        clock = _FakeClock()
        throttle = _throttle(clock)
        throttle.record_failure("10.0.0.1")
        clock.advance(100)
        for _ in range(PER_CLIENT_LIMIT - 1):
            throttle.record_failure("10.0.0.1")
        clock.advance(0.5)
        # Oldest failure was 100.5s ago → 799.5s left, rounded up.
        assert throttle.retry_after("10.0.0.1") == 800

    def test_other_clients_unaffected(self) -> None:
        clock = _FakeClock()
        throttle = _throttle(clock)
        for _ in range(PER_CLIENT_LIMIT):
            throttle.record_failure("10.0.0.1")
        assert throttle.retry_after("10.0.0.2") is None

    def test_allowed_again_once_window_passes(self) -> None:
        clock = _FakeClock()
        throttle = _throttle(clock)
        for _ in range(PER_CLIENT_LIMIT):
            throttle.record_failure("10.0.0.1")
        clock.advance(WINDOW_SECONDS - 1)
        assert throttle.retry_after("10.0.0.1") == 1
        clock.advance(1)
        assert throttle.retry_after("10.0.0.1") is None

    def test_success_clears_client_count(self) -> None:
        clock = _FakeClock()
        throttle = _throttle(clock)
        for _ in range(PER_CLIENT_LIMIT - 1):
            throttle.record_failure("10.0.0.1")
        throttle.record_success("10.0.0.1")
        for _ in range(PER_CLIENT_LIMIT - 1):
            throttle.record_failure("10.0.0.1")
        assert throttle.retry_after("10.0.0.1") is None


class TestGlobalCap:
    def test_distributed_failures_hit_global_cap(self) -> None:
        clock = _FakeClock()
        throttle = _throttle(clock, global_limit=10)
        for i in range(10):
            throttle.record_failure(f"10.0.0.{i}")
        # A fresh address with no failures of its own is still refused.
        assert throttle.retry_after("192.168.1.1") == 900

    def test_success_does_not_clear_global_window(self) -> None:
        clock = _FakeClock()
        throttle = _throttle(clock, global_limit=3)
        for _ in range(3):
            throttle.record_failure("10.0.0.1")
            throttle.record_success("10.0.0.1")
        assert throttle.retry_after("10.0.0.2") == 900

    def test_global_cap_lifts_after_window(self) -> None:
        clock = _FakeClock()
        throttle = _throttle(clock, global_limit=3)
        for i in range(3):
            throttle.record_failure(f"10.0.0.{i}")
        clock.advance(WINDOW_SECONDS)
        assert throttle.retry_after("10.0.0.9") is None


class TestPruning:
    def test_expired_entries_are_dropped(self) -> None:
        clock = _FakeClock()
        throttle = _throttle(clock)
        for i in range(20):
            throttle.record_failure(f"10.0.0.{i}")
        assert len(throttle._by_client) == 20
        clock.advance(WINDOW_SECONDS)
        throttle.retry_after("10.0.0.99")
        assert throttle._by_client == {}
        assert len(throttle._global) == 0

    def test_partial_expiry_keeps_live_entries(self) -> None:
        clock = _FakeClock()
        throttle = _throttle(clock)
        throttle.record_failure("10.0.0.1")
        clock.advance(WINDOW_SECONDS / 2)
        throttle.record_failure("10.0.0.2")
        clock.advance(WINDOW_SECONDS / 2)
        throttle.retry_after("10.0.0.3")
        assert list(throttle._by_client) == ["10.0.0.2"]
        assert len(throttle._global) == 1

    def test_clear_forgets_everything(self) -> None:
        clock = _FakeClock()
        throttle = _throttle(clock)
        for _ in range(PER_CLIENT_LIMIT):
            throttle.record_failure("10.0.0.1")
        throttle.clear()
        assert throttle.retry_after("10.0.0.1") is None
        assert len(throttle._global) == 0


class TestThreadSafety:
    def test_concurrent_failures_all_counted(self) -> None:
        clock = _FakeClock()
        throttle = _throttle(clock, global_limit=10_000)

        def hammer(client: str) -> None:
            for _ in range(200):
                throttle.record_failure(client)

        threads = [threading.Thread(target=hammer, args=(f"10.0.0.{i}",)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(throttle._global) == 1_600
        assert sum(len(q) for q in throttle._by_client.values()) == 1_600
