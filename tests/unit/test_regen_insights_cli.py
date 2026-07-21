"""Unit tests for the regen_insights eval CLI — pure parts + a mocked run.

Prompt assembly, section scan, and report formatting are pure and tested
directly. ``regen_month`` is exercised with the context gather and the provider
call mocked, so nothing hits a real DB or an LLM.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from dev.cli import regen_insights as cli
from src.finance.briefing_validator import validate_briefing


class TestPureHelpers:
    def test_assemble_prompt_embeds_context_and_month(self) -> None:
        prompt = cli.assemble_prompt("2026-05", '{"month": "2026-05"}')
        assert "2026-05" in prompt
        assert '{"month": "2026-05"}' in prompt
        # The prompt is the router's canonical BRIEFING_PROMPT.
        assert "spending briefing" in prompt.lower()

    def test_find_sections(self) -> None:
        md = "## The month in brief\ntext\n## What changed\n- a\n### sub\n## Looking ahead\n"
        assert cli.find_sections(md) == ["The month in brief", "What changed", "Looking ahead"]

    def test_word_count(self) -> None:
        assert cli.word_count("one two three") == 3
        assert cli.word_count("") == 0


class TestFormatReport:
    def test_dry_run_report_skips_provider_lines(self) -> None:
        report = cli.MonthReport(month="2026-05", dry_run=True, context_path="scratch/ctx.json", prompt_chars=12345)
        out = cli.format_report(report)
        assert "2026-05" in out
        assert "12,345 chars" in out
        assert "provider call skipped" in out
        assert "duration" not in out

    def test_generation_report_lists_unmatched(self) -> None:
        report = cli.MonthReport(
            month="2026-05",
            dry_run=False,
            context_path="scratch/ctx.json",
            prompt_chars=1000,
            provider="claude_cli",
            duration_s=31.4,
            words=420,
            sections=["The month in brief", "What changed"],
            matched=38,
            total_figures=40,
            unmatched_figures=[("$9,999", "an invented $9,999 appears here")],
            previous_path="data/insights/2026-05/old.md",
            new_path="data/insights/2026-05/new.md",
        )
        out = cli.format_report(report)
        assert "claude_cli" in out
        assert "31.4s" in out
        assert "38/40 matched" in out
        assert "1 not in context" in out
        assert "$9,999" in out
        assert "data/insights/2026-05/old.md" in out
        assert "data/insights/2026-05/new.md" in out

    def test_generation_report_ok_when_all_matched(self) -> None:
        report = cli.MonthReport(
            month="2026-05",
            dry_run=False,
            context_path="scratch/ctx.json",
            prompt_chars=1000,
            provider="openai",
            matched=5,
            total_figures=5,
        )
        out = cli.format_report(report)
        assert "5/5 matched — all trace to context" in out


class TestBuildGenerationReport:
    def test_projects_validation_result(self) -> None:
        ctx = {"total": 12480.09}
        md = "## The month in brief\nYou spent $12,480 and a fake $9,999."
        result = validate_briefing(md, ctx)
        report = cli.build_generation_report(
            month="2026-05",
            context_path="scratch/ctx.json",
            prompt="prompt body",
            provider="openai",
            duration_s=2.0,
            markdown=md,
            result=result,
            previous_path=None,
            new_path="data/insights/2026-05/new.md",
        )
        assert report.total_figures == 2
        assert report.matched == 1
        assert report.sections == ["The month in brief"]
        assert [raw for raw, _ in report.unmatched_figures] == ["$9,999"]


class TestRegenMonthMocked:
    def test_dry_run_gathers_and_skips_provider(self, tmp_path) -> None:
        context = {"month": "2026-05", "current_month": {"total_spending": 100.0}}

        def fake_gather(month, output_path=None, **kwargs):
            from pathlib import Path

            Path(output_path).write_text(json.dumps(context))
            return context

        with (
            patch.object(cli, "gather_context_to_file", side_effect=fake_gather),
            patch.object(cli, "run_briefing_provider") as mock_provider,
        ):
            report = cli.regen_month("2026-05", dry_run=True)

        mock_provider.assert_not_called()
        assert report.dry_run is True
        assert report.prompt_chars > 0

    def test_full_run_saves_md_and_sidecar(self, tmp_path, monkeypatch) -> None:
        context = {"month": "2026-05", "current_month": {"total_spending": 12480.09}}
        markdown = "## The month in brief\n" + "You spent $12,480. " * 15

        def fake_gather(month, output_path=None, **kwargs):
            from pathlib import Path

            Path(output_path).write_text(json.dumps(context))
            return context

        async def fake_provider(provider, prompt, **kwargs):
            return markdown

        monkeypatch.chdir(tmp_path)  # data/insights written under the tmp cwd
        with (
            patch.object(cli, "gather_context_to_file", side_effect=fake_gather),
            patch.object(cli, "get_config", return_value={"insights_provider": "openai"}),
            patch.object(cli, "run_briefing_provider", side_effect=fake_provider),
        ):
            report = cli.regen_month("2026-05", dry_run=False)

        assert report.provider == "openai"
        assert report.new_path is not None
        md_file = tmp_path / report.new_path
        assert md_file.is_file()
        sidecar = md_file.with_name(f"{md_file.stem}.validation.json")
        assert sidecar.is_file()
        payload = json.loads(sidecar.read_text())
        assert payload["ok"] is True  # $12,480 traces to 12480.09
        assert report.matched == report.total_figures
