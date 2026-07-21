"""Tests for the agent-token persistence layer."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from src.finance import agent_tokens, app_config

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the config persistence at a tmp file and reset the cache."""
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(app_config, "_CONFIG_PATH", cfg_path)
    app_config.invalidate_config_cache()
    yield cfg_path
    app_config.invalidate_config_cache()


class TestTokenGeneration:
    def test_raw_token_has_fin_prefix(self) -> None:
        raw = agent_tokens.generate_raw_token()
        assert raw.startswith("fin_")
        # 32 url-safe bytes ≈ 43 chars after b64; total comfortably over 30.
        assert len(raw) > 30

    def test_two_tokens_are_distinct(self) -> None:
        a = agent_tokens.generate_raw_token()
        b = agent_tokens.generate_raw_token()
        assert a != b

    def test_hash_is_deterministic(self) -> None:
        assert agent_tokens.hash_token("fin_x") == agent_tokens.hash_token("fin_x")

    def test_hash_differs_per_input(self) -> None:
        assert agent_tokens.hash_token("a") != agent_tokens.hash_token("b")


class TestAddToken:
    def test_default_scope_is_read_write(self, isolated_config: Path) -> None:
        record, raw = agent_tokens.add_token(label="test")
        assert record["scope"] == "read+write"
        assert raw.startswith("fin_")

    def test_persisted_record_is_hash_only(self, isolated_config: Path) -> None:
        _, raw = agent_tokens.add_token(label="laptop-claude")
        tokens = agent_tokens.list_tokens()
        assert len(tokens) == 1
        # The raw token is not in the record.
        for v in tokens[0].values():
            assert v != raw
        assert tokens[0]["token_hash"] == agent_tokens.hash_token(raw)

    def test_explicit_read_scope(self, isolated_config: Path) -> None:
        record, _ = agent_tokens.add_token(label="readonly", scope="read")
        assert record["scope"] == "read"

    def test_unknown_scope_rejected(self, isolated_config: Path) -> None:
        with pytest.raises(ValueError, match="unknown scope"):
            agent_tokens.add_token(label="x", scope="admin")  # type: ignore[arg-type]

    def test_blank_label_rejected(self, isolated_config: Path) -> None:
        with pytest.raises(ValueError, match="label"):
            agent_tokens.add_token(label="   ")

    def test_id_is_unique_per_token(self, isolated_config: Path) -> None:
        a, _ = agent_tokens.add_token(label="a")
        b, _ = agent_tokens.add_token(label="b")
        assert a["id"] != b["id"]

    def test_created_at_is_set_last_used_at_is_none(self, isolated_config: Path) -> None:
        record, _ = agent_tokens.add_token(label="t")
        assert record["created_at"]
        assert record["last_used_at"] is None


class TestListAndRevoke:
    def test_list_is_empty_by_default(self, isolated_config: Path) -> None:
        assert agent_tokens.list_tokens() == []

    def test_revoke_removes_record(self, isolated_config: Path) -> None:
        record, _ = agent_tokens.add_token(label="laptop")
        assert agent_tokens.revoke_token(record["id"]) is True
        assert agent_tokens.list_tokens() == []

    def test_revoke_unknown_id_returns_false(self, isolated_config: Path) -> None:
        agent_tokens.add_token(label="laptop")
        assert agent_tokens.revoke_token("does-not-exist") is False
        assert len(agent_tokens.list_tokens()) == 1

    def test_revoke_only_target(self, isolated_config: Path) -> None:
        keep, _ = agent_tokens.add_token(label="keep")
        drop, _ = agent_tokens.add_token(label="drop")
        agent_tokens.revoke_token(drop["id"])
        remaining = agent_tokens.list_tokens()
        assert [t["id"] for t in remaining] == [keep["id"]]


class TestLookup:
    def test_find_by_raw_returns_record(self, isolated_config: Path) -> None:
        record, raw = agent_tokens.add_token(label="t")
        found = agent_tokens.find_token_by_raw(raw)
        assert found is not None
        assert found["id"] == record["id"]

    def test_find_by_raw_unknown_returns_none(self, isolated_config: Path) -> None:
        agent_tokens.add_token(label="t")
        assert agent_tokens.find_token_by_raw("fin_unknown") is None

    def test_find_by_raw_rejects_missing_prefix(self, isolated_config: Path) -> None:
        _, raw = agent_tokens.add_token(label="t")
        # Strip the prefix — must not match even though the rest is valid.
        bare = raw.removeprefix("fin_")
        assert agent_tokens.find_token_by_raw(bare) is None

    def test_find_by_raw_handles_empty(self, isolated_config: Path) -> None:
        assert agent_tokens.find_token_by_raw("") is None

    def test_revoked_token_no_longer_found(self, isolated_config: Path) -> None:
        record, raw = agent_tokens.add_token(label="t")
        agent_tokens.revoke_token(record["id"])
        assert agent_tokens.find_token_by_raw(raw) is None


class TestMarkUsed:
    def test_mark_used_sets_timestamp(self, isolated_config: Path) -> None:
        record, _ = agent_tokens.add_token(label="t")
        assert record["last_used_at"] is None
        agent_tokens.mark_used(record["id"])
        refreshed = agent_tokens.list_tokens()[0]
        assert refreshed["last_used_at"] is not None

    def test_mark_used_unknown_id_is_noop(self, isolated_config: Path) -> None:
        record, _ = agent_tokens.add_token(label="t")
        agent_tokens.mark_used("unknown")
        # Original token unchanged.
        refreshed = agent_tokens.list_tokens()[0]
        assert refreshed["id"] == record["id"]
        assert refreshed["last_used_at"] is None


class TestPersistenceRoundTrip:
    def test_tokens_survive_cache_invalidation(self, isolated_config: Path) -> None:
        _, raw = agent_tokens.add_token(label="persisted")
        app_config.invalidate_config_cache()
        # New process worth of cache — should still find the token.
        found = agent_tokens.find_token_by_raw(raw)
        assert found is not None
        assert found["label"] == "persisted"

    def test_existing_app_config_keys_are_preserved(self, isolated_config: Path) -> None:
        app_config.update_config({"timezone": "Europe/Berlin"})
        agent_tokens.add_token(label="t")
        cfg = app_config.get_config()
        assert cfg["timezone"] == "Europe/Berlin"
        assert len(cfg.get("agent_tokens", []) or []) == 1
