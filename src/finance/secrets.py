"""Secret loader with a tiered fallback chain.

Resolves secrets from, in order:
    1. AWS SSM Parameter Store (production Lambda)
    2. Process environment variable (CI, manual override)
    3. ``.env`` file (local dev)

The loader is cached with :func:`functools.lru_cache` so the SSM call
happens at most once per Lambda container lifetime. Tests must call
``get_openai_api_key.cache_clear()`` between cases.

This module exists because the 2026-04-08 incident showed that storing
the OpenAI key in Lambda env vars is fragile — any
``update-function-configuration --environment`` call can silently clobber
the secret. SSM Parameter Store is audited, KMS-encrypted, and rotatable
without touching Lambda configuration.
"""

import logging
import os
from functools import lru_cache
from pathlib import Path

from src.finance.aws_region import get_aws_region

logger = logging.getLogger(__name__)

_SSM_PARAMETER_NAME = "/email-parser/openai-api-key"

# Written by POST /config/test-openai; monkeypatched by the test suite so unit
# tests can never touch the developer's real key file.
DATA_ENV_PATH = Path("data/.env")


@lru_cache(maxsize=1)
def get_openai_api_key() -> str:
    """Return the OpenAI API key from the first available source.

    Raises:
        RuntimeError: if the key is not found in SSM, environment, or ``.env``.
    """
    # Tier 1 — AWS SSM Parameter Store. The import is split from the SSM call so
    # a missing boto3 hits `except ImportError` cleanly: folding both into one
    # try makes the `except (ClientError, ...)` tuple reference names that the
    # failed import never bound, which would raise UnboundLocalError instead of
    # falling through.
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
    except ImportError as e:
        logger.debug("boto3 not installed, falling through: %s", e)
    else:
        try:
            ssm = boto3.client("ssm", region_name=get_aws_region())
            resp = ssm.get_parameter(Name=_SSM_PARAMETER_NAME, WithDecryption=True)
            logger.info("Loaded OpenAI key from SSM Parameter Store")
            return resp["Parameter"]["Value"]
        except (ClientError, BotoCoreError, NoCredentialsError) as e:
            logger.debug("SSM unavailable, falling through: %s", e)

    # Tier 2 — Process environment
    if key := os.environ.get("OPENAI_API_KEY"):
        logger.info("Loaded OpenAI key from environment variable")
        return key

    # Tier 3 — data/.env (user-provided via Settings UI)
    if DATA_ENV_PATH.is_file():
        try:
            from dotenv import dotenv_values

            vals = dotenv_values(DATA_ENV_PATH)
            if key := vals.get("OPENAI_API_KEY"):
                logger.info("Loaded OpenAI key from data/.env")
                return key
        except ImportError:
            pass

    # Tier 4 — project root .env file (local dev only)
    try:
        from dotenv import load_dotenv

        load_dotenv()
        if key := os.environ.get("OPENAI_API_KEY"):
            logger.info("Loaded OpenAI key from .env file")
            return key
    except ImportError:
        pass

    raise RuntimeError("OPENAI_API_KEY not found in SSM Parameter Store, environment, or .env")
