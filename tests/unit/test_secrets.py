"""Tests for the tiered secret loader in ``src/finance/secrets.py``.

Covers all three fallback tiers, the ``RuntimeError`` path when every
tier misses, and the ``lru_cache`` behavior that ensures one SSM call
per container lifetime.
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from src.finance import secrets
from src.finance.secrets import get_openai_api_key


@pytest.fixture(autouse=True)
def _clear_cache_and_env():
    """Clear the lru_cache and strip OPENAI_API_KEY between tests."""
    get_openai_api_key.cache_clear()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("OPENAI_API_KEY", None)
        yield
    get_openai_api_key.cache_clear()


class TestTier1SSM:
    """Tier 1 — SSM Parameter Store."""

    def test_ssm_hit_returns_value(self):
        mock_ssm = MagicMock(name="ssm")
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "sk-from-ssm"}}
        with patch("boto3.client", return_value=mock_ssm) as mock_client:
            result = get_openai_api_key()

        assert result == "sk-from-ssm"
        mock_client.assert_called_once_with("ssm", region_name="us-west-2")
        mock_ssm.get_parameter.assert_called_once_with(Name="/email-parser/openai-api-key", WithDecryption=True)


class TestTier2Env:
    """Tier 1 fails → Tier 2 — Process environment."""

    def test_ssm_client_error_falls_through_to_env(self):
        mock_ssm = MagicMock(name="ssm")
        mock_ssm.get_parameter.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "denied"}},
            "GetParameter",
        )
        with (
            patch("boto3.client", return_value=mock_ssm),
            patch.dict(os.environ, {"OPENAI_API_KEY": "sk-from-env"}),
        ):
            result = get_openai_api_key()

        assert result == "sk-from-env"
        mock_ssm.get_parameter.assert_called_once()


class TestTier3Dotenv:
    """Tier 1 + Tier 2 fail → Tier 3 — .env file."""

    def test_dotenv_loads_key_when_ssm_and_env_miss(self):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "denied"}},
            "GetParameter",
        )

        def fake_load_dotenv(*_args: object, **_kwargs: object) -> bool:
            os.environ["OPENAI_API_KEY"] = "sk-from-dotenv"
            return True

        with (
            patch("boto3.client", return_value=mock_ssm),
            patch("dotenv.load_dotenv", side_effect=fake_load_dotenv),
        ):
            result = get_openai_api_key()

        assert result == "sk-from-dotenv"


class TestAllTiersFail:
    """All three tiers miss → RuntimeError."""

    def test_all_miss_raises_runtime_error(self):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "denied"}},
            "GetParameter",
        )
        with (
            patch("boto3.client", return_value=mock_ssm),
            patch("dotenv.load_dotenv", return_value=False),
            pytest.raises(RuntimeError, match="OPENAI_API_KEY not found"),
        ):
            get_openai_api_key()


class TestLruCache:
    """Second call must not re-invoke SSM."""

    def test_second_call_is_cached(self):
        mock_ssm = MagicMock(name="ssm")
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "sk-cached"}}
        with patch("boto3.client", return_value=mock_ssm) as mock_client:
            first = get_openai_api_key()
            second = get_openai_api_key()

        assert first == "sk-cached"
        assert second == "sk-cached"
        # boto3.client should only be called once across both invocations
        assert mock_client.call_count == 1
        mock_ssm.get_parameter.assert_called_once()


class TestTier1ErrorVariants:
    """Tier 1 fails through every documented error variant → Tier 2 env."""

    def test_no_credentials_error_falls_through_to_env(self):
        from botocore.exceptions import NoCredentialsError

        mock_ssm = MagicMock()
        mock_ssm.get_parameter.side_effect = NoCredentialsError()
        with (
            patch("boto3.client", return_value=mock_ssm),
            patch.dict(os.environ, {"OPENAI_API_KEY": "sk-from-env"}),
        ):
            assert get_openai_api_key() == "sk-from-env"

    def test_boto3_import_error_falls_through_to_env(self):
        # A ``None`` entry in sys.modules makes ``import boto3`` raise ImportError,
        # exercising the second ``except`` arm of the Tier 1 block.
        with (
            patch.dict("sys.modules", {"boto3": None}),
            patch.dict(os.environ, {"OPENAI_API_KEY": "sk-from-env"}),
        ):
            assert get_openai_api_key() == "sk-from-env"


class TestTier3DataEnv:
    """Tier 1 + Tier 2 miss → Tier 3 reads ``data/.env`` via dotenv_values."""

    def _failing_ssm(self) -> MagicMock:
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "denied"}},
            "GetParameter",
        )
        return mock_ssm

    def test_data_env_provides_key(self):
        # Tier 3 now resolves the module-level DATA_ENV_PATH constant, so mock
        # that seam (the unit-suite autouse fixture redirects it to a tmp file).
        fake_env = MagicMock()
        fake_env.is_file.return_value = True
        with (
            patch("boto3.client", return_value=self._failing_ssm()),
            patch("src.finance.secrets.DATA_ENV_PATH", fake_env),
            patch("dotenv.dotenv_values", return_value={"OPENAI_API_KEY": "sk-from-data-env"}),
        ):
            assert get_openai_api_key() == "sk-from-data-env"

    def test_data_env_present_but_no_key_reaches_runtime_error(self):
        fake_env = MagicMock()
        fake_env.is_file.return_value = True
        with (
            patch("boto3.client", return_value=self._failing_ssm()),
            patch("src.finance.secrets.DATA_ENV_PATH", fake_env),
            patch("dotenv.dotenv_values", return_value={}),  # file present, key absent
            patch("dotenv.load_dotenv", return_value=False),  # Tier 4 also misses
            pytest.raises(RuntimeError, match="OPENAI_API_KEY not found"),
        ):
            get_openai_api_key()


class TestModuleConstants:
    """Guard against accidental parameter-name drift."""

    def test_constants_are_stable(self):
        assert secrets._SSM_PARAMETER_NAME == "/email-parser/openai-api-key"

    def test_region_defaults_and_respects_env(self, monkeypatch):
        from src.finance.aws_region import get_aws_region

        monkeypatch.delenv("AWS_REGION", raising=False)
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
        assert get_aws_region() == "us-west-2"
        monkeypatch.setenv("AWS_REGION", "ca-central-1")
        assert get_aws_region() == "ca-central-1"
