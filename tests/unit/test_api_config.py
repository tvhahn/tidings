"""Tests for /api/v1/config read + update endpoint.

Focuses on the ai_categorization_enabled privacy flag round-trip. Uses a
tmp_path-scoped config file so the test never touches the user's real
data/config.json.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

import src.finance.app_config as app_config
from tests.asserts import assert_ok, assert_problem


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Redirect _CONFIG_PATH to a tmp file + clear the in-memory cache."""
    tmp_config = tmp_path / "config.json"
    monkeypatch.setattr(app_config, "_CONFIG_PATH", Path(tmp_config))
    app_config.invalidate_config_cache()
    yield tmp_config
    app_config.invalidate_config_cache()


class TestAiCategorizationFlag:
    """Round-trip tests for the ai_categorization_enabled privacy flag."""

    def test_get_exposes_flag(self, isolated_config: Path, api_client) -> None:
        """GET /config includes ai_categorization_enabled in the response."""
        resp = api_client.get("/api/v1/config")
        assert_ok(resp)
        data = resp.json()
        assert "ai_categorization_enabled" in data
        assert isinstance(data["ai_categorization_enabled"], bool)

    def test_put_flips_flag_off(self, isolated_config: Path, api_client) -> None:
        """PUT with ai_categorization_enabled=false persists and GET reflects it."""
        resp = api_client.put(
            "/api/v1/config",
            json={"ai_categorization_enabled": False},
        )
        assert_ok(resp)
        assert resp.json()["ai_categorization_enabled"] is False

        # Re-read to confirm persistence
        resp2 = api_client.get("/api/v1/config")
        assert resp2.json()["ai_categorization_enabled"] is False

    def test_put_flips_flag_on(self, isolated_config: Path, api_client) -> None:
        """PUT with ai_categorization_enabled=true persists and GET reflects it."""
        resp = api_client.put(
            "/api/v1/config",
            json={"ai_categorization_enabled": True},
        )
        assert_ok(resp)
        assert resp.json()["ai_categorization_enabled"] is True

        resp2 = api_client.get("/api/v1/config")
        assert resp2.json()["ai_categorization_enabled"] is True

    def test_default_when_no_openai_key_is_false(self, isolated_config: Path, api_client) -> None:
        """First-run with no OPENAI_API_KEY → flag auto-detects as False."""
        # Drop any real OPENAI_API_KEY for this call
        with patch("src.finance.app_config._has_openai_key", return_value=False):
            resp = api_client.get("/api/v1/config")
        assert resp.json()["ai_categorization_enabled"] is False

    def test_default_when_openai_key_present_is_true(self, isolated_config: Path, api_client) -> None:
        """First-run with OPENAI_API_KEY set → flag auto-detects as True."""
        with patch("src.finance.app_config._has_openai_key", return_value=True):
            resp = api_client.get("/api/v1/config")
        assert resp.json()["ai_categorization_enabled"] is True

    def test_user_choice_overrides_auto_detect(self, isolated_config: Path, api_client) -> None:
        """Once the user explicitly sets the flag, it wins over auto-detection."""
        # User turns it off
        api_client.put("/api/v1/config", json={"ai_categorization_enabled": False})

        # Even if OPENAI_API_KEY would auto-detect True, the persisted False wins
        with patch("src.finance.app_config._has_openai_key", return_value=True):
            resp = api_client.get("/api/v1/config")
        assert resp.json()["ai_categorization_enabled"] is False


class TestAiExtractionFlag:
    """Round-trip + derivation tests for the ai_extraction_enabled consent (L1).

    The extraction consent is a distinct key whose persisted value always wins.
    Its default: on a fresh install it derives from key presence (True iff an
    OpenAI key is set). When absent from an *existing* config it preserves the
    prior consent semantics — inheriting a persisted ai_categorization_enabled
    (which gated extraction before the split) and only falling back to key
    presence when neither AI key was ever persisted.
    """

    def test_get_exposes_flag(self, isolated_config: Path, api_client) -> None:
        resp = api_client.get("/api/v1/config")
        assert_ok(resp)
        data = resp.json()
        assert "ai_extraction_enabled" in data
        assert isinstance(data["ai_extraction_enabled"], bool)

    def test_put_flips_flag_off(self, isolated_config: Path, api_client) -> None:
        resp = api_client.put("/api/v1/config", json={"ai_extraction_enabled": False})
        assert_ok(resp)
        assert resp.json()["ai_extraction_enabled"] is False
        assert api_client.get("/api/v1/config").json()["ai_extraction_enabled"] is False

    def test_put_flips_flag_on(self, isolated_config: Path, api_client) -> None:
        resp = api_client.put("/api/v1/config", json={"ai_extraction_enabled": True})
        assert_ok(resp)
        assert resp.json()["ai_extraction_enabled"] is True
        assert api_client.get("/api/v1/config").json()["ai_extraction_enabled"] is True

    def test_default_when_no_openai_key_is_false(self, isolated_config: Path, api_client) -> None:
        """Fresh config (no data/config.json) + no OPENAI_API_KEY → default False."""
        with patch("src.finance.app_config._has_openai_key", return_value=False):
            resp = api_client.get("/api/v1/config")
        assert resp.json()["ai_extraction_enabled"] is False

    def test_default_when_openai_key_present_is_true(self, isolated_config: Path, api_client) -> None:
        """Fresh config + OPENAI_API_KEY set → default True."""
        with patch("src.finance.app_config._has_openai_key", return_value=True):
            resp = api_client.get("/api/v1/config")
        assert resp.json()["ai_extraction_enabled"] is True

    def test_user_choice_overrides_auto_detect(self, isolated_config: Path, api_client) -> None:
        api_client.put("/api/v1/config", json={"ai_extraction_enabled": False})
        with patch("src.finance.app_config._has_openai_key", return_value=True):
            resp = api_client.get("/api/v1/config")
        assert resp.json()["ai_extraction_enabled"] is False

    def test_absent_key_derives_from_persisted_categorization_optout(self, isolated_config: Path, api_client) -> None:
        """Upgrade consent regression guard: a config predating the flag that
        persisted a categorization *opt-out* (ai_categorization_enabled=False,
        no ai_extraction_enabled) must keep extraction OFF even with a key in
        env — before the split, extraction was gated on that same categorization
        key, so deriving purely from key presence would silently re-enable AI."""
        isolated_config.write_text(json.dumps({"ai_categorization_enabled": False, "storage": "sqlite"}))
        app_config.invalidate_config_cache()
        with patch("src.finance.app_config._has_openai_key", return_value=True):
            resp = api_client.get("/api/v1/config")
        body = resp.json()
        assert body["ai_extraction_enabled"] is False
        # The persisted categorization choice is untouched.
        assert body["ai_categorization_enabled"] is False

    def test_absent_key_derives_from_persisted_categorization_optin(self, isolated_config: Path, api_client) -> None:
        """A config that persisted categorization=True (and no extraction key)
        inherits it: extraction derives True when a key is present."""
        isolated_config.write_text(json.dumps({"ai_categorization_enabled": True, "storage": "sqlite"}))
        app_config.invalidate_config_cache()
        with patch("src.finance.app_config._has_openai_key", return_value=True):
            resp = api_client.get("/api/v1/config")
        body = resp.json()
        assert body["ai_extraction_enabled"] is True
        assert body["ai_categorization_enabled"] is True

    def test_neither_ai_key_persisted_falls_back_to_key_present(self, isolated_config: Path, api_client) -> None:
        """A config predating *both* AI keys falls back to key presence: with a
        key in env, extraction derives True."""
        isolated_config.write_text(json.dumps({"storage": "sqlite"}))
        app_config.invalidate_config_cache()
        with patch("src.finance.app_config._has_openai_key", return_value=True):
            resp = api_client.get("/api/v1/config")
        assert resp.json()["ai_extraction_enabled"] is True

    def test_neither_ai_key_persisted_no_key_defaults_false(self, isolated_config: Path, api_client) -> None:
        """A config predating both AI keys, with no key in env → extraction
        derives False."""
        isolated_config.write_text(json.dumps({"storage": "sqlite"}))
        app_config.invalidate_config_cache()
        with patch("src.finance.app_config._has_openai_key", return_value=False):
            resp = api_client.get("/api/v1/config")
        assert resp.json()["ai_extraction_enabled"] is False

    def test_auto_detect_defaults_includes_flag(self, monkeypatch) -> None:
        """_auto_detect_defaults derives the flag parallel to categorization."""
        from src.finance import app_config

        monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
        monkeypatch.setattr(app_config, "_has_openai_key", lambda: True)
        config = app_config._auto_detect_defaults()
        assert config["ai_extraction_enabled"] is True
        assert config["ai_categorization_enabled"] is True

        monkeypatch.setattr(app_config, "_has_openai_key", lambda: False)
        config = app_config._auto_detect_defaults()
        assert config["ai_extraction_enabled"] is False
        assert config["ai_categorization_enabled"] is False


class TestTimezone:
    """Round-trip tests for the timezone setting."""

    def test_get_exposes_default_timezone(self, isolated_config: Path, api_client) -> None:
        resp = api_client.get("/api/v1/config")
        assert_ok(resp)
        assert resp.json()["timezone"] == "America/Los_Angeles"

    def test_put_valid_iana_zone_persists(self, isolated_config: Path, api_client) -> None:
        resp = api_client.put("/api/v1/config", json={"timezone": "Europe/Berlin"})
        assert_ok(resp)
        assert resp.json()["timezone"] == "Europe/Berlin"

        resp2 = api_client.get("/api/v1/config")
        assert resp2.json()["timezone"] == "Europe/Berlin"

    def test_put_invalid_zone_returns_400(self, isolated_config: Path, api_client) -> None:
        resp = api_client.put("/api/v1/config", json={"timezone": "Mars/Olympus_Mons"})
        assert_problem(resp, 400)
        assert "Mars/Olympus_Mons" in resp.json()["error"]

        # Confirm persisted value did not change
        resp2 = api_client.get("/api/v1/config")
        assert resp2.json()["timezone"] == "America/Los_Angeles"


class TestFirstRunStorageDefault:
    """First run must land on SQLite + demo mode even when AWS credentials
    are present — DynamoDB is an explicit opt-in, not an auto-upgrade. The
    old behavior silently pointed any machine with ~/.aws credentials at a
    cloud table on first boot. The one exception is the AWS Lambda pipeline
    (detected via AWS_LAMBDA_FUNCTION_NAME), which is always DynamoDB-backed."""

    def test_aws_credentials_do_not_auto_upgrade_storage(self, monkeypatch) -> None:
        from src.finance import app_config

        monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
        monkeypatch.setattr(app_config, "_has_aws_credentials", lambda: True)
        config = app_config._auto_detect_defaults()
        assert config["storage"] == "sqlite"
        assert config["demo_mode"] is True

    def test_no_aws_credentials_same_default(self, monkeypatch) -> None:
        from src.finance import app_config

        monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
        monkeypatch.setattr(app_config, "_has_aws_credentials", lambda: False)
        config = app_config._auto_detect_defaults()
        assert config["storage"] == "sqlite"
        assert config["demo_mode"] is True

    def test_lambda_runtime_forces_dynamodb(self, monkeypatch) -> None:
        """The Lambda pipeline ships no data/config.json and runs read-only, so
        it re-runs first-run defaults on every cold start. AWS_LAMBDA_FUNCTION_NAME
        (always set by the runtime) must force DynamoDB + no demo mode, otherwise
        categorization falls back to the bundled seed category list."""
        from src.finance import app_config

        monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "email-parser")
        # AWS credential detection is irrelevant inside Lambda — the env var wins.
        monkeypatch.setattr(app_config, "_has_aws_credentials", lambda: False)
        config = app_config._auto_detect_defaults()
        assert config["storage"] == "dynamodb"
        assert config["demo_mode"] is False


class TestServiceReinitialization:
    """PUT /config must reinitialize the service singletons only when demo_mode
    or user_id actually changes — the branch that repartitions DynamoDB / swaps
    the SQLite path under the running app (config.py:56-69).
    """

    def test_user_id_change_reinitializes_services(self, isolated_config: Path, api_client) -> None:
        with (
            patch("src.api.dependencies.reinitialize_services") as reinit,
            patch("src.finance.demo_loader.ensure_demo_loaded") as demo_load,
        ):
            assert_ok(api_client.put("/api/v1/config", json={"user_id": "alice"}))
        reinit.assert_called_once()
        demo_load.assert_not_called()  # a user_id switch doesn't touch demo data

    def test_enabling_demo_mode_loads_demo_and_reinitializes(self, isolated_config: Path, api_client) -> None:
        # Start from demo_mode off so turning it on is a real transition.
        isolated_config.write_text(json.dumps({"demo_mode": False, "storage": "sqlite"}))
        app_config.invalidate_config_cache()
        with (
            patch("src.api.dependencies.reinitialize_services") as reinit,
            patch("src.finance.demo_loader.ensure_demo_loaded") as demo_load,
        ):
            assert_ok(api_client.put("/api/v1/config", json={"demo_mode": True}))
        demo_load.assert_called_once()
        reinit.assert_called_once()

    def test_unrelated_change_does_not_reinitialize(self, isolated_config: Path, api_client) -> None:
        with (
            patch("src.api.dependencies.reinitialize_services") as reinit,
            patch("src.finance.demo_loader.ensure_demo_loaded") as demo_load,
        ):
            assert_ok(api_client.put("/api/v1/config", json={"timezone": "Europe/Berlin"}))
        reinit.assert_not_called()
        demo_load.assert_not_called()


class TestOpenAIConnection:
    """POST /config/test-openai validates a key and, on success, persists it to
    data/.env (config.py:84-121) — previously wholly untested.
    """

    def test_invalid_key_returns_ok_false(self, api_client) -> None:
        with patch("openai.OpenAI") as mock_openai:
            mock_openai.return_value.models.list.side_effect = Exception("invalid api key: sk-bad")
            resp = api_client.post("/api/v1/config/test-openai", json={"api_key": "sk-bad"})
        body = assert_ok(resp)
        assert body["ok"] is False
        assert body["error"]  # carries the (truncated) failure reason
        assert len(body["error"]) <= 200

    def test_valid_key_persists_to_data_env(self, api_client, tmp_path: Path, monkeypatch) -> None:
        # chdir so the handler's hardcoded Path("data/.env") lands under tmp_path,
        # never the repo's real data/.env.
        monkeypatch.chdir(tmp_path)
        with patch("openai.OpenAI") as mock_openai:
            mock_openai.return_value.models.list.return_value = []
            resp = api_client.post("/api/v1/config/test-openai", json={"api_key": "sk-good-123"})
        body = assert_ok(resp)
        assert body["ok"] is True
        env_file = tmp_path / "data" / ".env"
        assert env_file.is_file()
        assert "OPENAI_API_KEY=sk-good-123" in env_file.read_text()

    def test_valid_key_replaces_existing_line(self, api_client, tmp_path: Path, monkeypatch) -> None:
        # A pre-existing OPENAI_API_KEY line is replaced in place, not duplicated,
        # and unrelated lines are preserved (config.py:102-109).
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / ".env").write_text("OTHER=keep\nOPENAI_API_KEY=sk-old\n")
        with patch("openai.OpenAI") as mock_openai:
            mock_openai.return_value.models.list.return_value = []
            assert_ok(api_client.post("/api/v1/config/test-openai", json={"api_key": "sk-new"}))
        text = (tmp_path / "data" / ".env").read_text()
        assert "OPENAI_API_KEY=sk-new" in text
        assert "OPENAI_API_KEY=sk-old" not in text
        assert "OTHER=keep" in text
        assert text.count("OPENAI_API_KEY=") == 1  # replaced, not appended

    def test_validation_failure_returns_ok_false(self, api_client, monkeypatch) -> None:
        # Drive the {ok: false} branch off the extracted validator directly,
        # without touching the OpenAI SDK.
        monkeypatch.setattr(
            "src.api.routers.config._validate_openai_key",
            lambda _api_key: "invalid api key: sk-bad",
        )
        resp = api_client.post("/api/v1/config/test-openai", json={"api_key": "sk-bad"})
        body = assert_ok(resp)
        assert body["ok"] is False
        assert body["error"] == "invalid api key: sk-bad"

    def test_validation_success_writes_file_0600(self, api_client, tmp_path: Path, monkeypatch) -> None:
        # A passing validator (None) persists the key to data/.env with 0600
        # perms and an OPENAI_API_KEY= line, returning {ok: true}.
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("src.api.routers.config._validate_openai_key", lambda _api_key: None)
        resp = api_client.post("/api/v1/config/test-openai", json={"api_key": "sk-good-999"})
        body = assert_ok(resp)
        assert body["ok"] is True
        env_file = tmp_path / "data" / ".env"
        assert env_file.is_file()
        assert "OPENAI_API_KEY=sk-good-999" in env_file.read_text()
        # 0600: the file holds a live API key.
        assert oct(env_file.stat().st_mode & 0o777) == "0o600"


class TestS3BackupConfigKeys:
    """Round-trip + null-clear semantics for the S3 backup config keys."""

    def test_get_exposes_defaults(self, isolated_config: Path, api_client) -> None:
        resp = api_client.get("/api/v1/config")
        assert_ok(resp)
        body = resp.json()
        assert body["s3_backup_enabled"] is False
        assert body["s3_backup_bucket"] is None
        assert body["s3_backup_prefix"] is None

    def test_put_sets_bucket_and_prefix(self, isolated_config: Path, api_client) -> None:
        resp = api_client.put(
            "/api/v1/config",
            json={"s3_backup_enabled": True, "s3_backup_bucket": "my-backup", "s3_backup_prefix": "receipts"},
        )
        assert_ok(resp)
        body = resp.json()
        assert body["s3_backup_enabled"] is True
        assert body["s3_backup_bucket"] == "my-backup"
        assert body["s3_backup_prefix"] == "receipts"
        # Re-read to confirm persistence.
        reread = api_client.get("/api/v1/config").json()
        assert reread["s3_backup_bucket"] == "my-backup"
        assert reread["s3_backup_prefix"] == "receipts"

    def test_explicit_null_clears_bucket(self, isolated_config: Path, api_client) -> None:
        api_client.put("/api/v1/config", json={"s3_backup_bucket": "my-backup"})
        assert api_client.get("/api/v1/config").json()["s3_backup_bucket"] == "my-backup"
        # s3_backup_bucket is in NULLABLE_CONFIG_KEYS, so an explicit null clears it.
        resp = api_client.put("/api/v1/config", json={"s3_backup_bucket": None})
        assert_ok(resp)
        assert resp.json()["s3_backup_bucket"] is None
        assert api_client.get("/api/v1/config").json()["s3_backup_bucket"] is None

    def test_null_on_enabled_is_ignored(self, isolated_config: Path, api_client) -> None:
        # s3_backup_enabled is NOT nullable — a null keeps the prior value.
        api_client.put("/api/v1/config", json={"s3_backup_enabled": True})
        resp = api_client.put("/api/v1/config", json={"s3_backup_enabled": None})
        assert_ok(resp)
        assert resp.json()["s3_backup_enabled"] is True


class TestS3BackupVerifyEndpoint:
    """POST /config/test-s3-backup — stateless verify, persists nothing.

    The verifier is monkeypatched in the router namespace rather than driving
    moto through the API; the verifier's own moto coverage lives in
    tests/unit/test_s3_backup_verify.py.
    """

    def test_empty_bucket_returns_ok_false_without_verify(self, api_client, monkeypatch) -> None:
        called = {"hit": False}

        def _should_not_run(*_a, **_k):  # pragma: no cover - asserts it never runs
            called["hit"] = True
            raise AssertionError("verify should not run for an empty bucket")

        monkeypatch.setattr("src.api.routers.config.verify_backup_target", _should_not_run, raising=False)
        resp = api_client.post("/api/v1/config/test-s3-backup", json={"bucket": "   "})
        body = assert_ok(resp)
        assert body["ok"] is False
        assert body["error"] == "Bucket name is required."
        assert body["warnings"] == []
        assert called["hit"] is False

    def test_ok_result_passthrough(self, api_client, monkeypatch) -> None:
        from src.finance.s3_backup_verify import S3VerifyResult

        monkeypatch.setattr(
            "src.api.routers.config.verify_backup_target",
            lambda bucket, prefix: S3VerifyResult(ok=True, error=None, warnings=["Bucket versioning is off."]),
            raising=False,
        )
        resp = api_client.post(
            "/api/v1/config/test-s3-backup",
            json={"bucket": "my-backup", "prefix": "receipts"},
        )
        body = assert_ok(resp)
        assert body["ok"] is True
        assert body["error"] is None
        assert body["warnings"] == ["Bucket versioning is off."]

    def test_failure_result_passthrough(self, api_client, monkeypatch) -> None:
        from src.finance.s3_backup_verify import S3VerifyResult

        monkeypatch.setattr(
            "src.api.routers.config.verify_backup_target",
            lambda bucket, prefix: S3VerifyResult(ok=False, error="Bucket not found: my-backup.", warnings=[]),
            raising=False,
        )
        resp = api_client.post("/api/v1/config/test-s3-backup", json={"bucket": "my-backup"})
        body = assert_ok(resp)
        assert body["ok"] is False
        assert body["error"] == "Bucket not found: my-backup."
        assert body["warnings"] == []


class TestSummaryProviderMigration:
    """Load-time migration of the legacy single ``summary_provider`` key to the
    per-feature ``*_provider`` keys."""

    def test_no_legacy_key_is_noop(self) -> None:
        data = {"daily_summary_provider": "openai", "storage": "sqlite"}
        assert app_config._migrate_summary_provider(data) is False
        assert data == {"daily_summary_provider": "openai", "storage": "sqlite"}

    def test_already_migrated_config_untouched(self) -> None:
        data = {"daily_summary_provider": "codex", "insights_provider": "disabled"}
        before = dict(data)
        assert app_config._migrate_summary_provider(data) is False
        assert data == before

    @pytest.mark.parametrize("legacy", ["openai", "claude_cli", "codex", "gemini_cli", "disabled"])
    def test_seeds_feature_providers_from_legacy(self, legacy: str, monkeypatch) -> None:
        monkeypatch.setattr(app_config, "_has_openai_key", lambda: False)
        data = {"summary_provider": legacy, "storage": "sqlite"}
        assert app_config._migrate_summary_provider(data) is True
        assert data["daily_summary_provider"] == legacy
        assert data["insights_provider"] == legacy
        assert data["document_parsing_provider"] == legacy
        assert "summary_provider" not in data

    def test_categorization_codex_maps_to_codex(self, monkeypatch) -> None:
        # Even without a key, a legacy codex pick carries over to categorization.
        monkeypatch.setattr(app_config, "_has_openai_key", lambda: False)
        data = {"summary_provider": "codex"}
        app_config._migrate_summary_provider(data)
        assert data["categorization_provider"] == "codex"

    @pytest.mark.parametrize("legacy", ["openai", "claude_cli", "gemini_cli", "disabled"])
    def test_categorization_non_codex_with_key_is_openai(self, legacy: str, monkeypatch) -> None:
        monkeypatch.setattr(app_config, "_has_openai_key", lambda: True)
        data = {"summary_provider": legacy}
        app_config._migrate_summary_provider(data)
        assert data["categorization_provider"] == "openai"

    @pytest.mark.parametrize("legacy", ["openai", "claude_cli", "gemini_cli", "disabled"])
    def test_categorization_non_codex_without_key_is_disabled(self, legacy: str, monkeypatch) -> None:
        monkeypatch.setattr(app_config, "_has_openai_key", lambda: False)
        data = {"summary_provider": legacy}
        app_config._migrate_summary_provider(data)
        assert data["categorization_provider"] == "disabled"

    def test_existing_new_keys_not_clobbered(self, monkeypatch) -> None:
        monkeypatch.setattr(app_config, "_has_openai_key", lambda: False)
        data = {
            "summary_provider": "codex",
            "daily_summary_provider": "openai",
            "categorization_provider": "openai",
        }
        assert app_config._migrate_summary_provider(data) is True
        # Pre-set new keys win; only the absent ones are seeded from the legacy value.
        assert data["daily_summary_provider"] == "openai"
        assert data["categorization_provider"] == "openai"
        assert data["insights_provider"] == "codex"
        assert data["document_parsing_provider"] == "codex"
        assert "summary_provider" not in data

    def test_get_config_migrates_and_persists(self, isolated_config: Path, monkeypatch) -> None:
        monkeypatch.setattr(app_config, "_has_openai_key", lambda: False)
        isolated_config.write_text(json.dumps({"summary_provider": "claude_cli", "storage": "sqlite"}))
        app_config.invalidate_config_cache()

        cfg = app_config.get_config()
        assert cfg["daily_summary_provider"] == "claude_cli"
        assert cfg["insights_provider"] == "claude_cli"
        assert cfg["document_parsing_provider"] == "claude_cli"
        assert cfg["categorization_provider"] == "disabled"
        assert "summary_provider" not in cfg

        # The migration rewrote the file so the legacy key is gone from disk.
        on_disk = json.loads(isolated_config.read_text())
        assert "summary_provider" not in on_disk
        assert on_disk["daily_summary_provider"] == "claude_cli"


class TestProviderRoutingConfig:
    """PUT /config semantics for the per-feature provider/model/effort keys."""

    def test_put_sets_provider_and_model(self, isolated_config: Path, api_client) -> None:
        resp = api_client.put(
            "/api/v1/config",
            json={"daily_summary_provider": "openai", "daily_summary_model": "gpt-5.6-luna"},
        )
        assert_ok(resp)
        body = resp.json()
        assert body["daily_summary_provider"] == "openai"
        assert body["daily_summary_model"] == "gpt-5.6-luna"

    def test_explicit_null_clears_model(self, isolated_config: Path, api_client) -> None:
        api_client.put("/api/v1/config", json={"insights_model": "gpt-5.6-luna"})
        assert api_client.get("/api/v1/config").json()["insights_model"] == "gpt-5.6-luna"
        # An explicit null clears the override back to the provider default.
        resp = api_client.put("/api/v1/config", json={"insights_model": None})
        assert_ok(resp)
        assert resp.json()["insights_model"] is None
        assert api_client.get("/api/v1/config").json()["insights_model"] is None

    def test_explicit_null_clears_reasoning_effort(self, isolated_config: Path, api_client) -> None:
        api_client.put("/api/v1/config", json={"categorization_reasoning_effort": "high"})
        assert api_client.get("/api/v1/config").json()["categorization_reasoning_effort"] == "high"
        resp = api_client.put("/api/v1/config", json={"categorization_reasoning_effort": None})
        assert_ok(resp)
        assert resp.json()["categorization_reasoning_effort"] is None

    def test_null_on_non_nullable_field_ignored(self, isolated_config: Path, api_client) -> None:
        # A null on a non-nullable field keeps the old ignore-null behavior, so a
        # client can safely round-trip its whole config object.
        api_client.put("/api/v1/config", json={"timezone": "Europe/Berlin"})
        resp = api_client.put("/api/v1/config", json={"timezone": None})
        assert_ok(resp)
        assert resp.json()["timezone"] == "Europe/Berlin"

    def test_invalid_provider_returns_422(self, isolated_config: Path, api_client) -> None:
        resp = api_client.put("/api/v1/config", json={"daily_summary_provider": "not-a-provider"})
        assert_problem(resp, 422)
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_categorization_rejects_cli_provider_422(self, isolated_config: Path, api_client) -> None:
        # claude_cli is a valid daily-summary provider but NOT a categorization one.
        resp = api_client.put("/api/v1/config", json={"categorization_provider": "claude_cli"})
        assert_problem(resp, 422)


class TestInsightsUserMemo:
    """Round-trip + validation tests for the insights_user_memo briefing field.

    A single free-text field the user maintains in Settings → Intelligence that
    the monthly briefing injects as standing context. Persisted like any other
    config key; capped at 2000 chars with a 422 on overflow; explicit null clears
    it back to no memo.
    """

    def test_get_exposes_memo(self, isolated_config: Path, api_client) -> None:
        resp = api_client.get("/api/v1/config")
        assert_ok(resp)
        data = resp.json()
        assert "insights_user_memo" in data
        assert data["insights_user_memo"] is None

    def test_put_persists_memo(self, isolated_config: Path, api_client) -> None:
        memo = "Property taxes and home insurance are annual, both due around October."
        resp = api_client.put("/api/v1/config", json={"insights_user_memo": memo})
        assert_ok(resp)
        assert resp.json()["insights_user_memo"] == memo
        # Re-read to confirm persistence to disk.
        assert api_client.get("/api/v1/config").json()["insights_user_memo"] == memo

    def test_explicit_null_clears_memo(self, isolated_config: Path, api_client) -> None:
        api_client.put("/api/v1/config", json={"insights_user_memo": "Saving for a renovation."})
        assert api_client.get("/api/v1/config").json()["insights_user_memo"] is not None
        resp = api_client.put("/api/v1/config", json={"insights_user_memo": None})
        assert_ok(resp)
        assert resp.json()["insights_user_memo"] is None
        assert api_client.get("/api/v1/config").json()["insights_user_memo"] is None

    def test_at_limit_accepted(self, isolated_config: Path, api_client) -> None:
        resp = api_client.put("/api/v1/config", json={"insights_user_memo": "x" * 2000})
        assert_ok(resp)
        assert len(resp.json()["insights_user_memo"]) == 2000

    def test_over_limit_returns_422(self, isolated_config: Path, api_client) -> None:
        resp = api_client.put("/api/v1/config", json={"insights_user_memo": "x" * 2001})
        assert_problem(resp, 422)
        assert resp.json()["code"] == "VALIDATION_ERROR"


class TestConfigWriteFailure:
    """A failed disk write must surface as a 500 with a machine code, not fake success."""

    def test_put_config_write_failure_returns_500(
        self, isolated_config: Path, monkeypatch: pytest.MonkeyPatch, api_client
    ) -> None:
        def _boom(_config: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(app_config, "_save_config", _boom)
        resp = api_client.put("/api/v1/config", json={"ai_categorization_enabled": False})
        assert_problem(resp, 500)
        assert resp.json()["code"] == "CONFIG_WRITE_FAILED"
