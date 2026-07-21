"""Coverage for the FastAPI ``lifespan`` context manager in src.api.main.

The shared ``api_client`` fixture deliberately never triggers startup, so the
whole lifespan (demo autoload, daily-summary scheduler start, and the shutdown
path) is otherwise unexercised. These tests drive the async context manager
DIRECTLY via ``asyncio.run`` — no ``TestClient``, which would both risk blocking
on lifecycle hooks and trip the ``TestClient`` convention ratchet.

Collaborators are monkeypatched, never run:
- ``ensure_demo_loaded`` / ``run_scheduler`` are patched where lifespan imports
  them at call time (``src.finance.demo_loader`` / ``daily_summary_scheduler``).
- ``run_scheduler`` stubs are real awaited coroutines (not AsyncMock leftovers)
  so the active ``filterwarnings error::RuntimeWarning`` gate stays green.
- ``shutdown_executor`` is patched to a no-op on the main module — the real one
  tears down the module-global ThreadPoolExecutor that ``run_sync`` shares, which
  would break every later test in the process.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import src.api.main as main


def _pin_config(monkeypatch, **overrides):
    """Copy the autouse-pinned resolved config, override keys on a fresh _cache."""
    from src.finance import app_config

    cfg = dict(app_config.get_config())
    cfg.update(overrides)
    monkeypatch.setattr(app_config, "_cache", cfg)


def _drive_lifespan(post_exit_settle: float = 0.0) -> None:
    """Enter and exit ``lifespan`` once on a throwaway event loop.

    ``post_exit_settle`` lets a just-cancelled scheduler task finalize on the
    loop before it closes (used only by the timeout/cancel test).
    """

    async def _driver() -> None:
        async with main.lifespan(SimpleNamespace()):
            pass
        if post_exit_settle:
            await asyncio.sleep(post_exit_settle)

    asyncio.run(_driver())


def test_demo_and_serve_frontend_autoloads_without_scheduler(monkeypatch):
    """demo_mode + serve-frontend → ensure_demo_loaded once, scheduler NOT started."""
    from src.finance import daily_summary_scheduler, demo_loader

    monkeypatch.delenv("SERVE_FRONTEND", raising=False)  # default true
    _pin_config(monkeypatch, demo_mode=True, storage="sqlite")

    ensure_demo_loaded = MagicMock(name="ensure_demo_loaded")
    run_scheduler = MagicMock(name="run_scheduler")
    monkeypatch.setattr(demo_loader, "ensure_demo_loaded", ensure_demo_loaded)
    monkeypatch.setattr(daily_summary_scheduler, "run_scheduler", run_scheduler)
    shutdown_executor = MagicMock(name="shutdown_executor")
    monkeypatch.setattr(main, "shutdown_executor", shutdown_executor)

    _drive_lifespan()

    ensure_demo_loaded.assert_called_once_with()
    run_scheduler.assert_not_called()
    shutdown_executor.assert_called_once_with()


def test_demo_with_dynamodb_skips_autoload(monkeypatch):
    """demo_mode but storage=dynamodb → seeded-fixture autoload is skipped."""
    from src.finance import daily_summary_scheduler, demo_loader

    monkeypatch.delenv("SERVE_FRONTEND", raising=False)
    _pin_config(monkeypatch, demo_mode=True, storage="dynamodb")

    ensure_demo_loaded = MagicMock(name="ensure_demo_loaded")
    run_scheduler = MagicMock(name="run_scheduler")
    monkeypatch.setattr(demo_loader, "ensure_demo_loaded", ensure_demo_loaded)
    monkeypatch.setattr(daily_summary_scheduler, "run_scheduler", run_scheduler)
    monkeypatch.setattr(main, "shutdown_executor", MagicMock(name="shutdown_executor"))

    _drive_lifespan()

    ensure_demo_loaded.assert_not_called()
    run_scheduler.assert_not_called()


def test_non_demo_serve_frontend_starts_and_awaits_scheduler(monkeypatch):
    """non-demo + serve-frontend → scheduler task started and cleanly awaited on exit."""
    from src.finance import daily_summary_scheduler, demo_loader

    monkeypatch.delenv("SERVE_FRONTEND", raising=False)
    _pin_config(monkeypatch, demo_mode=False, storage="sqlite")

    ensure_demo_loaded = MagicMock(name="ensure_demo_loaded")
    monkeypatch.setattr(demo_loader, "ensure_demo_loaded", ensure_demo_loaded)

    received = {}
    finished = []

    async def fake_run_scheduler(shutdown: asyncio.Event) -> None:
        received["event"] = shutdown
        await shutdown.wait()
        finished.append(True)

    monkeypatch.setattr(daily_summary_scheduler, "run_scheduler", fake_run_scheduler)
    monkeypatch.setattr(main, "shutdown_executor", MagicMock(name="shutdown_executor"))

    _drive_lifespan()

    ensure_demo_loaded.assert_not_called()
    # Scheduler ran, was handed a real Event, and returned once it was set on exit.
    assert isinstance(received.get("event"), asyncio.Event)
    assert received["event"].is_set()
    assert finished == [True]


def test_scheduler_that_ignores_shutdown_is_cancelled(monkeypatch):
    """Scheduler that ignores the event → wait_for timeout → task cancelled."""
    from src.finance import daily_summary_scheduler, demo_loader

    monkeypatch.delenv("SERVE_FRONTEND", raising=False)
    _pin_config(monkeypatch, demo_mode=False, storage="sqlite")

    monkeypatch.setattr(demo_loader, "ensure_demo_loaded", MagicMock(name="ensure_demo_loaded"))
    monkeypatch.setattr(main, "shutdown_executor", MagicMock(name="shutdown_executor"))

    cancelled = []

    async def stubborn_run_scheduler(shutdown: asyncio.Event) -> None:
        try:
            await asyncio.sleep(0.5)  # ignores the shutdown event
        except asyncio.CancelledError:
            cancelled.append(True)
            # Re-raise so wait_for surfaces TimeoutError into lifespan's except,
            # exercising the scheduler_task.cancel() path (not just wait_for's own
            # internal cancel, which a swallowed CancelledError would mask).
            raise

    monkeypatch.setattr(daily_summary_scheduler, "run_scheduler", stubborn_run_scheduler)

    # Force the 5.0s wait down so the test stays well under a second, without
    # actually sleeping through the real timeout.
    real_wait_for = asyncio.wait_for

    async def fast_wait_for(awaitable, timeout):
        return await real_wait_for(awaitable, timeout=0.05)

    monkeypatch.setattr(asyncio, "wait_for", fast_wait_for)

    _drive_lifespan(post_exit_settle=0.1)

    assert cancelled == [True]


def test_headless_skips_autoload_and_scheduler(monkeypatch):
    """SERVE_FRONTEND=false → neither demo autoload nor scheduler; executor still shut down."""
    from src.finance import daily_summary_scheduler, demo_loader

    monkeypatch.setenv("SERVE_FRONTEND", "false")
    _pin_config(monkeypatch, demo_mode=True, storage="sqlite")

    ensure_demo_loaded = MagicMock(name="ensure_demo_loaded")
    run_scheduler = MagicMock(name="run_scheduler")
    monkeypatch.setattr(demo_loader, "ensure_demo_loaded", ensure_demo_loaded)
    monkeypatch.setattr(daily_summary_scheduler, "run_scheduler", run_scheduler)
    shutdown_executor = MagicMock(name="shutdown_executor")
    monkeypatch.setattr(main, "shutdown_executor", shutdown_executor)

    _drive_lifespan()

    ensure_demo_loaded.assert_not_called()
    run_scheduler.assert_not_called()
    shutdown_executor.assert_called_once_with()
