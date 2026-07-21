"""Tests for the daily summary scheduler.

Covers the time-parsing helper, the next-firing computation, and the loop's
respect for config toggles. Async portions run via ``asyncio.run()`` to
avoid a new pytest-asyncio dependency.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from src.finance import daily_summary_scheduler as sched

# Timezone offsets swept by the boundary tests below: the extreme west
# (UTC-11), a plain negative offset, UTC, a half-hour offset, and the extreme
# east (UTC+14). All five are DST-free on 2026-05-07 so ``.replace()``-based
# firing math has no fold ambiguity to reason about.
_SWEEP_ZONES = [
    "Pacific/Pago_Pago",  # UTC-11
    "America/Lima",  # UTC-05:00 (no DST)
    "UTC",  # UTC+00:00
    "Asia/Kolkata",  # UTC+05:30
    "Pacific/Kiritimati",  # UTC+14
]


class TestParseScheduleTime:
    def test_valid_hh_mm(self):
        assert sched._parse_schedule_time("07:30") == time(7, 30)
        assert sched._parse_schedule_time("19:00") == time(19, 0)
        assert sched._parse_schedule_time("23:59") == time(23, 59)

    def test_none_falls_back(self):
        assert sched._parse_schedule_time(None) == time(19, 0)

    def test_empty_falls_back(self):
        assert sched._parse_schedule_time("") == time(19, 0)

    def test_garbage_falls_back(self):
        assert sched._parse_schedule_time("not-a-time") == time(19, 0)
        assert sched._parse_schedule_time("99:99") == time(19, 0)


class TestNextFiring:
    def test_today_if_before(self):
        tz = ZoneInfo("America/Los_Angeles")
        now = datetime(2026, 5, 7, 10, 0, tzinfo=tz)
        result = sched._next_firing(now, time(19, 0))
        assert result == datetime(2026, 5, 7, 19, 0, tzinfo=tz)

    def test_tomorrow_if_after(self):
        tz = ZoneInfo("America/Los_Angeles")
        now = datetime(2026, 5, 7, 21, 0, tzinfo=tz)
        result = sched._next_firing(now, time(19, 0))
        assert result == datetime(2026, 5, 8, 19, 0, tzinfo=tz)

    def test_tomorrow_if_exactly_at(self):
        tz = ZoneInfo("America/Los_Angeles")
        now = datetime(2026, 5, 7, 19, 0, tzinfo=tz)
        result = sched._next_firing(now, time(19, 0))
        assert result == datetime(2026, 5, 8, 19, 0, tzinfo=tz)


class TestRunSchedulerSkips:
    def test_shutdown_already_set_returns_promptly(self, tmp_path, monkeypatch):
        """Pre-set shutdown should let the loop exit on its first wait_for."""
        monkeypatch.setattr(sched, "_SUMMARIES_DIR", tmp_path / "journal")

        async def runner():
            shutdown = asyncio.Event()
            shutdown.set()
            with patch.object(sched, "get_config", return_value={"daily_summary_provider": "disabled"}):
                await asyncio.wait_for(sched.run_scheduler(shutdown), timeout=2.0)

        asyncio.run(runner())

    def test_skips_when_provider_disabled(self, tmp_path, monkeypatch):
        """A wake-up with provider 'disabled' takes the skip branch, not generate.

        Shrinking ``_MIN_WAIT_SECONDS`` lets the loop wake, re-read config, and
        hit the disabled-skip path in one fast iteration; the second
        ``_next_firing`` call trips shutdown so the loop exits cleanly. The
        ``wakes >= 2`` assertion proves we actually reached the skip branch
        rather than exiting during the first wait.
        """
        monkeypatch.setattr(sched, "_SUMMARIES_DIR", tmp_path / "journal")
        monkeypatch.setattr(sched, "_MIN_WAIT_SECONDS", 0.01)

        cfg = {
            "daily_summary_provider": "disabled",
            "enable_daily_summaries": True,
            "daily_summary_schedule_time": "19:00",
        }

        async def runner():
            shutdown = asyncio.Event()
            mock_gen = AsyncMock(name="_generate_for_today")
            wakes = 0

            def near_now_firing(now, _t):
                nonlocal wakes
                wakes += 1
                if wakes >= 2:  # one full skip iteration is enough — end the loop
                    shutdown.set()
                return now + timedelta(milliseconds=1)

            with (
                patch.object(sched, "get_config", return_value=cfg),
                patch.object(sched, "_generate_for_today", new=mock_gen),
                patch.object(sched, "_next_firing", side_effect=near_now_firing),
            ):
                await asyncio.wait_for(sched.run_scheduler(shutdown), timeout=2.0)

            mock_gen.assert_not_called()
            assert wakes >= 2

        asyncio.run(runner())

    def test_skips_when_summaries_off(self, tmp_path, monkeypatch):
        """A wake-up with the daily-summaries toggle off takes the skip branch."""
        monkeypatch.setattr(sched, "_SUMMARIES_DIR", tmp_path / "journal")
        monkeypatch.setattr(sched, "_MIN_WAIT_SECONDS", 0.01)

        cfg = {
            "daily_summary_provider": "openai",
            "enable_daily_summaries": False,
            "daily_summary_schedule_time": "19:00",
        }

        async def runner():
            shutdown = asyncio.Event()
            mock_gen = AsyncMock(name="_generate_for_today")
            wakes = 0

            def near_now_firing(now, _t):
                nonlocal wakes
                wakes += 1
                if wakes >= 2:
                    shutdown.set()
                return now + timedelta(milliseconds=1)

            with (
                patch.object(sched, "get_config", return_value=cfg),
                patch.object(sched, "_generate_for_today", new=mock_gen),
                patch.object(sched, "_next_firing", side_effect=near_now_firing),
            ):
                await asyncio.wait_for(sched.run_scheduler(shutdown), timeout=2.0)

            mock_gen.assert_not_called()
            assert wakes >= 2

        asyncio.run(runner())

    def test_fires_when_enabled(self, tmp_path, monkeypatch, freeze_clock):
        """Wake-up with provider + toggle on must call _generate_for_today.

        Event-driven: a shrunk wait floor lets the loop wake fast, and the test
        proceeds the instant generate is invoked (the mock sets ``fired``)
        instead of sleeping past a fixed threshold.
        """
        monkeypatch.setattr(sched, "_SUMMARIES_DIR", tmp_path / "journal")
        monkeypatch.setattr(sched, "_MIN_WAIT_SECONDS", 0.01)
        today = freeze_clock(sched).date()
        month_dir = tmp_path / "journal" / today.strftime("%Y-%m")
        month_dir.mkdir(parents=True)
        (month_dir / f"{today.day:02d}.txt").write_text("seeded")  # skip startup catch-up

        cfg = {
            "daily_summary_provider": "openai",
            "enable_daily_summaries": True,
            "daily_summary_schedule_time": "19:00",
        }

        async def runner():
            shutdown = asyncio.Event()
            fired = asyncio.Event()
            mock_gen = AsyncMock(name="_generate_for_today", side_effect=lambda: fired.set())

            def near_now_firing(now, _t):
                return now + timedelta(milliseconds=1)

            with (
                patch.object(sched, "get_config", return_value=cfg),
                patch.object(sched, "_generate_for_today", new=mock_gen),
                patch.object(sched, "_next_firing", side_effect=near_now_firing),
            ):
                task = asyncio.create_task(sched.run_scheduler(shutdown))
                await asyncio.wait_for(fired.wait(), timeout=2.0)
                shutdown.set()
                await asyncio.wait_for(task, timeout=2.0)

            assert mock_gen.await_count >= 1

        asyncio.run(runner())


class TestStartupCatchUp:
    def test_catchup_skipped_when_summary_exists(self, tmp_path, monkeypatch, freeze_clock):
        """If today's file already exists, catch-up must not fire."""
        monkeypatch.setattr(sched, "_SUMMARIES_DIR", tmp_path / "journal")
        today = freeze_clock(sched).date()
        month_dir = tmp_path / "journal" / today.strftime("%Y-%m")
        month_dir.mkdir(parents=True)
        (month_dir / f"{today.day:02d}.txt").write_text("existing summary")

        cfg = {
            "daily_summary_provider": "openai",
            "enable_daily_summaries": True,
            "daily_summary_schedule_time": "00:01",
        }

        async def runner():
            shutdown = asyncio.Event()
            shutdown.set()
            mock_gen = AsyncMock(name="_generate_for_today")

            with (
                patch.object(sched, "get_config", return_value=cfg),
                patch.object(sched, "_generate_for_today", new=mock_gen),
            ):
                await sched.run_scheduler(shutdown)

            mock_gen.assert_not_called()

        asyncio.run(runner())

    def test_catchup_skipped_when_provider_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sched, "_SUMMARIES_DIR", tmp_path / "journal")

        cfg = {
            "daily_summary_provider": "disabled",
            "enable_daily_summaries": True,
            "daily_summary_schedule_time": "00:01",
        }

        async def runner():
            shutdown = asyncio.Event()
            shutdown.set()
            mock_gen = AsyncMock(name="_generate_for_today")

            with (
                patch.object(sched, "get_config", return_value=cfg),
                patch.object(sched, "_generate_for_today", new=mock_gen),
            ):
                await sched.run_scheduler(shutdown)

            mock_gen.assert_not_called()

        asyncio.run(runner())

    def test_catchup_fires_when_due_and_no_summary(self, tmp_path, monkeypatch, freeze_clock):
        """Time already passed today + no summary file → catch-up generates once."""
        monkeypatch.setattr(sched, "_SUMMARIES_DIR", tmp_path / "journal")  # empty → not exists
        freeze_clock(sched)  # 20:00 local — past the 00:01 firing

        cfg = {
            "daily_summary_provider": "openai",
            "enable_daily_summaries": True,
            "daily_summary_schedule_time": "00:01",  # past the frozen clock → catch-up is due
        }

        async def runner():
            shutdown = asyncio.Event()
            shutdown.set()  # exit the loop immediately after the startup catch-up
            mock_gen = AsyncMock(name="_generate_for_today")

            with (
                patch.object(sched, "get_config", return_value=cfg),
                patch.object(sched, "_generate_for_today", new=mock_gen),
            ):
                await sched.run_scheduler(shutdown)

            mock_gen.assert_awaited_once()

        asyncio.run(runner())

    def test_catchup_survives_config_error(self, tmp_path, monkeypatch):
        """A raising get_config in the catch-up block is caught, not propagated."""
        monkeypatch.setattr(sched, "_SUMMARIES_DIR", tmp_path / "journal")

        async def runner():
            shutdown = asyncio.Event()
            shutdown.set()  # while-loop is skipped; only the catch-up runs
            with patch.object(sched, "get_config", side_effect=RuntimeError("config boom")):
                # Must return cleanly rather than let the exception escape the task.
                await asyncio.wait_for(sched.run_scheduler(shutdown), timeout=2.0)

        asyncio.run(runner())


class TestRunSchedulerBackoff:
    def test_loop_backs_off_on_generation_error(self, tmp_path, monkeypatch, freeze_clock):
        """A raising _generate_for_today is caught and the loop enters backoff,
        from which a shutdown wakes it and returns."""
        monkeypatch.setattr(sched, "_SUMMARIES_DIR", tmp_path / "journal")
        monkeypatch.setattr(sched, "_MIN_WAIT_SECONDS", 0.01)
        today = freeze_clock(sched).date()
        month_dir = tmp_path / "journal" / today.strftime("%Y-%m")
        month_dir.mkdir(parents=True)
        (month_dir / f"{today.day:02d}.txt").write_text("seeded")  # skip catch-up

        cfg = {
            "daily_summary_provider": "openai",
            "enable_daily_summaries": True,
            "daily_summary_schedule_time": "19:00",
        }

        async def runner():
            shutdown = asyncio.Event()
            fired = asyncio.Event()

            def boom():
                fired.set()
                raise RuntimeError("generation boom")

            mock_gen = AsyncMock(name="_generate_for_today", side_effect=boom)

            def near_now_firing(now, _t):
                return now + timedelta(milliseconds=1)

            with (
                patch.object(sched, "get_config", return_value=cfg),
                patch.object(sched, "_generate_for_today", new=mock_gen),
                patch.object(sched, "_next_firing", side_effect=near_now_firing),
            ):
                task = asyncio.create_task(sched.run_scheduler(shutdown))
                await asyncio.wait_for(fired.wait(), timeout=2.0)
                shutdown.set()  # wake the failure-backoff wait_for → return
                await asyncio.wait_for(task, timeout=2.0)

            assert mock_gen.await_count >= 1

        asyncio.run(runner())


class TestGenerateForToday:
    def test_logs_on_successful_kick_off(self):
        """_generate_for_today awaits kick_off_generation and logs the result."""
        result = SimpleNamespace(status="queued", dates_queued=1)
        with (
            patch(
                "src.api.routers.daily_summaries.kick_off_generation",
                new=AsyncMock(name="kick_off_generation", return_value=result),
            ) as mock_kick,
            patch("src.api.dependencies.get_spending_summary", return_value=MagicMock()),
            patch("src.api.dependencies.get_budget_service", return_value=MagicMock()),
        ):
            asyncio.run(sched._generate_for_today())

        mock_kick.assert_awaited_once()

    def test_swallows_http_exception_from_kick_off(self):
        """A provider-disabled / already-running HTTPException is a normal state."""
        from fastapi import HTTPException

        with (
            patch(
                "src.api.routers.daily_summaries.kick_off_generation",
                new=AsyncMock(side_effect=HTTPException(status_code=409, detail="already running")),
            ),
            patch("src.api.dependencies.get_spending_summary", return_value=MagicMock()),
            patch("src.api.dependencies.get_budget_service", return_value=MagicMock()),
        ):
            # Must not raise — the handler logs and returns.
            asyncio.run(sched._generate_for_today())


class TestNextFiringTimezoneSweep:
    """Sweep ``_next_firing`` across offset extremes and boundary instants.

    ``_next_firing`` is pure — it takes an aware ``now``, so no clock freeze is
    needed. The invariants that must hold in *every* timezone: the next firing
    is strictly in the future, carries the scheduled wall-clock HH:MM, keeps
    ``now``'s tzinfo, and lands today when the schedule minute is still ahead or
    tomorrow once it has arrived (including the local-midnight straddle).
    """

    @pytest.mark.parametrize("zone", _SWEEP_ZONES)
    @pytest.mark.parametrize(
        ("now_hms", "scheduled", "expect_tomorrow"),
        [
            # Straddling the configured schedule minute (19:00).
            ((18, 59, 0), time(19, 0), False),
            ((19, 0, 0), time(19, 0), True),  # exactly-at fires tomorrow
            ((19, 30, 0), time(19, 0), True),
            # Straddling local midnight, schedule just after it (00:01).
            ((0, 0, 30), time(0, 1), False),
            ((0, 1, 0), time(0, 1), True),
            ((23, 59, 0), time(0, 1), True),  # late-night → next day's 00:01
        ],
    )
    def test_boundaries(self, zone, now_hms, scheduled, expect_tomorrow):
        tz = ZoneInfo(zone)
        hour, minute, second = now_hms
        now = datetime(2026, 5, 7, hour, minute, second, tzinfo=tz)

        result = sched._next_firing(now, scheduled)

        assert result > now  # always strictly in the future
        assert (result.hour, result.minute) == (scheduled.hour, scheduled.minute)
        assert result.second == 0
        assert result.microsecond == 0
        assert result.tzinfo is now.tzinfo
        expected_day = now.date() + timedelta(days=1 if expect_tomorrow else 0)
        assert result.date() == expected_day


class TestStartupCatchUpTimezoneSweep:
    """Sweep the startup catch-up decision across offset extremes.

    Catch-up must fire iff the scheduled time has already passed *in the app
    timezone* AND no summary file exists for the app-tz date. The clock and the
    app timezone are frozen together (via ``freeze_clock``) so the decision
    depends only on the seeded file and the schedule minute — never the host
    ``TZ`` or the real wall clock.
    """

    @pytest.mark.parametrize("zone", _SWEEP_ZONES)
    @pytest.mark.parametrize(
        ("now_hour", "scheduled", "seed_summary", "expect_fire"),
        [
            (20, "00:01", False, True),  # past schedule, no file → fire
            (20, "00:01", True, False),  # past schedule, file exists → skip
            (0, "23:59", False, False),  # before schedule → skip
        ],
    )
    def test_catchup_decision(
        self, zone, now_hour, scheduled, seed_summary, expect_fire, tmp_path, monkeypatch, freeze_clock
    ):
        monkeypatch.setattr(sched, "_SUMMARIES_DIR", tmp_path / "journal")
        at = datetime(2026, 5, 7, now_hour, 0, tzinfo=ZoneInfo(zone))
        today = freeze_clock(sched, at=at).date()

        if seed_summary:
            month_dir = tmp_path / "journal" / today.strftime("%Y-%m")
            month_dir.mkdir(parents=True)
            (month_dir / f"{today.day:02d}.txt").write_text("existing summary")

        cfg = {
            "daily_summary_provider": "openai",
            "enable_daily_summaries": True,
            "daily_summary_schedule_time": scheduled,
        }

        async def runner():
            shutdown = asyncio.Event()
            shutdown.set()  # run only the startup catch-up, then exit
            mock_gen = AsyncMock(name="_generate_for_today")

            with (
                patch.object(sched, "get_config", return_value=cfg),
                patch.object(sched, "_generate_for_today", new=mock_gen),
            ):
                await sched.run_scheduler(shutdown)

            if expect_fire:
                mock_gen.assert_awaited_once()
            else:
                mock_gen.assert_not_called()

        asyncio.run(runner())
