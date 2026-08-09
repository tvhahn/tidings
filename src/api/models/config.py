"""Pydantic models for app configuration endpoints."""

from typing import Literal

from pydantic import BaseModel, Field

AiProvider = Literal["claude_cli", "openai", "codex", "gemini_cli", "disabled"]
# Categorization only ever spoke the OpenAI API or Codex — the CLI text
# providers (Claude Code / Gemini) don't do forced-tool categorization.
CategorizationProvider = Literal["openai", "codex", "disabled"]
# Reasoning effort is a permissive union across every provider; per-provider
# narrowing is a UI concern, and an unsupported combo surfaces as a
# provider-side error through the normal error paths. Verified support:
# OpenAI API none-xhigh, codex low-xhigh, Claude Code low-max.
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]

_TIME_24H = r"^([01]\d|2[0-3]):[0-5]\d$"


class AppConfigResponse(BaseModel):
    storage: str
    demo_mode: bool
    user_id: str
    openai_enabled: bool
    aws_available: bool
    claude_cli_available: bool
    codex_available: bool
    gemini_cli_available: bool
    chatgpt_oauth_connected: bool
    chatgpt_oauth_email: str | None
    daily_summary_provider: AiProvider = "disabled"
    daily_summary_model: str | None = None
    daily_summary_reasoning_effort: ReasoningEffort | None = None
    insights_provider: AiProvider = "disabled"
    insights_model: str | None = None
    insights_reasoning_effort: ReasoningEffort | None = None
    insights_user_memo: str | None = None
    categorization_provider: CategorizationProvider = "disabled"
    categorization_model: str | None = None
    categorization_reasoning_effort: ReasoningEffort | None = None
    document_parsing_provider: AiProvider = "disabled"
    document_parsing_model: str | None = None
    document_parsing_reasoning_effort: ReasoningEffort | None = None
    enable_daily_summaries: bool
    daily_summary_schedule_time: str = Field(default="19:00", pattern=_TIME_24H)
    ai_categorization_enabled: bool
    ai_extraction_enabled: bool
    ai_statement_parsing_enabled: bool = False
    ai_receipt_parsing_enabled: bool = False
    tax_tracking_enabled: bool = True
    s3_backup_enabled: bool = False
    s3_backup_bucket: str | None = None
    s3_backup_prefix: str | None = None
    timezone: str
    auth_bypass_for_dev: bool = False
    passwordless_acknowledged: bool = False


class AppConfigUpdateRequest(BaseModel):
    storage: str | None = None
    demo_mode: bool | None = None
    user_id: str | None = None
    daily_summary_provider: AiProvider | None = None
    daily_summary_model: str | None = None
    daily_summary_reasoning_effort: ReasoningEffort | None = None
    insights_provider: AiProvider | None = None
    insights_model: str | None = None
    insights_reasoning_effort: ReasoningEffort | None = None
    # Standing free-text context injected into every AI briefing. Capped so one
    # oversized paste can't blow the prompt budget; overflow is a 422.
    insights_user_memo: str | None = Field(default=None, max_length=2000)
    categorization_provider: CategorizationProvider | None = None
    categorization_model: str | None = None
    categorization_reasoning_effort: ReasoningEffort | None = None
    document_parsing_provider: AiProvider | None = None
    document_parsing_model: str | None = None
    document_parsing_reasoning_effort: ReasoningEffort | None = None
    enable_daily_summaries: bool | None = None
    daily_summary_schedule_time: str | None = Field(default=None, pattern=_TIME_24H)
    ai_categorization_enabled: bool | None = None
    ai_extraction_enabled: bool | None = None
    ai_statement_parsing_enabled: bool | None = None
    ai_receipt_parsing_enabled: bool | None = None
    tax_tracking_enabled: bool | None = None
    s3_backup_enabled: bool | None = None
    s3_backup_bucket: str | None = None
    s3_backup_prefix: str | None = None
    timezone: str | None = None
    auth_bypass_for_dev: bool | None = None
    passwordless_acknowledged: bool | None = None


class TestOpenAIResponse(BaseModel):
    ok: bool
    error: str | None


class TestS3BackupResponse(BaseModel):
    ok: bool
    error: str | None
    warnings: list[str]
