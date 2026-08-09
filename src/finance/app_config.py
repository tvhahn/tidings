"""Runtime application configuration with file persistence and auto-detection."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import secrets
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.finance.agent_tokens import AgentTokenRecord

_GEMINI_AUTH_PATH = Path.home() / ".gemini" / "oauth_creds.json"

logger = logging.getLogger(__name__)

# The AI statement parser resolves its provider by probing these two internal
# availability predicates (also patched by name in the config test suite). They
# stay underscore-prefixed because they're not part of app_config's general
# interface — listing them here just marks the cross-module use as intentional.
__all__ = ["_has_aws_credentials", "_has_gemini_cli", "_has_openai_key"]


class AppConfig(TypedDict, total=False):
    """Core application configuration keys (all optional since configs may be partial)."""

    storage: str
    demo_mode: bool
    user_id: str
    # Per-feature AI routing. Each `*_provider` is one of
    # "openai" | "claude_cli" | "codex" | "gemini_cli" | "disabled"
    # (categorization is narrower: "openai" | "codex" | "disabled"). Each
    # `*_model` is an optional model override (None = the provider's default);
    # each `*_reasoning_effort` is an optional
    # "none" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max" override
    # (None = the provider's default; no flag/param emitted). Gemini ignores both.
    daily_summary_provider: str
    daily_summary_model: str | None
    daily_summary_reasoning_effort: str | None
    insights_provider: str
    insights_model: str | None
    insights_reasoning_effort: str | None
    insights_user_memo: str | None  # standing free-text context for every AI briefing
    categorization_provider: str
    categorization_model: str | None
    categorization_reasoning_effort: str | None
    document_parsing_provider: str  # drives both statement and receipt parsing
    document_parsing_model: str | None
    document_parsing_reasoning_effort: str | None
    enable_daily_summaries: bool
    daily_summary_schedule_time: str  # "HH:MM" 24h, evaluated in `timezone`
    ai_categorization_enabled: bool
    ai_extraction_enabled: bool  # consent to send unparseable email bodies to AI for rescue
    ai_statement_parsing_enabled: bool  # consent to send unparseable statement PDFs' text to AI
    ai_receipt_parsing_enabled: bool  # consent to send a receipt photo/PDF to AI, only when asked
    tax_tracking_enabled: bool  # gates the Tax receipts workspace, nav tab, and per-row tax flags
    # Opt-in mirror of receipt attachments + statement PDFs to a user-owned S3
    # bucket. Only offered when AWS credentials are present; the sync engine and
    # scheduler live in a sibling module.
    s3_backup_enabled: bool
    s3_backup_bucket: str | None
    s3_backup_prefix: str | None
    timezone: str  # IANA zone name; see src/finance/app_timezone.py
    agent_tokens: list[AgentTokenRecord]
    # Phase 4 — webapp auth (cookie session). Absence of `app_password_hash`
    # puts the middleware into TOFU mode (allows everything; SetupBanner warns).
    app_password_hash: str | None
    session_version: int  # bumped to invalidate every existing cookie
    session_signing_secret: str  # 256-bit hex; auto-generated on first read
    auth_bypass_for_dev: bool  # dev-only: skip cookie auth even when password is set
    # Operator opt-in to stay passwordless: hides the dashboard's "No password
    # set" banner while in TOFU mode. Auth behavior is unchanged — TOFU already
    # allows everything; this only silences the reminder.
    passwordless_acknowledged: bool


class AppConfigWithFeatures(AppConfig, total=False):
    """AppConfig extended with runtime feature-detection flags."""

    openai_enabled: bool
    aws_available: bool
    claude_cli_available: bool
    codex_available: bool
    gemini_cli_available: bool
    chatgpt_oauth_connected: bool
    chatgpt_oauth_email: str | None


_CONFIG_PATH = Path("data/config.json")

# The legacy single-provider key, replaced by the per-feature `*_provider` keys.
# Referenced only by the load-time migration below; every read site now routes
# on the per-feature keys.
_LEGACY_PROVIDER_KEY = "summary_provider"

_DEFAULTS = {
    "storage": "sqlite",
    "demo_mode": False,
    "user_id": "default",
    # Per-feature AI routing. `categorization_provider` is intentionally absent:
    # like `ai_categorization_enabled`, it has a computed default (see
    # `_default_categorization_provider`). Model/effort overrides default to None.
    "daily_summary_provider": "disabled",
    "daily_summary_model": None,
    "daily_summary_reasoning_effort": None,
    "insights_provider": "disabled",
    "insights_model": None,
    "insights_reasoning_effort": None,
    "insights_user_memo": None,
    "categorization_model": None,
    "categorization_reasoning_effort": None,
    "document_parsing_provider": "disabled",
    "document_parsing_model": None,
    "document_parsing_reasoning_effort": None,
    "enable_daily_summaries": True,
    "daily_summary_schedule_time": "19:00",
    "timezone": "America/Los_Angeles",
    # Statement text is the most sensitive document the app touches, so unlike
    # the email consents this never auto-enables from key detection.
    "ai_statement_parsing_enabled": False,
    # A receipt photo is just as sensitive; it is only ever sent when the user
    # explicitly taps "Parse receipt", and never auto-enables from key detection.
    "ai_receipt_parsing_enabled": False,
    # Tax receipt tracking is on by default so existing tax flags stay visible on
    # upgrade (the key is absent from pre-flag configs and merges to this default).
    # Turning it off hides the Tax receipts tab, workspace, and per-row tax flags.
    "tax_tracking_enabled": True,
    # S3 attachment backup is off by default; bucket/prefix are unset until the
    # user configures a target.
    "s3_backup_enabled": False,
    "s3_backup_bucket": None,
    "s3_backup_prefix": None,
}

_cache: AppConfig | None = None


def _has_aws_credentials() -> bool:
    """Check if AWS credentials are available (env vars or boto3 credential chain)."""
    # Fast path: explicit env vars
    if os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_PROFILE") or os.environ.get("AWS_ROLE_ARN"):
        return True
    # Fallback: try boto3's credential chain (~/.aws/credentials, IAM role, etc.)
    try:
        import boto3

        session = boto3.Session()
        credentials = session.get_credentials()
        return credentials is not None
    except Exception:
        return False


def _has_openai_key() -> bool:
    """Check if OpenAI API key is available."""
    return bool(os.environ.get("OPENAI_API_KEY"))


def _default_ai_extraction_enabled(persisted: Mapping[str, Any]) -> bool:
    """Derive the extraction consent when ``ai_extraction_enabled`` is absent.

    Single source of truth for the absent-key default, shared by first-run
    auto-detection and the persisted-file merge so the two can never drift.

    Before this key existed (base commit d85edb3), the extraction gate was
    keyed on ``ai_categorization_enabled``. So an upgrading user who had
    persisted a categorization *opt-out* must keep extraction off — deriving
    the extraction default purely from ``_has_openai_key()`` would silently
    re-enable sending email bodies to the AI for anyone with a key in env.
    We therefore preserve the prior consent: when the categorization key was
    persisted, inherit it; only when *neither* AI key was persisted (a truly
    pre-flag config) do we fall back to key presence.
    """
    if "ai_categorization_enabled" in persisted:
        return bool(persisted["ai_categorization_enabled"])
    return _has_openai_key()


def _default_categorization_provider() -> str:
    """Categorization defaults to the OpenAI API path when a key is present.

    Mirrors the ``ai_categorization_enabled`` computed default so the two can't
    drift. Codex is never auto-selected — it requires an explicit opt-in plus a
    ChatGPT login.
    """
    return "openai" if _has_openai_key() else "disabled"


def _migrate_summary_provider(data: dict[str, Any]) -> bool:
    """Migrate the legacy single ``summary_provider`` to per-feature keys.

    Seeds ``daily_summary_provider`` / ``insights_provider`` /
    ``document_parsing_provider`` from the legacy value, and
    ``categorization_provider`` to ``"codex"`` when the legacy value was codex
    else the computed OpenAI-or-disabled default (categorization never spoke the
    CLI providers, so claude_cli / gemini_cli can't carry over). Only seeds keys
    that are absent, so a config already carrying the new keys is left untouched.
    Deletes the legacy key. Returns True when ``data`` was modified (so the
    caller persists the migrated file).
    """
    if _LEGACY_PROVIDER_KEY not in data:
        return False
    legacy = data.get(_LEGACY_PROVIDER_KEY)
    data.setdefault("daily_summary_provider", legacy)
    data.setdefault("insights_provider", legacy)
    data.setdefault("document_parsing_provider", legacy)
    data.setdefault(
        "categorization_provider",
        "codex" if legacy == "codex" else _default_categorization_provider(),
    )
    del data[_LEGACY_PROVIDER_KEY]
    return True


def _has_codex_cli() -> bool:
    """Check if OpenAI Codex is installed *and* signed in (auth.json present)."""
    from src.finance import chatgpt_oauth

    return bool(shutil.which("codex")) and chatgpt_oauth.auth_json_path().exists()


def _has_gemini_cli() -> bool:
    """Check if Google Gemini CLI is installed *and* authenticated (OAuth creds or API key)."""
    if not shutil.which("gemini"):
        return False
    return _GEMINI_AUTH_PATH.exists() or bool(os.environ.get("GEMINI_API_KEY"))


def _has_chatgpt_oauth() -> bool:
    """Check if the Codex CLI holds a ChatGPT login (device-auth tokens)."""
    try:
        from src.finance import chatgpt_oauth

        return chatgpt_oauth.is_connected()
    except Exception:
        logger.exception("Failed to read Codex auth state")
        return False


def _get_chatgpt_oauth_email() -> str | None:
    """Lazily decode the Codex auth id_token to surface the connected email."""
    try:
        from src.finance import chatgpt_oauth

        return chatgpt_oauth.get_account_email()
    except Exception:
        logger.exception("Failed to read ChatGPT OAuth email")
        return None


def _auto_detect_defaults() -> AppConfig:
    """Determine sensible defaults for a first run.

    Self-hosters default to SQLite + demo mode. DynamoDB is an explicit
    opt-in (set `storage: "dynamodb"` in data/config.json): the old behavior
    of auto-upgrading whenever boto3 could find ANY credential (env vars,
    ~/.aws/credentials, an IAM role) silently pointed self-hosters with
    unrelated AWS credentials at a cloud table — contradicting the
    "zero AWS required" first-run promise. The persisted file wins on
    every subsequent boot, so existing deployments are unaffected.

    Exception — the AWS Lambda pipeline: it ships no `data/config.json` and
    runs on a read-only filesystem, so it can never persist an opt-in and
    would re-run this first-run path on every cold start. It is unambiguously
    DynamoDB-backed, so key off the reserved `AWS_LAMBDA_FUNCTION_NAME` env var
    (always set by the Lambda runtime) to force DynamoDB and disable demo mode.
    Without this, `create_category_service()` selects the empty local SQLite
    backend and categorization silently falls back to the bundled seed
    category list instead of the user's stored custom vocabulary.
    """
    config = cast("AppConfig", dict(_DEFAULTS))
    config["storage"] = "sqlite"
    config["demo_mode"] = True
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        # Running in the Lambda pipeline: always DynamoDB, never demo.
        config["storage"] = "dynamodb"
        config["demo_mode"] = False
    elif _has_aws_credentials():
        logger.info(
            "AWS credentials detected but not used: first-run storage defaults to sqlite. "
            'Set storage="dynamodb" in data/config.json to opt in.'
        )
    # AI categorization defaults on only when an OpenAI key is configured.
    # Once the user explicitly flips it, the persisted config wins.
    config["ai_categorization_enabled"] = _has_openai_key()
    # The categorization provider mirrors that key: the OpenAI API path when a
    # key is present, else disabled. Codex is never auto-selected.
    config["categorization_provider"] = _default_categorization_provider()
    # AI extraction (rescuing unparseable emails) is a separate consent. On a
    # fresh install there is no persisted categorization choice, so the shared
    # derivation falls back to key presence — identical to categorization —
    # while keeping the logic in one place so it can't drift from get_config().
    config["ai_extraction_enabled"] = _default_ai_extraction_enabled(config)
    return config


def get_config() -> AppConfig:
    """Read config from file, auto-detecting defaults on first run."""
    global _cache
    if _cache is not None:
        return cast("AppConfig", dict(_cache))

    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH) as f:
                data = json.load(f)
            # Migrate the legacy single-provider key to the per-feature keys
            # before merging, persisting the rewrite so the migration runs once.
            migrated = _migrate_summary_provider(data)
            # Merge with defaults for any missing keys
            config = cast("AppConfig", dict(_DEFAULTS))
            config.update(data)
            # Derive ai_categorization_enabled when absent from the persisted
            # file (existing users before the flag was introduced). Once the
            # user explicitly sets the key, `data` contains it and this line
            # is a no-op.
            if "ai_categorization_enabled" not in data:
                config["ai_categorization_enabled"] = _has_openai_key()
            # The categorization provider has a computed default parallel to
            # that flag; derive it when absent (migration seeds it for legacy
            # configs, so this covers only pre-key configs it didn't touch).
            if "categorization_provider" not in data:
                config["categorization_provider"] = _default_categorization_provider()
            # Absent-key derivation for the extraction consent (existing users
            # predating the flag). Preserve the prior consent semantics: when a
            # categorization opt-out was persisted, extraction stays off (it was
            # gated on that key before this split); only a config predating both
            # keys falls back to key presence. Once persisted, `data` carries it.
            if "ai_extraction_enabled" not in data:
                config["ai_extraction_enabled"] = _default_ai_extraction_enabled(data)
            _cache = config
            if migrated:
                # Rewrite the file once so the legacy key is gone from disk and
                # the migration doesn't re-run on the next boot.
                _save_config(config)
            return cast("AppConfig", dict(_cache))
        except Exception:
            logger.exception("Failed to read config file, using auto-detected defaults")

    # First run: auto-detect
    config = _auto_detect_defaults()
    try:
        _save_config(config)
    except OSError:
        # A read-only filesystem must not crash startup — continue in-memory.
        logger.exception("Failed to persist first-run config; continuing in-memory")
    _cache = config
    return cast("AppConfig", dict(_cache))


def update_config(updates: AppConfig) -> AppConfig:
    """Update config with provided fields, persist to file, update cache."""
    global _cache
    config = get_config()
    # TypedDict.update accepts another TypedDict of the same shape; `updates`
    # is `AppConfig` (all keys optional) so only provided fields are merged.
    config.update(updates)
    # _save_config raises on failure — the cache must never hold state the disk doesn't.
    _save_config(config)
    _cache = config
    return cast("AppConfig", dict(_cache))


def _save_config(config: AppConfig) -> None:
    """Write config to data/config.json atomically. Raises OSError on failure.

    Writes to a uniquely-named temp file in the same directory, then
    ``os.replace`` (an atomic rename on the same filesystem) into place. This
    keeps first-run creation safe when two processes (e.g. finance +
    imap-poller) write concurrently: a reader always sees either the old file or
    a complete new one, never a truncated partial, and the last full writer
    wins. The temp file is removed if writing fails.
    """
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=_CONFIG_PATH.parent, prefix=".config.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(config, f, indent=2)
            f.write("\n")
        os.replace(tmp_name, _CONFIG_PATH)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def invalidate_config_cache() -> None:
    """Clear the in-memory config cache (for testing)."""
    global _cache
    _cache = None


def get_session_signing_secret() -> str:
    """Return the cookie-signing secret, generating + persisting one on first call.

    The secret is 32 random bytes (hex-encoded → 64 chars). Bumping
    `session_version` is the in-band way to invalidate cookies without
    regenerating the secret; the secret only needs to rotate if it leaks.
    """
    cfg = get_config()
    secret = cfg.get("session_signing_secret")
    if not secret:
        secret = secrets.token_hex(32)
        update_config(cast("AppConfig", {"session_signing_secret": secret}))
    return secret


def get_config_with_features() -> AppConfigWithFeatures:
    """Return config enriched with feature detection flags."""
    base = get_config()
    enriched: AppConfigWithFeatures = cast("AppConfigWithFeatures", dict(base))
    enriched["openai_enabled"] = _has_openai_key()
    enriched["aws_available"] = _has_aws_credentials()
    enriched["claude_cli_available"] = bool(shutil.which("claude"))
    enriched["codex_available"] = _has_codex_cli()
    enriched["gemini_cli_available"] = _has_gemini_cli()
    if base.get("demo_mode"):
        # Belt-and-suspenders: never surface real OAuth state in demo mode.
        enriched["chatgpt_oauth_connected"] = False
        enriched["chatgpt_oauth_email"] = None
        # Demo mode describes the demo world, not the host machine: a
        # self-hosted SQLite install with an OpenAI key and no AWS. Pinning
        # the detection flags also keeps demo fixtures deterministic across
        # generator machines (P2-H in the 2026-06-11 demo-realism spec).
        enriched["storage"] = "sqlite"
        enriched["aws_available"] = False
        enriched["openai_enabled"] = True
        enriched["claude_cli_available"] = False
        enriched["codex_available"] = False
        enriched["gemini_cli_available"] = False
    else:
        connected = _has_chatgpt_oauth()
        enriched["chatgpt_oauth_connected"] = connected
        enriched["chatgpt_oauth_email"] = _get_chatgpt_oauth_email() if connected else None
    return enriched
