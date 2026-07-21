"""Tests for daily summary API endpoints — generate, status, and retrieve."""

import asyncio
from collections.abc import Iterator
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.api.routers.daily_summaries as ds_mod
from tests.asserts import assert_ok, assert_problem
from tests.factories import make_transaction_item


@pytest.fixture(autouse=True)
def _reset_generation_state() -> Iterator[None]:
    """Reset module-level generation state between tests."""
    ds_mod._generation_state = {"status": "idle"}
    ds_mod._generation_task = None
    yield
    ds_mod._generation_state = {"status": "idle"}
    ds_mod._generation_task = None


def _item(
    day: str, hour: str = "10.30", amount: str = "42.50", txn_type: str = "purchase", **kw: Any
) -> dict[str, Any]:
    return make_transaction_item(
        DateFileName=f"2026.04.{day}_{hour}_test.eml",
        Date=f"04/{day}/2026 {hour.replace('.', ':')} PST",
        Amount=Decimal(amount),
        TransactionType=txn_type,
        **kw,
    )


class TestGetSummaries:
    @patch.object(ds_mod, "_read_saved_summaries", return_value={})
    def test_returns_empty_summaries(self, mock_read: MagicMock, api_client) -> None:
        resp = api_client.get("/api/v1/journal/summaries?month=2026-04")
        assert_ok(resp)
        data = resp.json()
        assert data["month"] == "2026-04"
        assert data["summaries"] == {}

    @patch.object(
        ds_mod,
        "_read_saved_summaries",
        return_value={"2026-04-15": "A busy day."},
    )
    def test_returns_saved_summaries(self, mock_read: MagicMock, api_client) -> None:
        resp = api_client.get("/api/v1/journal/summaries?month=2026-04")
        data = resp.json()
        assert data["summaries"]["2026-04-15"] == "A busy day."

    def test_rejects_invalid_month(self, api_client) -> None:
        resp = api_client.get("/api/v1/journal/summaries?month=bad")
        assert_problem(resp, 422)

    def test_rejects_missing_month(self, api_client) -> None:
        resp = api_client.get("/api/v1/journal/summaries")
        assert_problem(resp, 422)


class TestGetStatus:
    def test_status_returns_idle(self, api_client) -> None:
        resp = api_client.get("/api/v1/journal/summaries/status")
        assert_ok(resp)
        assert resp.json()["status"] == "idle"

    def test_status_returns_running(self, api_client) -> None:
        ds_mod._generation_state = {
            "status": "running",
            "month": "2026-04",
            "completed": 2,
            "total": 5,
        }
        resp = api_client.get("/api/v1/journal/summaries/status")
        data = resp.json()
        assert data["status"] == "running"
        assert data["completed"] == 2
        assert data["total"] == 5

    def test_status_returns_error(self, api_client) -> None:
        ds_mod._generation_state = {
            "status": "error",
            "month": "2026-04",
            "error": "Provider failed",
        }
        resp = api_client.get("/api/v1/journal/summaries/status")
        data = resp.json()
        assert data["status"] == "error"
        assert data["error"] == "Provider failed"


class TestGenerateEndpoint:
    @patch("src.api.routers.daily_summaries._run_generation", new_callable=AsyncMock)
    @patch("src.api.routers.daily_summaries._read_saved_summaries", return_value={})
    @patch("src.api.routers.daily_summaries.get_config")
    @pytest.mark.parametrize("mock_run_sync", ["daily_summaries"], indirect=True)
    def test_returns_202_and_starts_generation(
        self,
        mock_config: MagicMock,
        mock_saved: MagicMock,
        mock_run_gen: MagicMock,
        mock_run_sync: AsyncMock,
        api_client,
    ) -> None:
        mock_config.return_value = {"daily_summary_provider": "openai", "storage": "sqlite"}
        items = [_item("14"), _item("15")]
        mock_run_sync.side_effect = [items, None]  # query_month, get_targets

        resp = api_client.post(
            "/api/v1/journal/summaries/generate",
            json={"month": "2026-04"},
        )
        assert_ok(resp)
        data = resp.json()
        assert data["status"] == "running"
        assert data["dates_queued"] == 2

    @patch("src.api.routers.daily_summaries.get_config")
    @pytest.mark.parametrize("mock_run_sync", ["daily_summaries"], indirect=True)
    def test_rejects_when_disabled(self, mock_config: MagicMock, mock_run_sync: AsyncMock, api_client) -> None:
        mock_config.return_value = {"daily_summary_provider": "disabled", "storage": "sqlite"}

        resp = api_client.post(
            "/api/v1/journal/summaries/generate",
            json={"month": "2026-04"},
        )
        assert_problem(resp, 400)

    @patch("src.api.routers.daily_summaries._run_generation", new_callable=AsyncMock)
    @patch("src.api.routers.daily_summaries._read_saved_summaries", return_value={})
    @patch("src.api.routers.daily_summaries.get_config")
    @pytest.mark.parametrize("mock_run_sync", ["daily_summaries"], indirect=True)
    def test_manual_generate_ignores_daily_toggle(
        self,
        mock_config: MagicMock,
        mock_saved: MagicMock,
        mock_run_gen: MagicMock,
        mock_run_sync: AsyncMock,
        api_client,
    ) -> None:
        # Auto-generation is off, but a manual Summarize click must still run:
        # the enable_daily_summaries toggle only governs the background scheduler.
        mock_config.return_value = {
            "daily_summary_provider": "codex",
            "enable_daily_summaries": False,
            "storage": "sqlite",
        }
        items = [_item("14"), _item("15")]
        mock_run_sync.side_effect = [items, None]  # query_month, get_targets

        resp = api_client.post(
            "/api/v1/journal/summaries/generate",
            json={"month": "2026-04"},
        )
        assert_ok(resp)
        assert resp.json()["status"] == "running"

    def test_rejects_concurrent_generation(self, api_client) -> None:
        ds_mod._generation_state = {"status": "running", "month": "2026-04"}

        resp = api_client.post(
            "/api/v1/journal/summaries/generate",
            json={"month": "2026-04"},
        )
        assert_problem(resp, 409)

    def test_rejects_invalid_month(self, api_client) -> None:
        resp = api_client.post(
            "/api/v1/journal/summaries/generate",
            json={"month": "bad-format"},
        )
        assert_problem(resp, 422)

    @patch("src.api.routers.daily_summaries._run_generation", new_callable=AsyncMock)
    @patch("src.api.routers.daily_summaries.get_config")
    @pytest.mark.parametrize("mock_run_sync", ["daily_summaries"], indirect=True)
    def test_empty_month_returns_idle(
        self, mock_config: MagicMock, mock_run_gen: MagicMock, mock_run_sync: AsyncMock, api_client
    ) -> None:
        mock_config.return_value = {"daily_summary_provider": "openai", "storage": "sqlite"}
        mock_run_sync.side_effect = [[], None]

        resp = api_client.post(
            "/api/v1/journal/summaries/generate",
            json={"month": "2026-04"},
        )
        assert_ok(resp)
        assert resp.json()["status"] == "idle"
        assert resp.json()["dates_queued"] == 0

    @patch("src.api.routers.daily_summaries._run_generation", new_callable=AsyncMock)
    @patch("src.api.routers.daily_summaries._read_saved_summaries")
    @patch("src.api.routers.daily_summaries.get_config")
    @pytest.mark.parametrize("mock_run_sync", ["daily_summaries"], indirect=True)
    def test_skips_already_saved_dates(
        self,
        mock_config: MagicMock,
        mock_saved: MagicMock,
        mock_run_gen: MagicMock,
        mock_run_sync: AsyncMock,
        api_client,
    ) -> None:
        mock_config.return_value = {"daily_summary_provider": "openai", "storage": "sqlite"}
        items = [_item("14"), _item("15")]
        mock_run_sync.side_effect = [items, None]
        mock_saved.return_value = {"2026-04-14": "Already done."}

        resp = api_client.post(
            "/api/v1/journal/summaries/generate",
            json={"month": "2026-04"},
        )
        assert_ok(resp)
        assert resp.json()["dates_queued"] == 1

    @patch("src.api.routers.daily_summaries._run_generation", new_callable=AsyncMock)
    @patch("src.api.routers.daily_summaries._read_saved_summaries")
    @patch("src.api.routers.daily_summaries.get_config")
    @pytest.mark.parametrize("mock_run_sync", ["daily_summaries"], indirect=True)
    def test_force_regenerates_saved_dates(
        self,
        mock_config: MagicMock,
        mock_saved: MagicMock,
        mock_run_gen: MagicMock,
        mock_run_sync: AsyncMock,
        api_client,
    ) -> None:
        mock_config.return_value = {"daily_summary_provider": "openai", "storage": "sqlite"}
        items = [_item("14")]
        mock_run_sync.side_effect = [items, None]
        mock_saved.return_value = {"2026-04-14": "Already done."}

        resp = api_client.post(
            "/api/v1/journal/summaries/generate",
            json={"month": "2026-04", "dates": ["2026-04-14"], "force": True},
        )
        assert_ok(resp)
        assert resp.json()["dates_queued"] == 1

    @patch("src.api.routers.daily_summaries._run_generation", new_callable=AsyncMock)
    @patch("src.api.routers.daily_summaries._read_saved_summaries")
    @patch("src.api.routers.daily_summaries.get_config")
    @pytest.mark.parametrize("mock_run_sync", ["daily_summaries"], indirect=True)
    def test_all_saved_returns_idle(
        self,
        mock_config: MagicMock,
        mock_saved: MagicMock,
        mock_run_gen: MagicMock,
        mock_run_sync: AsyncMock,
        api_client,
    ) -> None:
        mock_config.return_value = {"daily_summary_provider": "openai", "storage": "sqlite"}
        items = [_item("14")]
        mock_run_sync.side_effect = [items, None]
        mock_saved.return_value = {"2026-04-14": "Already done."}

        resp = api_client.post(
            "/api/v1/journal/summaries/generate",
            json={"month": "2026-04"},
        )
        assert_ok(resp)
        assert resp.json()["dates_queued"] == 0

    @patch("src.api.routers.daily_summaries._run_generation", new_callable=AsyncMock)
    @patch("src.api.routers.daily_summaries._read_saved_summaries", return_value={})
    @patch("src.api.routers.daily_summaries.gather_insights_context", new_callable=AsyncMock)
    @patch("src.api.routers.daily_summaries.get_config")
    @pytest.mark.parametrize("mock_run_sync", ["daily_summaries"], indirect=True)
    def test_insights_context_failure_falls_back_to_thin_context(
        self,
        mock_config: MagicMock,
        mock_insights: AsyncMock,
        mock_saved: MagicMock,
        mock_run_gen: MagicMock,
        mock_run_sync: AsyncMock,
        api_client,
    ) -> None:
        """A raising gather_insights_context is best-effort — generation still starts."""
        mock_config.return_value = {"daily_summary_provider": "openai", "storage": "sqlite"}
        mock_insights.side_effect = RuntimeError("insights boom")
        mock_run_sync.side_effect = [[_item("14")], None]

        resp = api_client.post(
            "/api/v1/journal/summaries/generate",
            json={"month": "2026-04"},
        )
        assert_ok(resp)
        assert resp.json()["status"] == "running"


class TestRunGenerationInternals:
    """Direct tests for the background _run_generation task and _save_summary,
    which the endpoint tests deliberately mock out."""

    def test_provider_unavailable_sets_error_state(self) -> None:
        with patch("src.finance.summary_provider.create_summary_provider", return_value=None):
            asyncio.run(ds_mod._run_generation("2026-04", [{"date": "2026-04-15"}], "openai"))
        assert ds_mod._generation_state["status"] == "error"
        assert "not available" in ds_mod._generation_state["error"]

    def test_success_saves_each_day_and_warns_on_long_summary(self, monkeypatch) -> None:
        saved: list[tuple[str, str, str]] = []
        monkeypatch.setattr(ds_mod, "_save_summary", lambda m, d, t: saved.append((m, d, t)))
        # Force the word-count warning branch regardless of the real threshold.
        monkeypatch.setattr(ds_mod, "_WORD_COUNT_WARN_THRESHOLD", 3)

        async def fake_generate(day_contexts, on_complete):
            on_complete("2026-04-15", "one two three four five")  # 5 words > 3 → warns

        provider = MagicMock()
        provider.generate_summaries = AsyncMock(side_effect=fake_generate)
        with patch("src.finance.summary_provider.create_summary_provider", return_value=provider):
            asyncio.run(ds_mod._run_generation("2026-04", [{"date": "2026-04-15"}], "openai"))

        assert saved == [("2026-04", "2026-04-15", "one two three four five")]
        assert ds_mod._generation_state == {"status": "idle"}

    def test_generation_exception_sets_error_state(self) -> None:
        provider = MagicMock()
        provider.generate_summaries = AsyncMock(side_effect=RuntimeError("provider boom"))
        with patch("src.finance.summary_provider.create_summary_provider", return_value=provider):
            asyncio.run(ds_mod._run_generation("2026-04", [{"date": "2026-04-15"}], "openai"))
        assert ds_mod._generation_state["status"] == "error"
        assert "provider boom" in ds_mod._generation_state["error"]


class TestSaveSummary:
    def test_writes_day_file_named_by_day_of_month(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(ds_mod, "_summaries_dir", lambda month: tmp_path)
        ds_mod._save_summary("2026-04", "2026-04-15", "A calm day.")
        assert (tmp_path / "15.txt").read_text() == "A calm day."
