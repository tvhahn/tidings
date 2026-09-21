"""Tests for src/finance/user_mapping.py.

Covers the ``USER_MAPPINGS`` environment channel (the Lambda's only way to
personalize the ForwardedTo → UserId map, since the image ships no ``data/``),
the CSV fallbacks, and the user-id resolution behind the synthetic
``{user_id}@local`` partition.

Addresses here are synthetic. Several assertions prove that a *malformed*
entry's text never reaches a log record — real forwarding addresses are
personal, so the warnings carry positions only.
"""

from __future__ import annotations

import logging

import pytest

import src.finance.storage as storage_module
import src.finance.user_mapping as user_mapping_module
from src.finance.user_mapping import (
    get_forwarded_to_addresses,
    get_user_id,
    load_user_mappings,
    local_forwarded_to,
    user_id_cache,
)

ENV_VAR = "USER_MAPPINGS"
ADDRESS_A = "inbox-a@example.net"
ADDRESS_B = "inbox-b@example.net"
BAD_ADDRESS = "no-equals-sign-here@example.net"

# The tracked default CSV (tests/conftest.py pins _PERSONAL_MAPPINGS away).
BUNDLED_CSV_ADDRESSES = ["demo@example.com", "youremail@example.com"]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both env channels start closed; ``user_id_cache`` is reset by conftest.

    ``monkeypatch`` undoes the deletions itself, so there is nothing to tear
    down here.
    """
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.delenv("USER_ID", raising=False)


def _set_config_user_id(monkeypatch: pytest.MonkeyPatch, user_id: str | None) -> None:
    """Pin ``get_config()`` for both twins.

    ``user_mapping`` imports ``get_config`` per call (so it sees the
    app_config-level patch) while ``storage`` binds it at module import (so it
    needs its own). Patching both keeps the twin-agreement test honest.
    """
    config: dict[str, str] = {} if user_id is None else {"user_id": user_id}
    monkeypatch.setattr("src.finance.app_config.get_config", lambda: dict(config))
    monkeypatch.setattr(storage_module, "get_config", lambda: dict(config))


class TestLoadUserMappingsFromCsv:
    """Behaviour with no env var set must be exactly what it was before."""

    def test_falls_back_to_bundled_csv(self) -> None:
        load_user_mappings()
        assert sorted(user_id_cache) == sorted(BUNDLED_CSV_ADDRESSES)

    def test_get_user_id_reads_the_cache(self) -> None:
        load_user_mappings()
        assert get_user_id("demo@example.com") == "default"
        assert get_user_id("nobody@example.net") is None


class TestLoadUserMappingsFromEnv:
    def test_env_replaces_the_csv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_VAR, f" {ADDRESS_A} = alice , {ADDRESS_B}=bob ")
        load_user_mappings()
        assert user_id_cache == {ADDRESS_A: "alice", ADDRESS_B: "bob"}
        for csv_address in BUNDLED_CSV_ADDRESSES:
            assert csv_address not in user_id_cache

    def test_cache_is_mutated_in_place(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Modules that did ``from … import user_id_cache`` must see the update."""
        before = user_id_cache
        monkeypatch.setenv(ENV_VAR, f"{ADDRESS_A}=alice")
        load_user_mappings()
        assert user_mapping_module.user_id_cache is before
        assert before == {ADDRESS_A: "alice"}

    def test_blank_pairs_are_dropped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_VAR, f",,{ADDRESS_A}=alice,  ,")
        load_user_mappings()
        assert user_id_cache == {ADDRESS_A: "alice"}

    def test_user_id_may_contain_an_equals_sign(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The split is on the FIRST '=' — the address side never contains one."""
        monkeypatch.setenv(ENV_VAR, f"{ADDRESS_A}=a=b")
        load_user_mappings()
        assert user_id_cache == {ADDRESS_A: "a=b"}

    @pytest.mark.parametrize(
        "raw",
        [
            f"{ADDRESS_A}=alice,{BAD_ADDRESS}",
            f"{ADDRESS_A}=alice,={BAD_ADDRESS}",
            f"{ADDRESS_A}=alice,{BAD_ADDRESS}=",
        ],
    )
    def test_malformed_pair_is_skipped_with_a_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, raw: str
    ) -> None:
        monkeypatch.setenv(ENV_VAR, raw)
        with caplog.at_level(logging.DEBUG):
            load_user_mappings()
        assert user_id_cache == {ADDRESS_A: "alice"}
        assert ENV_VAR in caplog.text
        assert "pair 2" in caplog.text

    @pytest.mark.parametrize(
        "raw",
        [
            f"{ADDRESS_A}=alice,{BAD_ADDRESS}",
            f"{BAD_ADDRESS},{BAD_ADDRESS}=",
            f"{ADDRESS_A}=alice",
        ],
    )
    def test_addresses_never_reach_a_log_record(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, raw: str
    ) -> None:
        monkeypatch.setenv(ENV_VAR, raw)
        with caplog.at_level(logging.DEBUG):
            load_user_mappings()
        for record in caplog.records:
            rendered = record.getMessage() + str(record.args)
            assert ADDRESS_A not in rendered
            assert BAD_ADDRESS not in rendered
        assert ADDRESS_A not in caplog.text
        assert BAD_ADDRESS not in caplog.text

    def test_all_invalid_env_warns_and_falls_back_to_csv(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv(ENV_VAR, f"{BAD_ADDRESS},=,  =nobody")
        with caplog.at_level(logging.WARNING):
            load_user_mappings()
        assert sorted(user_id_cache) == sorted(BUNDLED_CSV_ADDRESSES)
        assert "no valid pairs" in caplog.text

    def test_blank_env_falls_back_to_csv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_VAR, "   ")
        load_user_mappings()
        assert sorted(user_id_cache) == sorted(BUNDLED_CSV_ADDRESSES)


class TestLocalForwardedTo:
    """The synthetic `{user_id}@local` partition — the monthly-summary bug."""

    def test_user_id_env_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_config_user_id(monkeypatch, "from-config")
        monkeypatch.setenv("USER_ID", "from-env")
        assert local_forwarded_to() == "from-env@local"

    def test_config_used_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_config_user_id(monkeypatch, "from-config")
        assert local_forwarded_to() == "from-config@local"

    def test_default_when_neither_is_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_config_user_id(monkeypatch, None)
        assert local_forwarded_to() == "default@local"

    def test_blank_user_id_env_falls_through_to_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_config_user_id(monkeypatch, "from-config")
        monkeypatch.setenv("USER_ID", "")
        assert local_forwarded_to() == "from-config@local"

    @pytest.mark.parametrize(
        ("env_user_id", "config_user_id"),
        [
            ("from-env", "from-config"),
            (None, "from-config"),
            (None, None),
        ],
    )
    def test_agrees_with_the_storage_twin(
        self, monkeypatch: pytest.MonkeyPatch, env_user_id: str | None, config_user_id: str | None
    ) -> None:
        """``storage._get_user_id`` is the twin — a drift splits reads from writes."""
        _set_config_user_id(monkeypatch, config_user_id)
        if env_user_id is None:
            monkeypatch.delenv("USER_ID", raising=False)
        else:
            monkeypatch.setenv("USER_ID", env_user_id)

        resolved = user_mapping_module._resolve_user_id()
        assert resolved == storage_module._get_user_id()
        assert local_forwarded_to() == f"{resolved}@local"


class TestGetForwardedToAddresses:
    def test_includes_the_env_user_id_partition(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_config_user_id(monkeypatch, "from-config")
        monkeypatch.setenv("USER_ID", "from-env")
        monkeypatch.setenv(ENV_VAR, f"{ADDRESS_A}=alice")

        addresses = get_forwarded_to_addresses()

        assert addresses == [ADDRESS_A, "from-env@local"]

    def test_uses_the_config_partition_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_config_user_id(monkeypatch, "from-config")
        monkeypatch.setenv(ENV_VAR, f"{ADDRESS_A}=alice")

        addresses = get_forwarded_to_addresses()

        assert addresses == [ADDRESS_A, "from-config@local"]

    def test_csv_partitions_when_no_env_mapping(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_config_user_id(monkeypatch, "from-config")

        addresses = get_forwarded_to_addresses()

        assert addresses == [*BUNDLED_CSV_ADDRESSES, "from-config@local"]
