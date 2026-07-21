"""Tests for the scripts/agent/agent_token.py CLI."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from src.finance import agent_tokens, app_config

if TYPE_CHECKING:
    from collections.abc import Iterator


_CLI_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "agent" / "agent_token.py"
_spec = importlib.util.spec_from_file_location("agent_token_cli", _CLI_PATH)
assert _spec is not None
assert _spec.loader is not None
agent_token_cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agent_token_cli)


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(app_config, "_CONFIG_PATH", cfg_path)
    app_config.invalidate_config_cache()
    yield cfg_path
    app_config.invalidate_config_cache()


class TestGenerate:
    def test_generate_prints_raw_and_persists_hash(
        self,
        isolated_config: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = agent_token_cli.main(["generate", "--label", "laptop-claude"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Token: fin_" in out
        assert "scope: read+write" in out
        # The persisted record stores hash only — raw never recoverable.
        records = agent_tokens.list_tokens()
        assert len(records) == 1
        assert records[0]["label"] == "laptop-claude"

    def test_generate_with_read_scope(
        self,
        isolated_config: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = agent_token_cli.main(["generate", "--label", "readonly", "--scope", "read"])
        assert rc == 0
        assert agent_tokens.list_tokens()[0]["scope"] == "read"

    def test_generate_rejects_blank_label(
        self,
        isolated_config: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = agent_token_cli.main(["generate", "--label", "   "])
        assert rc == 2
        assert "label is required" in capsys.readouterr().err

    def test_generate_rejects_unknown_scope(
        self,
        isolated_config: Path,
    ) -> None:
        # argparse rejects choices before our handler runs.
        with pytest.raises(SystemExit):
            agent_token_cli.main(["generate", "--label", "x", "--scope", "admin"])


class TestShow:
    def test_show_empty(self, isolated_config: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc = agent_token_cli.main(["show"])
        assert rc == 0
        assert "(no agent tokens configured)" in capsys.readouterr().out

    def test_show_lists_persisted_tokens(
        self,
        isolated_config: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        agent_tokens.add_token(label="laptop", scope="read+write")
        agent_tokens.add_token(label="phone", scope="read")
        rc = agent_token_cli.main(["show"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "laptop" in out
        assert "phone" in out
        assert "read+write" in out
        # The header columns are present.
        assert "id" in out
        assert "label" in out
        assert "scope" in out


class TestRevoke:
    def test_revoke_removes_token(
        self,
        isolated_config: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        record, _ = agent_tokens.add_token(label="t")
        rc = agent_token_cli.main(["revoke", "--id", record["id"]])
        assert rc == 0
        assert agent_tokens.list_tokens() == []
        assert f"revoked token {record['id']}" in capsys.readouterr().out

    def test_revoke_unknown_id_is_error(
        self,
        isolated_config: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        agent_tokens.add_token(label="t")
        rc = agent_token_cli.main(["revoke", "--id", "missing"])
        assert rc == 1
        assert "no token with id" in capsys.readouterr().err
        assert len(agent_tokens.list_tokens()) == 1

    def test_revoke_blank_id_rejected(
        self,
        isolated_config: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = agent_token_cli.main(["revoke", "--id", "  "])
        assert rc == 2
        assert "id is required" in capsys.readouterr().err
