"""Externalized configuration loader for categories, card mappings,
and blocked companies."""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, cast

_CONFIG_DIR = Path(__file__).resolve().parent / "config"
_PERSONAL_DIR = Path(__file__).resolve().parents[2] / "data" / "config"


def _config_path(filename: str) -> Path:
    """Return personal config path if it exists, else tracked default."""
    personal = _PERSONAL_DIR / filename
    if personal.exists():
        return personal
    return _CONFIG_DIR / filename


logger = logging.getLogger(__name__)

# Environment channel for the SMS suppression list. Named after the existing
# NOTIFICATION_PROVIDER / NOTIFICATION_URL family. Deliberately NOT cached in
# `_simple_caches` — see get_blocked_companies().
_BLOCKED_COMPANIES_ENV_VAR = "NOTIFICATION_BLOCKED_COMPANIES"

_simple_caches: dict[str, object] = {}
_category_overrides_cache: dict[str, str] | None = None
_category_overrides_cache_time = 0
_OVERRIDES_TTL = 300  # 5 minutes

# Bundled overrides + aliases cache — one read every 5 minutes per warm container.
# Used by resolve_override() callers that need Tier 2 alias support.
_override_context_cache: tuple[dict[str, str], dict[str, str]] | None = None
_override_context_cache_time = 0

# Storage-backed category list cache — mirrors the overrides cache. The canonical
# category vocabulary lives in DynamoDB/SQLite (CategoryService); the bundled
# categories.json is only a seed/fallback for empty storage (fresh installs/demo).
_category_list_cache: list[str] | None = None
_category_list_cache_time = 0

# Merchant auto-ignore rules cache — same 5-minute TTL as the overrides cache.
# Consulted at transaction-write time (add_transaction) so a matching merchant
# arrives Ignored. Fail-open to an empty set (no rule fires) if storage is
# unreachable, exactly like the overrides lookup.
_ignore_rules_cache: list[str] | None = None
_ignore_rules_cache_time = 0


def _cached_json_load(filename: str, use_personal_path: bool = False) -> object:
    """Load a JSON config file, caching the result in memory after first read."""
    if filename not in _simple_caches:
        path = _config_path(filename) if use_personal_path else _CONFIG_DIR / filename
        with open(path) as f:
            _simple_caches[filename] = json.load(f)
    return _simple_caches[filename]


def get_categories() -> list[str]:
    """Return the bundled seed categories (categories.json), loading from disk on first call.

    This is the seed/fallback list only. For the user's active category vocabulary,
    use `get_category_list()`, which reads the configured storage backend first.
    """
    return cast("list[str]", _cached_json_load("categories.json"))


def get_category_list() -> list[str]:
    """Return the active category vocabulary, reading storage first, seed JSON as fallback.

    The canonical category list lives in the configured storage backend
    (DynamoDB/SQLite via CategoryService). ``CategoryService.get_categories_list()``
    already returns the bundled ``categories.json`` seed when storage is empty, so a
    fresh install (no stored categories) transparently gets the shipped defaults; the
    stored list only takes over once a user has saved customizations. Result is cached
    for 5 minutes and fails open to the seed JSON if storage is unreachable.
    """
    global _category_list_cache, _category_list_cache_time

    now = time.time()
    if _category_list_cache is not None and (now - _category_list_cache_time) < _OVERRIDES_TTL:
        return _category_list_cache

    try:
        from src.finance.storage import create_category_service

        categories = create_category_service().get_categories_list()
        if categories:
            _category_list_cache = list(categories)
            _category_list_cache_time = now
            return _category_list_cache
    except Exception:
        logger.debug("Storage category lookup failed, falling back to JSON seed", exc_info=True)

    # Fail-open: bundled JSON seed (the same source CategoryService falls back to).
    seed = cast("list[str]", _cached_json_load("categories.json"))
    _category_list_cache = list(seed)
    _category_list_cache_time = now
    return _category_list_cache


def get_card_name_mappings() -> dict[str, dict[str, str]]:
    """Return card-fragment-to-name mappings keyed by institution."""
    return cast("dict[str, dict[str, str]]", _cached_json_load("card_name_mappings.json", use_personal_path=True))


def get_tax_line_mappings() -> dict[str, Any]:
    """Return the tax line mapping seed (tax_line_mappings.json); a personal copy wins.

    Two-tier read like the other seeds: a user copy in gitignored ``data/config/``
    overrides the tracked default in ``src/finance/config/``. Validates at load
    that no category is claimed by two lines — a seed with a duplicated category
    would silently double-count a transaction, so it raises ``ValueError`` instead.
    Category comparison is case-insensitive (stored rows carry lowercase
    categories; the seed uses display case).
    """
    data = cast("dict[str, Any]", _cached_json_load("tax_line_mappings.json", use_personal_path=True))
    claimed_by: dict[str, str] = {}
    for line in data.get("lines", []):
        for category in line.get("categories", []):
            lowered = str(category).lower()
            if lowered in claimed_by and claimed_by[lowered] != line["key"]:
                raise ValueError(
                    f"tax_line_mappings.json maps category {category!r} to two lines "
                    f"({claimed_by[lowered]!r} and {line['key']!r}); each category may "
                    "belong to at most one line"
                )
            claimed_by[lowered] = line["key"]
    return data


def _parse_blocked_companies_env(raw: str) -> list[str]:
    """Parse the ``NOTIFICATION_BLOCKED_COMPANIES`` value into a list of entries.

    Two accepted forms: a JSON array of strings (when the trimmed value starts
    with ``[``) or a comma-separated list. Entries are trimmed and empties are
    dropped. A malformed value is ignored wholesale — never raised — because
    the only consumer is the fail-open notification filter and a typo in a
    Lambda env var must not stop ingestion.

    Entry text is personal (merchant names), so nothing here logs a value;
    warnings carry counts and positions only.
    """
    trimmed = raw.strip()
    if not trimmed:
        return []

    if trimmed.startswith("["):
        try:
            loaded = json.loads(trimmed)
        except ValueError:
            logger.warning(
                "%s is not valid JSON; ignoring the environment override (entries not logged)",
                _BLOCKED_COMPANIES_ENV_VAR,
            )
            return []
        if not isinstance(loaded, list):
            logger.warning(
                "%s parsed as %s, expected a JSON array; ignoring the environment override",
                _BLOCKED_COMPANIES_ENV_VAR,
                type(loaded).__name__,
            )
            return []
        for index, item in enumerate(loaded):
            if not isinstance(item, str):
                logger.warning(
                    "%s entry %d is %s, expected a string; ignoring the environment override",
                    _BLOCKED_COMPANIES_ENV_VAR,
                    index,
                    type(item).__name__,
                )
                return []
        candidates = [str(item) for item in loaded]
    else:
        candidates = trimmed.split(",")

    return [stripped for entry in candidates if (stripped := entry.strip())]


def get_blocked_companies() -> list[str]:
    """Return the list of companies whose transactions should not trigger SMS.

    Two sources, unioned: the bundled ``blocked_companies.json`` seed (cached
    after the first read, like the other seeds) and the
    ``NOTIFICATION_BLOCKED_COMPANIES`` environment variable. The env channel
    exists for AWS Lambda, whose image carries ``src/`` only — there is no
    ``data/`` directory to personalize, so without it the bundled (empty) seed
    would be the whole suppression list. Set it with
    ``docker/email_parsing/11_set_function_env.sh``.

    The env var is read on *every* call (never cached) so an env-map update
    takes effect on the next invocation rather than waiting for a cold start.
    Bundled entries come first; env entries are appended only when no existing
    entry matches case-insensitively, so ordering is stable and a value present
    in both sources is not duplicated. When the env var is absent, blank or
    malformed, the cached seed list is returned unchanged — the same object as
    before this channel existed.
    """
    bundled = cast("list[str]", _cached_json_load("blocked_companies.json"))

    raw = os.environ.get(_BLOCKED_COMPANIES_ENV_VAR)
    if not raw or not raw.strip():
        return bundled

    extra = _parse_blocked_companies_env(raw)
    if not extra:
        return bundled

    merged = list(bundled)
    seen = {entry.lower() for entry in merged}
    for entry in extra:
        lowered = entry.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        merged.append(entry)

    # Counts only — the entries themselves are personal merchant names.
    logger.debug(
        "Blocked companies: %d bundled + %d from %s -> %d total",
        len(bundled),
        len(extra),
        _BLOCKED_COMPANIES_ENV_VAR,
        len(merged),
    )
    return merged


def get_category_overrides() -> dict[str, str]:
    """Return company-to-category overrides. Tries DynamoDB first, falls back to JSON.

    Results are cached in memory for 5 minutes. If both DynamoDB and JSON fail,
    returns an empty dict (fail-open — categorization falls through to OpenAI).
    """
    global _category_overrides_cache, _category_overrides_cache_time

    now = time.time()
    if _category_overrides_cache is not None and (now - _category_overrides_cache_time) < _OVERRIDES_TTL:
        return _category_overrides_cache

    # Try DynamoDB first — use the storage factory so user_id is pulled from
    # data/config.json rather than defaulting to "default".
    try:
        from src.finance.storage import create_override_service

        svc = create_override_service()
        item = svc.get_overrides()
        if item is not None:
            _category_overrides_cache = dict(item.get("Data", {}))
            _category_overrides_cache_time = now
            return _category_overrides_cache
    except Exception:
        logger.debug("DynamoDB override lookup failed, falling back to JSON", exc_info=True)

    # Fall back to JSON file (checks data/config/ first, then src/finance/config/)
    try:
        with open(_config_path("category_overrides.json")) as f:
            loaded = cast("dict[str, str]", json.load(f))
            _category_overrides_cache = loaded
            _category_overrides_cache_time = now
            return loaded
    except Exception:
        logger.warning("Failed to load category overrides from JSON", exc_info=True)

    # Fail-open: return empty dict so categorization falls through to OpenAI
    return {}


def invalidate_category_overrides_cache() -> None:
    """Clear the in-memory overrides cache so the next call re-reads from source."""
    global _category_overrides_cache, _category_overrides_cache_time
    _category_overrides_cache = None
    _category_overrides_cache_time = 0
    # Aliases are bundled with overrides in get_override_context — same invalidation.
    invalidate_override_context_cache()


def get_override_context() -> tuple[dict[str, str], dict[str, str]]:
    """Return (overrides, aliases) with a bundled 5-minute cache.

    Lambda cold start pays one extra DynamoDB get_item every 5 minutes of warm
    life vs. reading overrides alone. Fail-open on the alias side: if DynamoDB
    is unreachable, aliases default to `{}` and only Tier 0/1 run.

    Callers pass the tuple directly to `resolve_override(company, overrides, aliases=aliases)`.
    """
    global _override_context_cache, _override_context_cache_time

    now = time.time()
    if _override_context_cache is not None and (now - _override_context_cache_time) < _OVERRIDES_TTL:
        return _override_context_cache

    overrides = get_category_overrides()

    try:
        from src.finance.storage import create_merchant_alias_service

        svc = create_merchant_alias_service()
        aliases = svc.get_aliases_map()
    except Exception:
        logger.debug("DynamoDB alias lookup failed, using empty alias map", exc_info=True)
        aliases = {}

    _override_context_cache = (overrides, aliases)
    _override_context_cache_time = now
    return _override_context_cache


def invalidate_override_context_cache() -> None:
    """Clear the bundled overrides+aliases cache. Called from override and alias CRUD endpoints."""
    global _override_context_cache, _override_context_cache_time
    _override_context_cache = None
    _override_context_cache_time = 0


def get_ignore_rules() -> list[str]:
    """Return the merchant auto-ignore patterns. Tries storage first, falls back to JSON.

    Cached in memory for 5 minutes. Fails open to an empty list (no rule fires)
    if both storage and the JSON backup are unavailable — mirrors
    ``get_category_overrides``.
    """
    global _ignore_rules_cache, _ignore_rules_cache_time

    now = time.time()
    if _ignore_rules_cache is not None and (now - _ignore_rules_cache_time) < _OVERRIDES_TTL:
        return _ignore_rules_cache

    try:
        from src.finance.storage import create_ignore_rule_service

        patterns = create_ignore_rule_service().get_patterns()
        _ignore_rules_cache = list(patterns)
        _ignore_rules_cache_time = now
        return _ignore_rules_cache
    except Exception:
        logger.debug("Storage ignore-rules lookup failed, falling back to JSON", exc_info=True)

    # Fall back to JSON backup (a list of patterns), checking data/config/ first.
    try:
        with open(_config_path("ignore_rules.json")) as f:
            loaded = json.load(f)
            if isinstance(loaded, list):
                _ignore_rules_cache = [str(p) for p in loaded]
                _ignore_rules_cache_time = now
                return _ignore_rules_cache
    except Exception:
        logger.debug("Failed to load ignore rules from JSON", exc_info=True)

    _ignore_rules_cache = []
    _ignore_rules_cache_time = now
    return _ignore_rules_cache


def get_ignore_context() -> tuple[list[str], dict[str, str]]:
    """Return (ignore_patterns, aliases) for tiered ignore-rule matching.

    Aliases are shared with the override resolver (same merchant alias map), so
    this reuses the bundled ``get_override_context`` alias half — ignore rules
    match the same way category rules do, alias tier included.
    """
    patterns = get_ignore_rules()
    _, aliases = get_override_context()
    return patterns, aliases


def invalidate_ignore_rules_cache() -> None:
    """Clear the in-memory ignore-rules cache. Called from ignore-rule CRUD endpoints."""
    global _ignore_rules_cache, _ignore_rules_cache_time
    _ignore_rules_cache = None
    _ignore_rules_cache_time = 0


def invalidate_categories_cache() -> None:
    """Clear the in-memory category caches so the next call re-reads from source.

    Clears both the seed-JSON cache and the storage-backed `get_category_list()`
    cache, so category CRUD endpoints (which already call this) invalidate both.
    """
    global _category_list_cache, _category_list_cache_time
    _simple_caches.pop("categories.json", None)
    _category_list_cache = None
    _category_list_cache_time = 0
