"""Request/response models for the data import/export endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ImportStrategy = Literal["skip", "overwrite", "keep_both"]


class ImportPreviewCounts(BaseModel):
    total: int
    new: int
    duplicates: int
    invalid: int


class ImportPreviewSample(BaseModel):
    """One row from the preview buckets, trimmed for display."""

    date: str | None = None
    amount: float | None = None
    company: str | None = None
    category: str | None = None
    reason: str | None = None  # populated for invalid rows


class ConfigPreview(BaseModel):
    """Summary of the config blobs that would be replaced on import."""

    categories_count: int | None = None
    overrides_count: int | None = None
    merchant_aliases_count: int | None = None
    budget_years_count: int | None = None


class ImportPreviewResponse(BaseModel):
    """Dry-run of an import. Call /data/import/commit with `token` to apply."""

    token: str = Field(description="Staged-import token. Commit within 15 minutes.")
    filename: str
    source_kind: str
    counts: ImportPreviewCounts
    sample_new: list[ImportPreviewSample] = []
    sample_duplicates: list[ImportPreviewSample] = []
    sample_invalid: list[ImportPreviewSample] = []
    config: ConfigPreview | None = None


class ImportCommitRequest(BaseModel):
    token: str
    strategy: ImportStrategy = "skip"
    apply_config: bool = True


class ImportResult(BaseModel):
    inserted: int
    updated: int
    skipped: int
    invalid: int
    errors: int = 0
    config_applied: bool = False
    config_details: dict[str, Any] = Field(default_factory=dict)


class S3BackupStatusResponse(BaseModel):
    """Current S3 attachment-backup config plus the last-run state metadata."""

    enabled: bool
    bucket: str | None
    prefix: str | None
    last_attempt_at: str | None
    last_success_at: str | None
    last_error: str | None
    consecutive_failures: int
    uploaded_count: int
    deleted_count: int
    objects_total: int
