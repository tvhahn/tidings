"""Unit tests for shared API utilities (``src.api.utils``)."""

from src.api.utils import sanitize_filename


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
