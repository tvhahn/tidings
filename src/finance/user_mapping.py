"""User mapping utilities — load and query ForwardedTo → UserId cache.

Mapping source precedence, highest first:

1. the ``USER_MAPPINGS`` environment variable (comma-separated
   ``forwarded_to=user_id`` pairs),
2. ``data/config/user_mappings.csv`` (personal, gitignored),
3. ``src/finance/user_mappings.csv`` (the tracked demo default).

The environment channel exists for AWS Lambda: the image ships ``src/`` and the
handlers only — there is no ``data/`` directory to personalize — so without it
the bundled demo addresses are the whole mapping, and every read path derived
from them queries partitions that hold nothing. Set it with
``docker/email_parsing/11_set_function_env.sh``.
"""

import csv
import logging
import os
from pathlib import Path

user_id_cache: dict[str, str] = {}

__all__ = [
    "LOCAL_FORWARDED_TO_SUFFIX",
    "get_forwarded_to_addresses",
    "get_user_id",
    "load_user_mappings",
    "local_forwarded_to",
    "user_id_cache",
]

logger = logging.getLogger(__name__)

_MAPPINGS_ENV_VAR = "USER_MAPPINGS"

_DEFAULT_MAPPINGS = Path(__file__).resolve().parent / "user_mappings.csv"
_PERSONAL_MAPPINGS = Path(__file__).resolve().parents[2] / "data" / "config" / "user_mappings.csv"

# Locally-originated rows (manual adds, plain-CSV imports) carry no forwarding
# address, so they live in a synthetic `{user_id}@local` partition instead of
# an email one. Writers derive it via `local_forwarded_to()`; readers pick it
# up through `get_forwarded_to_addresses()`.
LOCAL_FORWARDED_TO_SUFFIX = "@local"


def _parse_env_mappings(raw: str) -> dict[str, str]:
    """Parse ``USER_MAPPINGS`` into a ``{forwarded_to: user_id}`` dict.

    Format: comma-separated ``forwarded_to=user_id`` pairs, whitespace trimmed,
    blank pairs dropped. A pair with no ``=`` or an empty side is skipped with a
    warning; the split is on the first ``=`` (email addresses contain none).
    Never raises — a typo in a Lambda env var must not stop ingestion.

    Forwarding addresses are personal, so warnings name the pair's position
    only, never its text.
    """
    mappings: dict[str, str] = {}
    for index, chunk in enumerate(raw.split(","), start=1):
        pair = chunk.strip()
        if not pair:
            continue
        forwarded_to, separator, user_id = pair.partition("=")
        forwarded_to = forwarded_to.strip()
        user_id = user_id.strip()
        if not separator or not forwarded_to or not user_id:
            logger.warning(
                "%s pair %d is not a 'forwarded_to=user_id' pair; skipping it (value not logged)",
                _MAPPINGS_ENV_VAR,
                index,
            )
            continue
        mappings[forwarded_to] = user_id
    return mappings


def load_user_mappings() -> None:
    """Load user mappings into ``user_id_cache``.

    Source precedence: the ``USER_MAPPINGS`` environment variable, then
    data/config/user_mappings.csv (personal, gitignored), then
    src/finance/user_mappings.csv (tracked safe default). A set-but-unusable
    env var (no valid pairs) warns and falls back to the CSV behaviour rather
    than leaving the cache empty.

    Mutates ``user_id_cache`` in place — rebinding would desynchronize any
    module that imported the reference via ``from … import user_id_cache``.
    """
    raw_env = os.environ.get(_MAPPINGS_ENV_VAR) or ""
    if raw_env.strip():
        env_mappings = _parse_env_mappings(raw_env)
        if env_mappings:
            user_id_cache.clear()
            user_id_cache.update(env_mappings)
            # Counts only — the addresses themselves are personal.
            logger.info("User mappings loaded from %s (%d entries).", _MAPPINGS_ENV_VAR, len(env_mappings))
            return
        logger.warning(
            "%s is set but contained no valid pairs; falling back to the mappings CSV.",
            _MAPPINGS_ENV_VAR,
        )

    csv_file_path = _PERSONAL_MAPPINGS if _PERSONAL_MAPPINGS.exists() else _DEFAULT_MAPPINGS

    try:
        with open(csv_file_path) as infile:
            reader = csv.DictReader(infile)
            user_id_cache.clear()
            user_id_cache.update({row["ForwardedTo"]: row["UserId"] for row in reader})
        logger.info("User mappings loaded successfully.")
    except FileNotFoundError:
        logger.exception("CSV file %s not found.", csv_file_path)
    except Exception:
        logger.exception("Error loading user mappings from CSV")


def get_user_id(forwarded_to: str) -> str | None:
    """Retrieve UserId from the in-memory cache."""
    return user_id_cache.get(forwarded_to)


def _resolve_user_id() -> str:
    """Resolve this install's user id: ``USER_ID`` env, then config, then "default".

    TWIN: ``src.finance.storage._get_user_id`` resolves the same three steps in
    the same order and the two must stay in sync — a disagreement puts writes
    and reads in different DynamoDB partitions (which is exactly how the Lambda
    monthly summary ended up querying ``default@local``). The logic is
    replicated rather than imported for two reasons: ``src.finance.storage``
    sits *above* this module in the import graph (storage → spending_summary →
    user_mapping, currently only lazily), and storage binds ``get_config`` at
    module import while this module resolves it per call, so delegating would
    silently change which ``get_config`` patch callers see.
    ``tests/unit/test_user_mapping.py`` asserts the two agree.
    """
    env_user_id = os.environ.get("USER_ID")
    if env_user_id:
        return env_user_id

    from src.finance.app_config import get_config

    return get_config().get("user_id", "default")


def local_forwarded_to() -> str:
    """Return the synthetic ForwardedTo partition for locally-entered rows.

    Manual adds and plain-CSV imports have no forwarding address; both key off
    this value so they dedup against each other. Kept here as the single
    derivation so writers and readers cannot drift apart.

    The user id comes from ``_resolve_user_id()`` — the ``USER_ID`` env var
    first, exactly like the storage layer. Self-hosted installs leave that
    variable unset, so they keep resolving through ``data/config.json``
    unchanged; in Lambda (no config file, ``USER_ID`` set) this is what stops
    the partition collapsing to ``default@local``.
    """
    return f"{_resolve_user_id()}{LOCAL_FORWARDED_TO_SUFFIX}"


def get_forwarded_to_addresses() -> list[str]:
    """Return every ForwardedTo partition belonging to this user.

    The mapped email partitions from the active mapping source (the
    ``USER_MAPPINGS`` env var, else a mappings CSV), plus the synthetic
    `{user_id}@local` partition holding manually-added and CSV-imported rows.
    The local partition is appended last so callers that treat the first entry
    as the primary write target (e.g. statement ingestion) keep their mapped
    address. Without it, locally-entered transactions are written to a
    partition no read path enumerates and never surface in the UI.
    """
    if not user_id_cache:
        load_user_mappings()
    addresses = list(user_id_cache.keys())
    local = local_forwarded_to()
    if local not in user_id_cache:
        addresses.append(local)
    return addresses
