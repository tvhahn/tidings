"""Tests for the insights background generation + polling endpoints."""

import asyncio
import json
from collections.abc import Iterator
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

import src.api.routers.insights as insights_mod
from src.finance import app_timezone
from tests.asserts import assert_ok, assert_problem


@pytest.fixture(autouse=True)
def _reset_generation_state() -> Iterator[None]:
    """Reset module-level generation state between tests."""
    insights_mod._generation_state = {"status": "idle"}
    insights_mod._generation_task = None
    yield
    insights_mod._generation_state = {"status": "idle"}
    insights_mod._generation_task = None


class TestGenerateEndpoint:
    @patch("src.api.routers.insights._run_generation", new_callable=AsyncMock)
    def test_generate_returns_202(self, mock_run: AsyncMock, api_client) -> None:
        resp = api_client.post("/api/v1/insights/generate?month=2026-02")
        assert_ok(resp)
        body = resp.json()
        assert body["status"] == "running"
        assert body["month"] == "2026-02"

    @patch("src.api.routers.insights._run_generation", new_callable=AsyncMock)
    def test_started_at_carries_app_timezone_offset(self, mock_run: AsyncMock, api_client, freeze_clock) -> None:
        # started_at is stamped via now_local() (app timezone), not naive
        # datetime.now(). Frozen at a Pacific winter instant, the ISO string must
        # carry the -08:00 offset rather than a bare/UTC timestamp.
        freeze_clock(  # now_local() reads its clock from app_timezone
            app_timezone,
            at=datetime(2026, 12, 31, 16, 30, tzinfo=ZoneInfo("America/Los_Angeles")),
        )
        resp = api_client.post("/api/v1/insights/generate?month=2026-02")
        assert_ok(resp)
        started_at = insights_mod._generation_state["started_at"]
        assert started_at == "2026-12-31T16:30:00-08:00"
        assert started_at.endswith("-08:00")

    @patch("src.api.routers.insights._run_generation", new_callable=AsyncMock)
    def test_generate_rejects_concurrent(self, mock_run: AsyncMock, api_client) -> None:
        insights_mod._generation_state = {"status": "running", "month": "2026-01"}

        resp = api_client.post("/api/v1/insights/generate?month=2026-02")
        assert_problem(resp, 409)

    def test_generate_rejects_invalid_month(self, api_client) -> None:
        resp = api_client.post("/api/v1/insights/generate?month=bad")
        assert_problem(resp, 422)

    def test_generate_rejects_missing_month(self, api_client) -> None:
        resp = api_client.post("/api/v1/insights/generate")
        assert_problem(resp, 422)


class TestStatusEndpoint:
    def test_status_returns_idle(self, api_client) -> None:
        resp = api_client.get("/api/v1/insights/status")
        assert_ok(resp)
        body = resp.json()
        assert body["status"] == "idle"
        # Optional fields are explicitly null when idle (typed response model)
        assert body["month"] is None
        assert body["error"] is None

    def test_status_returns_running(self, api_client) -> None:
        insights_mod._generation_state = {
            "status": "running",
            "month": "2026-02",
            "started_at": "2026-02-27T10:00:00",
        }
        resp = api_client.get("/api/v1/insights/status")
        body = resp.json()
        assert body["status"] == "running"
        assert body["month"] == "2026-02"

    def test_status_returns_error(self, api_client) -> None:
        insights_mod._generation_state = {
            "status": "error",
            "month": "2026-02",
            "error": "Claude CLI failed",
        }
        resp = api_client.get("/api/v1/insights/status")
        body = resp.json()
        assert body["status"] == "error"
        assert body["error"] == "Claude CLI failed"


class TestContextEndpoint:
    @patch("src.api.routers.insights.gather_insights_context")
    def test_context_returns_gathered_dict(self, mock_gather: MagicMock, api_client) -> None:
        mock_gather.return_value = {
            "month": "2026-02",
            "current_month": {"total_spending": 1234.5},
            "previous_month": {"total_spending": 1000.0},
            "delta": {"amount": 234.5, "percent": 23.45},
            "trend": [],
            "budget": None,
            "historical_averages": {},
            "category_deltas": [],
            "anomalies": [],
            "commented_transactions": [],
            "generated_at": "2026-02-27T10:00:00",
        }
        resp = api_client.get("/api/v1/insights/context?month=2026-02")
        assert_ok(resp)
        body = resp.json()
        assert body["month"] == "2026-02"
        assert body["current_month"]["total_spending"] == 1234.5
        # gather_insights_context should receive the injected services
        mock_gather.assert_called_once()
        args, kwargs = mock_gather.call_args
        assert args[0] == "2026-02"
        assert "spending_summary" in kwargs
        assert "budget_service" in kwargs

    def test_context_rejects_bad_month_format(self, api_client) -> None:
        resp = api_client.get("/api/v1/insights/context?month=not-a-month")
        assert_problem(resp, 422)
        assert resp.json()["code"] == "VALIDATION_ERROR"


class TestRunGeneration:
    @patch(
        "src.api.routers.insights.get_config",
        return_value={"insights_provider": "claude_cli"},
    )
    @patch("src.api.routers.insights.run_cli_provider", new_callable=AsyncMock)
    @pytest.mark.parametrize("mock_run_sync", ["insights"], indirect=True)
    def test_error_when_cli_provider_fails(
        self,
        mock_cli: AsyncMock,
        _mock_config: MagicMock,
        mock_run_sync: AsyncMock,
    ) -> None:
        mock_run_sync.return_value = {}
        mock_cli.side_effect = RuntimeError("Claude Code not found in PATH")

        asyncio.new_event_loop().run_until_complete(insights_mod._run_generation("2026-02", MagicMock(), MagicMock()))

        assert insights_mod._generation_state["status"] == "error"
        assert "Claude Code not found" in insights_mod._generation_state["error"]

    @patch(
        "src.api.routers.insights.get_config",
        return_value={"insights_provider": "disabled"},
    )
    @pytest.mark.parametrize("mock_run_sync", ["insights"], indirect=True)
    def test_error_when_provider_disabled(
        self,
        _mock_config: MagicMock,
        mock_run_sync: AsyncMock,
    ) -> None:
        mock_run_sync.return_value = {}

        asyncio.new_event_loop().run_until_complete(insights_mod._run_generation("2026-02", MagicMock(), MagicMock()))

        assert insights_mod._generation_state["status"] == "error"
        assert "No insights provider is configured" in insights_mod._generation_state["error"]

    @patch(
        "src.api.routers.insights.get_config",
        return_value={"insights_provider": "openai", "insights_model": "gpt-5.6-luna"},
    )
    @patch("src.api.routers.insights._run_openai_briefing", new_callable=AsyncMock)
    @pytest.mark.parametrize("mock_run_sync", ["insights"], indirect=True)
    def test_openai_provider_happy_path(
        self,
        mock_openai: AsyncMock,
        _mock_config: MagicMock,
        mock_run_sync: AsyncMock,
    ) -> None:
        mock_run_sync.return_value = {}
        mock_openai.return_value = "## The month in brief\n" + "OpenAI-generated briefing. " * 20

        with patch("src.api.routers.insights.Path") as mock_path_cls:
            real_path = __import__("pathlib").Path

            def path_side_effect(arg: Any) -> Any:
                p = real_path(arg)
                if str(arg).startswith("data/insights"):
                    mock_dir = MagicMock()
                    mock_dir.mkdir = MagicMock()
                    mock_dir.__truediv__ = lambda self, name: MagicMock(write_text=MagicMock())
                    return mock_dir
                return p

            mock_path_cls.side_effect = path_side_effect

            asyncio.new_event_loop().run_until_complete(
                insights_mod._run_generation("2026-02", MagicMock(), MagicMock())
            )

        # The openai path is used (not a CLI), threading the configured model.
        assert mock_openai.call_args.args[1] == "gpt-5.6-luna"
        assert insights_mod._generation_state["status"] == "idle"

    @patch(
        "src.api.routers.insights.get_config",
        return_value={"insights_provider": "openai"},
    )
    @pytest.mark.parametrize("mock_run_sync", ["insights"], indirect=True)
    def test_openai_missing_key_sets_error(
        self,
        _mock_config: MagicMock,
        mock_run_sync: AsyncMock,
    ) -> None:
        mock_run_sync.return_value = {}
        # No OpenAI key configured → the openai briefing helper raises, surfaced
        # as an "Analysis failed" error state.
        with patch(
            "src.finance.secrets.get_openai_api_key",
            side_effect=RuntimeError("OpenAI API key not set"),
        ):
            asyncio.new_event_loop().run_until_complete(
                insights_mod._run_generation("2026-02", MagicMock(), MagicMock())
            )

        assert insights_mod._generation_state["status"] == "error"
        assert "no API key is configured" in insights_mod._generation_state["error"]

    @patch(
        "src.api.routers.insights.get_config",
        return_value={"insights_provider": "claude_cli"},
    )
    @patch("src.api.routers.insights.run_cli_provider", new_callable=AsyncMock)
    @pytest.mark.parametrize("mock_run_sync", ["insights"], indirect=True)
    def test_generate_completes_successfully(
        self,
        mock_cli: AsyncMock,
        _mock_config: MagicMock,
        mock_run_sync: AsyncMock,
    ) -> None:
        mock_run_sync.return_value = {}
        mock_cli.return_value = "## The month in brief\n" + "Spending briefing. " * 20

        with patch("src.api.routers.insights.Path") as mock_path_cls:
            real_path = __import__("pathlib").Path

            def path_side_effect(arg: Any) -> Any:
                p = real_path(arg)
                if str(arg).startswith("data/insights"):
                    mock_dir = MagicMock()
                    mock_dir.mkdir = MagicMock()
                    mock_dir.__truediv__ = lambda self, name: MagicMock(write_text=MagicMock())
                    return mock_dir
                return p

            mock_path_cls.side_effect = path_side_effect

            asyncio.new_event_loop().run_until_complete(
                insights_mod._run_generation("2026-02", MagicMock(), MagicMock())
            )

        assert insights_mod._generation_state["status"] == "idle"

    @patch(
        "src.api.routers.insights.get_config",
        return_value={"insights_provider": "codex"},
    )
    @patch("src.api.routers.insights.run_cli_provider", new_callable=AsyncMock)
    @pytest.mark.parametrize("mock_run_sync", ["insights"], indirect=True)
    def test_codex_provider_path(
        self,
        mock_cli: AsyncMock,
        _mock_config: MagicMock,
        mock_run_sync: AsyncMock,
    ) -> None:
        mock_run_sync.return_value = {}
        mock_cli.return_value = "## The month in brief\n" + "Codex-generated briefing. " * 20

        with patch("src.api.routers.insights.Path") as mock_path_cls:
            real_path = __import__("pathlib").Path

            def path_side_effect(arg: Any) -> Any:
                p = real_path(arg)
                if str(arg).startswith("data/insights"):
                    mock_dir = MagicMock()
                    mock_dir.mkdir = MagicMock()
                    mock_dir.__truediv__ = lambda self, name: MagicMock(write_text=MagicMock())
                    return mock_dir
                return p

            mock_path_cls.side_effect = path_side_effect

            asyncio.new_event_loop().run_until_complete(
                insights_mod._run_generation("2026-02", MagicMock(), MagicMock())
            )

        # run_cli_provider is called with "codex", not "claude_cli"
        assert mock_cli.call_args[0][0] == "codex"
        assert insights_mod._generation_state["status"] == "idle"

    @patch(
        "src.api.routers.insights.get_config",
        return_value={"insights_provider": "claude_cli"},
    )
    @patch("src.api.routers.insights.run_cli_provider", new_callable=AsyncMock)
    @pytest.mark.parametrize("mock_run_sync", ["insights"], indirect=True)
    def test_cli_failure_sets_error(
        self,
        mock_cli: AsyncMock,
        _mock_config: MagicMock,
        mock_run_sync: AsyncMock,
    ) -> None:
        mock_run_sync.return_value = {}
        mock_cli.side_effect = RuntimeError("Claude Code error: something went wrong")

        asyncio.new_event_loop().run_until_complete(insights_mod._run_generation("2026-02", MagicMock(), MagicMock()))

        assert insights_mod._generation_state["status"] == "error"
        assert "Analysis failed" in insights_mod._generation_state["error"]

    @pytest.mark.parametrize("mock_run_sync", ["insights"], indirect=True)
    def test_exception_sets_error(self, mock_run_sync: AsyncMock) -> None:
        mock_run_sync.side_effect = RuntimeError("data gathering failed")

        ss = MagicMock()
        bs = MagicMock()

        asyncio.new_event_loop().run_until_complete(insights_mod._run_generation("2026-02", ss, bs))

        assert insights_mod._generation_state["status"] == "error"
        assert "data gathering failed" in insights_mod._generation_state["error"]


class TestSavedInsightsValidation:
    def test_list_rejects_invalid_month(self, api_client) -> None:
        resp = api_client.get("/api/v1/insights/saved?month=bad")
        assert_problem(resp, 422)

    def test_get_rejects_invalid_id(self, api_client) -> None:
        resp = api_client.get("/api/v1/insights/saved/invalid-id?month=2026-02")
        assert_problem(resp, 404)

    def test_get_returns_404_for_missing(self, api_client) -> None:
        resp = api_client.get("/api/v1/insights/saved/20260201T120000?month=2026-02")
        assert_problem(resp, 404)

    def test_list_returns_empty_for_no_dir(self, api_client) -> None:
        resp = api_client.get("/api/v1/insights/saved?month=1999-01")
        assert_ok(resp)
        assert resp.json() == {"items": [], "count": 0}


class TestBriefingPromptVoice:
    """Cheap drift guard: the briefing prompt must carry the on-brand section
    headers and stay clear of the off-brand analyst register it was rewritten
    away from (see docs/brand/voice.md)."""

    PROMPT = insights_mod.BRIEFING_PROMPT

    def test_has_new_section_headers(self) -> None:
        for header in (
            "## The month in brief",
            "## What changed",
            "## Where the month went",
            "## Worth attention",
            "## Your notes",
            "## Looking ahead",
        ):
            assert header in self.PROMPT, f"missing section header: {header}"

    def test_drops_off_brand_section_and_register(self) -> None:
        # "Alerts" was the alarmist section header; "the user" was the third-person
        # register — both are what the rewrite removed. Neither should return.
        assert "Alerts" not in self.PROMPT
        assert "the user" not in self.PROMPT

    def test_keeps_interpolation_contract(self) -> None:
        assert "{month}" in self.PROMPT
        assert "{context_data}" in self.PROMPT

    def test_keeps_no_arithmetic_and_adjusted_projection_rules(self) -> None:
        assert "pace.ceiling.projected_adjusted" in self.PROMPT
        assert "verbatim" in self.PROMPT


def _make_chat_response(content: str | None) -> MagicMock:
    """Build a mock OpenAI chat response with ``choices[0].message.content``."""
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock(name="chat_response")
    response.choices = [choice]
    return response


class TestRunOpenaiBriefing:
    """Direct tests for the module-level ``_run_openai_briefing`` helper."""

    def test_missing_key_raises(self) -> None:
        with (
            patch(
                "src.finance.secrets.get_openai_api_key",
                side_effect=RuntimeError("OpenAI API key not set"),
            ),
            pytest.raises(RuntimeError, match="no API key is configured"),
        ):
            asyncio.run(insights_mod._run_openai_briefing("prompt", None, None))

    def test_none_response_raises_with_last_error(self) -> None:
        client = MagicMock(name="openai_client")
        client.chat.return_value = None
        client.last_error = "connection refused"
        with (
            patch("src.finance.secrets.get_openai_api_key", return_value="sk-test"),
            patch("src.finance.openai_client.OpenAIClient", return_value=client) as ctor,
            pytest.raises(RuntimeError, match="The OpenAI request failed: connection refused"),
        ):
            asyncio.run(insights_mod._run_openai_briefing("prompt", "gpt-x", "high"))
        assert ctor.call_args.kwargs["model"] == "gpt-x"

    def test_empty_content_raises(self) -> None:
        client = MagicMock(name="openai_client")
        client.chat.return_value = _make_chat_response("")
        with (
            patch("src.finance.secrets.get_openai_api_key", return_value="sk-test"),
            patch("src.finance.openai_client.OpenAIClient", return_value=client),
            pytest.raises(RuntimeError, match="The OpenAI reply was empty"),
        ):
            asyncio.run(insights_mod._run_openai_briefing("prompt", None, None))

    def test_success_returns_content(self) -> None:
        client = MagicMock(name="openai_client")
        client.chat.return_value = _make_chat_response("## briefing body")
        with (
            patch("src.finance.secrets.get_openai_api_key", return_value="sk-test"),
            patch("src.finance.openai_client.OpenAIClient", return_value=client),
        ):
            result = asyncio.run(insights_mod._run_openai_briefing("the prompt", None, "medium"))
        assert result == "## briefing body"
        # The prompt is threaded as the single user message and the reasoning
        # effort is passed through to chat().
        assert client.chat.call_args.args[0] == [{"role": "user", "content": "the prompt"}]
        assert client.chat.call_args.kwargs["reasoning_effort"] == "medium"


class TestRunBriefingProvider:
    """The provider dispatch resolves ``_run_openai_briefing`` / ``run_cli_provider``
    from module globals at call time."""

    def test_openai_dispatch(self) -> None:
        with (
            patch("src.api.routers.insights._run_openai_briefing", new_callable=AsyncMock) as m_openai,
            patch("src.api.routers.insights.run_cli_provider", new_callable=AsyncMock) as m_cli,
        ):
            m_openai.return_value = "openai briefing"
            result = asyncio.run(
                insights_mod.run_briefing_provider("openai", "prompt", model="gpt-x", reasoning_effort="high")
            )
        assert result == "openai briefing"
        m_openai.assert_awaited_once_with("prompt", "gpt-x", "high")
        m_cli.assert_not_awaited()

    def test_cli_dispatch(self) -> None:
        with (
            patch("src.api.routers.insights._run_openai_briefing", new_callable=AsyncMock) as m_openai,
            patch("src.api.routers.insights.run_cli_provider", new_callable=AsyncMock) as m_cli,
        ):
            m_cli.return_value = "cli briefing"
            result = asyncio.run(
                insights_mod.run_briefing_provider(
                    "claude_cli", "prompt", model=None, reasoning_effort=None, timeout=90
                )
            )
        assert result == "cli briefing"
        m_cli.assert_awaited_once_with("claude_cli", "prompt", timeout=90, model=None, reasoning_effort=None)
        m_openai.assert_not_awaited()


class TestValidateAndPersistBriefing:
    """Direct tests for the figure-validation sidecar writer."""

    def test_bad_context_json_returns_none_and_writes_no_sidecar(self, tmp_path) -> None:
        result = insights_mod.validate_and_persist_briefing(
            "## briefing", "not valid json{", tmp_path, "2026-02-01_10-00-00"
        )
        assert result is None
        assert list(tmp_path.glob("*.validation.json")) == []

    def test_all_figures_matched_writes_ok_sidecar(self, tmp_path) -> None:
        # A briefing with no dollar/percent figures has nothing to reconcile, so
        # the verdict is ok=True and the sidecar records zero figures.
        markdown = "## The month in brief\nSpending held steady with no notable movements."
        context_json = json.dumps({"month": "2026-02", "current_month": {"total_spending": 0}})
        ts = "2026-02-01_10-00-00"

        result = insights_mod.validate_and_persist_briefing(markdown, context_json, tmp_path, ts)

        assert result is True
        sidecar = tmp_path / f"{ts}.validation.json"
        assert sidecar.is_file()
        payload = json.loads(sidecar.read_text())
        assert payload["ok"] is True
        assert payload["summary"]["total"] == 0

    def test_unmatched_figure_returns_false_and_writes_sidecar(self, tmp_path) -> None:
        # A dollar figure absent from the context cannot be traced → ok=False,
        # and the sidecar lists the offending figure.
        markdown = "## The month in brief\nYou spent $9,999.99 on groceries this month."
        context_json = json.dumps({"month": "2026-02", "current_month": {"total_spending": 12.34}})
        ts = "2026-02-01_11-00-00"

        result = insights_mod.validate_and_persist_briefing(markdown, context_json, tmp_path, ts)

        assert result is False
        payload = json.loads((tmp_path / f"{ts}.validation.json").read_text())
        assert payload["ok"] is False
        assert payload["summary"]["unmatched"] >= 1
        assert any(fig["raw"] == "$9,999.99" for fig in payload["figures"])
