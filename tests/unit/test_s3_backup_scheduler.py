"""Tests for the S3 backup scheduler.

Mirrors the daily-summary scheduler technique: async portions run via
``asyncio.run`` (no pytest-asyncio). ``run_backup``, ``get_config``,
``_has_aws_credentials`` and ``notification_service.send_raw`` are patched in
the scheduler's namespace; the state-file path is redirected by monkeypatching
``s3_backup_shared.DEFAULT_STATE_PATH``. The loop's waits are replaced by a
controllable fake so tests drive a precise number of iterations.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from src.finance import s3_backup_scheduler as sched
from src.finance import s3_backup_shared
from src.finance.s3_backup import BackupRunResult


def _make_wait(stop_after: int):
    """Fake ``_wait`` that returns False until its ``stop_after``-th call, then
    sets shutdown and returns True — bounding the loop deterministically."""
    calls = 0

    async def _wait(shutdown: asyncio.Event, _seconds: float) -> bool:
        nonlocal calls
        calls += 1
        if calls >= stop_after:
            shutdown.set()
            return True
        return False

    return _wait


def _enabled_cfg() -> dict:
    return {"s3_backup_enabled": True, "s3_backup_bucket": "my-bucket", "s3_backup_prefix": None}


def test_shutdown_already_set_exits_promptly(tmp_path, monkeypatch):
    monkeypatch.setattr(s3_backup_shared, "DEFAULT_STATE_PATH", tmp_path / "state.json")
    mock_backup = MagicMock(name="run_backup")

    async def runner():
        shutdown = asyncio.Event()
        shutdown.set()
        with (
            patch.object(sched, "get_config", return_value=_enabled_cfg()),
            patch.object(sched, "run_backup", new=mock_backup),
            patch.object(sched, "_has_aws_credentials", return_value=True),
        ):
            await asyncio.wait_for(sched.run_s3_backup_scheduler(shutdown), timeout=2.0)

    asyncio.run(runner())
    mock_backup.assert_not_called()


def test_disabled_config_no_run_no_state_write(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(s3_backup_shared, "DEFAULT_STATE_PATH", state_path)
    mock_backup = MagicMock(name="run_backup")
    cfg = {"s3_backup_enabled": False, "s3_backup_bucket": None, "s3_backup_prefix": None}

    async def runner():
        shutdown = asyncio.Event()
        with (
            patch.object(sched, "get_config", return_value=cfg),
            patch.object(sched, "run_backup", new=mock_backup),
            patch.object(sched, "_has_aws_credentials", return_value=True),
            patch.object(sched, "_wait", new=_make_wait(1)),
        ):
            await asyncio.wait_for(sched.run_s3_backup_scheduler(shutdown), timeout=2.0)

    asyncio.run(runner())
    mock_backup.assert_not_called()
    assert not state_path.exists()


def test_disabled_recheck_uses_short_wait(tmp_path, monkeypatch):
    """While off/unconfigured the loop re-checks on the short cadence, so
    enabling from Settings takes effect within a minute, not a full interval."""
    monkeypatch.setattr(s3_backup_shared, "DEFAULT_STATE_PATH", tmp_path / "state.json")
    cfg = {"s3_backup_enabled": False, "s3_backup_bucket": None, "s3_backup_prefix": None}
    waits: list[float] = []

    async def capture_wait(shutdown: asyncio.Event, seconds: float) -> bool:
        waits.append(seconds)
        shutdown.set()
        return True

    async def runner():
        shutdown = asyncio.Event()
        with (
            patch.object(sched, "get_config", return_value=cfg),
            patch.object(sched, "run_backup", new=MagicMock(name="run_backup")),
            patch.object(sched, "_has_aws_credentials", return_value=True),
            patch.object(sched, "_wait", new=capture_wait),
        ):
            await asyncio.wait_for(sched.run_s3_backup_scheduler(shutdown), timeout=2.0)

    asyncio.run(runner())
    assert waits == [sched._DISABLED_RECHECK_SECONDS]


def test_missing_credentials_skips_backup(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(s3_backup_shared, "DEFAULT_STATE_PATH", state_path)
    mock_backup = MagicMock(name="run_backup")

    async def runner():
        shutdown = asyncio.Event()
        with (
            patch.object(sched, "get_config", return_value=_enabled_cfg()),
            patch.object(sched, "run_backup", new=mock_backup),
            patch.object(sched, "_has_aws_credentials", return_value=False),
            patch.object(sched, "_wait", new=_make_wait(1)),
        ):
            await asyncio.wait_for(sched.run_s3_backup_scheduler(shutdown), timeout=2.0)

    asyncio.run(runner())
    mock_backup.assert_not_called()
    assert not state_path.exists()


def test_enabled_success_writes_state(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(s3_backup_shared, "DEFAULT_STATE_PATH", state_path)
    result = BackupRunResult(uploaded=3, deleted=1, skipped=2, objects_total=5)
    mock_backup = MagicMock(name="run_backup", return_value=result)

    async def runner():
        shutdown = asyncio.Event()
        with (
            patch.object(sched, "get_config", return_value=_enabled_cfg()),
            patch.object(sched, "run_backup", new=mock_backup),
            patch.object(sched, "_has_aws_credentials", return_value=True),
            patch.object(sched, "_wait", new=_make_wait(1)),
            patch("src.finance.notification_service.send_raw") as mock_notify,
        ):
            await asyncio.wait_for(sched.run_s3_backup_scheduler(shutdown), timeout=2.0)
            mock_notify.assert_not_called()

    asyncio.run(runner())

    mock_backup.assert_called_once_with("my-bucket", None)
    state = s3_backup_shared.read_state(state_path)
    assert state["uploaded_count"] == 3
    assert state["deleted_count"] == 1
    assert state["objects_total"] == 5
    assert state["consecutive_failures"] == 0
    assert state["last_error"] is None
    assert state["last_success_at"] is not None
    assert state["last_attempt_at"] == state["last_success_at"]


def test_first_failure_records_state_and_notifies_once(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(s3_backup_shared, "DEFAULT_STATE_PATH", state_path)
    long_error = "boom " * 100  # 500 chars — must be truncated to 300
    mock_backup = MagicMock(name="run_backup", side_effect=RuntimeError(long_error))

    async def runner():
        shutdown = asyncio.Event()
        with (
            patch.object(sched, "get_config", return_value=_enabled_cfg()),
            patch.object(sched, "run_backup", new=mock_backup),
            patch.object(sched, "_has_aws_credentials", return_value=True),
            patch.object(sched, "_wait", new=_make_wait(1)),
            patch("src.finance.notification_service.send_raw") as mock_notify,
        ):
            await asyncio.wait_for(sched.run_s3_backup_scheduler(shutdown), timeout=2.0)
            mock_notify.assert_called_once()
            assert mock_notify.call_args.kwargs["title"] == "S3 backup failed"
            assert "my-bucket" in mock_notify.call_args.kwargs["body"]

    asyncio.run(runner())

    state = s3_backup_shared.read_state(state_path)
    assert state["consecutive_failures"] == 1
    assert state["last_error"] is not None
    assert len(state["last_error"]) == 300
    assert state["last_success_at"] is None


def test_second_consecutive_failure_increments_without_second_notify(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(s3_backup_shared, "DEFAULT_STATE_PATH", state_path)
    mock_backup = MagicMock(name="run_backup", side_effect=RuntimeError("still broken"))

    async def runner():
        shutdown = asyncio.Event()
        with (
            patch.object(sched, "get_config", return_value=_enabled_cfg()),
            patch.object(sched, "run_backup", new=mock_backup),
            patch.object(sched, "_has_aws_credentials", return_value=True),
            patch.object(sched, "_wait", new=_make_wait(2)),  # allow two failing runs
            patch("src.finance.notification_service.send_raw") as mock_notify,
        ):
            await asyncio.wait_for(sched.run_s3_backup_scheduler(shutdown), timeout=2.0)
            mock_notify.assert_called_once()  # only the first failure notifies

    asyncio.run(runner())

    assert mock_backup.call_count == 2
    state = s3_backup_shared.read_state(state_path)
    assert state["consecutive_failures"] == 2


def test_success_after_failures_resets_counter(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(s3_backup_shared, "DEFAULT_STATE_PATH", state_path)
    result = BackupRunResult(uploaded=1, deleted=0, skipped=4, objects_total=5)
    mock_backup = MagicMock(name="run_backup", side_effect=[RuntimeError("transient"), result])

    async def runner():
        shutdown = asyncio.Event()
        with (
            patch.object(sched, "get_config", return_value=_enabled_cfg()),
            patch.object(sched, "run_backup", new=mock_backup),
            patch.object(sched, "_has_aws_credentials", return_value=True),
            patch.object(sched, "_wait", new=_make_wait(2)),  # fail, then succeed
            patch("src.finance.notification_service.send_raw") as mock_notify,
        ):
            await asyncio.wait_for(sched.run_s3_backup_scheduler(shutdown), timeout=2.0)
            mock_notify.assert_called_once()  # only the failure notified

    asyncio.run(runner())

    assert mock_backup.call_count == 2
    state = s3_backup_shared.read_state(state_path)
    assert state["consecutive_failures"] == 0
    assert state["last_error"] is None
    assert state["uploaded_count"] == 1
    assert state["objects_total"] == 5
