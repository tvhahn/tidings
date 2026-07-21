"""App configuration endpoints: read and update runtime config."""

import logging
import os
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api import dependencies
from src.api.errors import ApiException
from src.api.models.config import (
    AppConfigResponse,
    AppConfigUpdateRequest,
    TestOpenAIResponse,
    TestS3BackupResponse,
)
from src.finance.app_config import AppConfig, get_config, get_config_with_features, update_config
from src.finance.s3_backup_verify import verify_backup_target

logger = logging.getLogger(__name__)

router = APIRouter(tags=["config"])

# Config keys where an explicit `null` from the client is meaningful (clears a
# model / effort override back to the provider default) rather than "field
# omitted". Every other field keeps the ignore-null behavior, so a client can
# safely send its whole config object without wiping unset scalars.
NULLABLE_CONFIG_KEYS = {
    "daily_summary_model",
    "daily_summary_reasoning_effort",
    "insights_model",
    "insights_reasoning_effort",
    "insights_user_memo",
    "categorization_model",
    "categorization_reasoning_effort",
    "document_parsing_model",
    "document_parsing_reasoning_effort",
    "s3_backup_bucket",
    "s3_backup_prefix",
}


@router.get(
    "/config",
    response_model=AppConfigResponse,
    operation_id="getAppConfig",
    summary="Get runtime app configuration (storage, demo mode, user_id, features)",
)
async def get_config_endpoint():
    return get_config_with_features()


@router.put(
    "/config",
    response_model=AppConfigResponse,
    operation_id="putAppConfig",
    summary="Update runtime app configuration",
)
async def put_config(body: AppConfigUpdateRequest):
    old_cfg = get_config()
    was_demo = old_cfg.get("demo_mode", False)
    old_user_id = old_cfg.get("user_id", "default")

    # `exclude_unset` keeps only fields the client actually sent, then we drop
    # None values EXCEPT for the nullable override keys — so an explicit null on
    # a `*_model` / `*_reasoning_effort` key clears it, while a null on any other
    # field is ignored (preserving the old whole-object-safe PUT behavior).
    sent = body.model_dump(exclude_unset=True)
    updates = cast(
        "AppConfig",
        {k: v for k, v in sent.items() if v is not None or k in NULLABLE_CONFIG_KEYS},
    )

    if "timezone" in updates:
        try:
            ZoneInfo(updates["timezone"])
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown IANA timezone: {updates['timezone']!r}",
            ) from e

    try:
        update_config(updates)
    except OSError as e:
        raise ApiException(500, "CONFIG_WRITE_FAILED", "could not write data/config.json") from e

    # Reinitialize services when demo_mode or user_id changes so singleton
    # service instances pick up the new DynamoDB partition key / database path.
    now_demo = updates.get("demo_mode")
    now_user_id = updates.get("user_id")
    demo_changed = now_demo is not None and now_demo != was_demo
    user_id_changed = now_user_id is not None and now_user_id != old_user_id

    if demo_changed or user_id_changed:
        if demo_changed and now_demo:
            from src.finance.demo_loader import ensure_demo_loaded

            ensure_demo_loaded()

        from src.api.dependencies import reinitialize_services

        reinitialize_services()

    return get_config_with_features()


class TestOpenAIRequest(BaseModel):
    api_key: str


class TestS3BackupRequest(BaseModel):
    bucket: str
    prefix: str | None = None


def _validate_openai_key(api_key: str) -> str | None:
    """Validate an OpenAI API key via a ``models.list()`` round trip.

    Returns ``None`` on success or a truncated error string on failure.
    Blocking (network I/O) — call via ``run_sync`` from the async handler.
    """
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        client.models.list()
    except Exception as e:
        return str(e)[:200]
    return None


def _persist_openai_key(api_key: str) -> None:
    """Write ``OPENAI_API_KEY`` to data/.env (0600), replacing any existing line.

    Blocking (file I/O) — call via ``run_sync`` from the async handler.
    """
    from src.finance.secrets import DATA_ENV_PATH

    data_env = DATA_ENV_PATH
    data_env.parent.mkdir(parents=True, exist_ok=True)

    # Read existing lines, replace or append OPENAI_API_KEY
    lines: list[str] = []
    if data_env.is_file():
        lines = data_env.read_text().splitlines()
    found = False
    for i, line in enumerate(lines):
        if line.startswith("OPENAI_API_KEY="):
            lines[i] = f"OPENAI_API_KEY={api_key}"
            found = True
            break
    if not found:
        lines.append(f"OPENAI_API_KEY={api_key}")
    # 0600: the file holds a live API key — same posture as data/chatgpt_oauth.json.
    fd = os.open(data_env, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")


@router.post(
    "/config/test-openai",
    response_model=TestOpenAIResponse,
    operation_id="testOpenAIKey",
    summary="Validate an OpenAI API key and persist it to data/.env on success",
)
async def test_openai_connection(body: TestOpenAIRequest):
    """Validate an OpenAI API key and persist it to data/.env on success."""
    error = await dependencies.run_sync(_validate_openai_key, body.api_key)
    if error:
        return TestOpenAIResponse(ok=False, error=error)

    await dependencies.run_sync(_persist_openai_key, body.api_key)

    # Clear cached secret so next usage picks up the new key
    from src.finance.secrets import get_openai_api_key

    get_openai_api_key.cache_clear()

    logger.info("OpenAI API key validated and saved to data/.env")
    return TestOpenAIResponse(ok=True, error=None)


@router.post(
    "/config/test-s3-backup",
    response_model=TestS3BackupResponse,
    operation_id="testS3Backup",
    summary="Verify an S3 bucket is a usable attachment-backup target",
)
async def test_s3_backup(body: TestS3BackupRequest):
    """Run stateless bucket checks. Persists nothing — the client saves via PUT /config."""
    bucket = body.bucket.strip()
    if not bucket:
        return TestS3BackupResponse(ok=False, error="Bucket name is required.", warnings=[])

    result = await dependencies.run_sync(verify_backup_target, bucket, body.prefix)
    return TestS3BackupResponse(ok=result.ok, error=result.error, warnings=result.warnings)
