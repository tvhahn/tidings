"""Background scheduler for the opt-in hourly S3 attachment/statement mirror.

Runs as a single ``asyncio.Task`` spawned from the FastAPI lifespan (self-hosted,
non-demo only). Re-reads ``data/config.json`` on each iteration so enabling or
disabling the backup, or changing the bucket, takes effect without a restart,
and short-circuits when the feature is off, no bucket is set, or AWS credentials
are absent. On each eligible firing it runs the mirror engine in a worker thread
and records the outcome to the shared state file — the scheduler is the sole
writer of that file.

The first eligible run happens immediately on startup (no initial sleep);
thereafter it waits an hour between successes and backs off after failures. A
single calm notification fires on the first failure of a streak, never on the
repeats. State timestamps are ISO-8601 UTC (operational metadata, not financial
data, so the app timezone rules do not apply).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from src.finance import notification_service, s3_backup_shared
from src.finance.app_config import _has_aws_credentials, get_config
from src.finance.s3_backup import BackupRunResult, run_backup

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 3600  # 1 hour between successful mirrors
_FAILURE_BACKOFF_SECONDS = 300  # 5 min — avoid hot-looping on persistent failure
_DISABLED_RECHECK_SECONDS = 60  # while off/unconfigured — enabling takes effect within a minute
# Floor on each wait so a shrunk interval (tests) or clock skew can't spin the
# loop hot. Named (not an inline literal) so scheduler tests can shrink it.
_MIN_WAIT_SECONDS = 1.0

_ERROR_MAX_CHARS = 300


async def _wait(shutdown: asyncio.Event, seconds: float) -> bool:
    """Wait up to ``seconds`` (floored at ``_MIN_WAIT_SECONDS``) for shutdown.

    Returns True if the shutdown event fired (loop should exit), False on the
    normal timeout wake.
    """
    try:
        await asyncio.wait_for(shutdown.wait(), timeout=max(_MIN_WAIT_SECONDS, seconds))
        return True
    except TimeoutError:
        return False


def _record_success(attempt_at: str, result: BackupRunResult) -> None:
    """Persist a clean-slate success state (counts from the run, failures reset)."""
    state = s3_backup_shared.default_state()
    state.update(
        last_attempt_at=attempt_at,
        last_success_at=attempt_at,
        last_error=None,
        consecutive_failures=0,
        uploaded_count=result.uploaded,
        deleted_count=result.deleted,
        objects_total=result.objects_total,
    )
    s3_backup_shared.write_state(state)


def _record_failure(bucket: str, attempt_at: str, err: Exception) -> None:
    """Bump the failure counter, record the error, and notify on the first miss.

    Preserves ``last_success_at`` and prior counts (read from existing state);
    only the attempt timestamp, error, and streak counter change. The
    notification fires exactly once per failure streak (when the counter first
    reaches 1).
    """
    state = s3_backup_shared.read_state()
    failures = int(state.get("consecutive_failures") or 0) + 1
    state["last_attempt_at"] = attempt_at
    state["last_error"] = str(err)[:_ERROR_MAX_CHARS]
    state["consecutive_failures"] = failures
    s3_backup_shared.write_state(state)
    if failures == 1:
        notification_service.send_raw(
            title="S3 backup failed",
            body=f"Backing up receipts and statements to {bucket} failed: {err}. Tidings will retry.",
        )


async def run_s3_backup_scheduler(shutdown: asyncio.Event) -> None:
    """Long-lived loop: mirror on each eligible firing, sleep between runs.

    Cancellation-safe: ``asyncio.wait_for`` on the shutdown event raises
    CancelledError on task cancellation, which propagates out cleanly.
    """
    logger.info("S3 backup scheduler started")
    while not shutdown.is_set():
        try:
            cfg = get_config()
            bucket = cfg.get("s3_backup_bucket")
            prefix = cfg.get("s3_backup_prefix")
            eligible = bool(cfg.get("s3_backup_enabled")) and bool(bucket) and _has_aws_credentials()
            if not eligible or not bucket:
                # Not configured / no creds — re-check soon (not a full interval)
                # so enabling from Settings takes effect within a minute, no
                # state write.
                if await _wait(shutdown, _DISABLED_RECHECK_SECONDS):
                    return
                continue

            attempt_at = datetime.now(UTC).isoformat()
            try:
                result = await asyncio.to_thread(run_backup, bucket, prefix)
            except asyncio.CancelledError:
                raise
            except Exception as err:
                logger.exception("S3 backup run failed; backing off")
                _record_failure(bucket, attempt_at, err)
                if await _wait(shutdown, _FAILURE_BACKOFF_SECONDS):
                    return
                continue

            logger.info(
                "S3 backup run complete: uploaded=%d deleted=%d skipped=%d",
                result.uploaded,
                result.deleted,
                result.skipped,
            )
            _record_success(attempt_at, result)
            if await _wait(shutdown, _INTERVAL_SECONDS):
                return
        except asyncio.CancelledError:
            raise
    logger.info("S3 backup scheduler stopped")
