"""Unit tests for shared API utilities (``src.api.utils``)."""

import asyncio
import io

import pytest
from fastapi import HTTPException, UploadFile

from src.api import utils as api_utils
from src.api.utils import read_upload_limited, sanitize_filename


class TestSanitizeFilename:
    """Filename hardening used by the attachments and tax routers.

    The sanitizer takes the final path component, whitelists to
    ``[A-Za-z0-9._-]``, strips leading/trailing dot-underscore runs, and
    truncates. It must never let path traversal or leading dots survive.
    """

    def test_strips_path_traversal(self) -> None:
        # Path components (incl. `../`) are dropped; only the leaf survives.
        assert sanitize_filename("../../etc/passwd") == "passwd"

    def test_strips_windows_path_segments(self) -> None:
        assert sanitize_filename("..\\..\\win") == "win"

    def test_dot_run_falls_back(self) -> None:
        # Nothing survives the leading/trailing strip -> fallback.
        assert sanitize_filename("...") == "file"

    def test_custom_fallback(self) -> None:
        assert sanitize_filename("...", fallback="unknown") == "unknown"

    def test_normal_name_unchanged(self) -> None:
        assert sanitize_filename("report.pdf") == "report.pdf"

    def test_disallowed_chars_become_underscores(self) -> None:
        assert sanitize_filename("my file@#.txt") == "my_file__.txt"

    def test_truncation_applies(self) -> None:
        assert sanitize_filename("a" * 100) == "a" * 80

    def test_truncation_respects_max_len(self) -> None:
        assert sanitize_filename("a" * 100, max_len=10) == "a" * 10

    def test_no_leading_or_trailing_dots(self) -> None:
        result = sanitize_filename(".hidden.")
        assert not result.startswith(".")
        assert not result.endswith(".")
        assert result == "hidden"


class _TrackingFile(io.BytesIO):
    """BytesIO that records the largest single read request and total bytes read."""

    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.bytes_read = 0
        self.max_request = 0

    def read(self, size: int | None = -1) -> bytes:
        self.max_request = max(self.max_request, size if size is not None and size >= 0 else len(self.getvalue()))
        chunk = super().read(size)
        self.bytes_read += len(chunk)
        return chunk


def _too_large(size: int) -> HTTPException:
    return HTTPException(status_code=413, detail=f"too large: {size}")


class TestReadUploadLimited:
    @pytest.fixture(autouse=True)
    def _small_chunks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(api_utils, "_UPLOAD_CHUNK_BYTES", 4)

    def test_returns_all_bytes_under_limit(self) -> None:
        upload = UploadFile(file=io.BytesIO(b"0123456789"))
        assert asyncio.run(read_upload_limited(upload, 10, _too_large)) == b"0123456789"

    def test_known_size_rejected_before_reading(self) -> None:
        raw = _TrackingFile(b"x" * 50)
        upload = UploadFile(file=raw, size=50)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(read_upload_limited(upload, 10, _too_large))
        # The route's own exception is raised unchanged (an HTTPException, not a response).
        assert (exc.value.status_code, exc.value.detail) == (413, "too large: 50")
        assert raw.bytes_read == 0

    def test_unknown_size_reads_in_chunks_and_reports_full_size(self) -> None:
        raw = _TrackingFile(b"x" * 50)
        upload = UploadFile(file=raw)  # size unknown → chunked count
        with pytest.raises(HTTPException) as exc:
            asyncio.run(read_upload_limited(upload, 10, _too_large))
        assert exc.value.detail == "too large: 50"
        assert raw.max_request == 4  # never a whole-body read()

    def test_exactly_at_limit_is_accepted(self) -> None:
        upload = UploadFile(file=io.BytesIO(b"x" * 12), size=12)
        assert asyncio.run(read_upload_limited(upload, 12, _too_large)) == b"x" * 12
