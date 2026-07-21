"""Tests for src/api/logging_config.py.

The module mutates the root logger and creates a `logs/` directory on the
process CWD. Tests must restore both, otherwise sibling tests using `caplog`
or the working tree's real `logs/` directory will see contamination.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from src.api.logging_config import configure_logging


@pytest.fixture
def isolated_logging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Run configure_logging() against a tmp CWD and restore root handlers."""
    monkeypatch.chdir(tmp_path)
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    saved_third_party = {name: logging.getLogger(name).level for name in ("botocore", "boto3", "urllib3", "s3transfer")}
    yield tmp_path
    # Drop handlers we added so the file handle to tmp_path/logs/api.log is
    # released before pytest deletes tmp_path.
    for h in root.handlers[:]:
        if h not in saved_handlers:
            h.close()
            root.removeHandler(h)
    root.setLevel(saved_level)
    for name, level in saved_third_party.items():
        logging.getLogger(name).setLevel(level)


class TestConfigureLogging:
    def test_creates_logs_directory(self, isolated_logging: Path):
        configure_logging()
        assert (isolated_logging / "logs").is_dir()

    def test_attaches_stream_and_file_handlers(self, isolated_logging: Path):
        configure_logging()
        root = logging.getLogger()
        assert any(isinstance(h, logging.StreamHandler) for h in root.handlers)
        assert any(isinstance(h, RotatingFileHandler) for h in root.handlers)

    def test_root_logger_at_debug(self, isolated_logging: Path):
        configure_logging()
        assert logging.getLogger().level == logging.DEBUG

    def test_third_party_loggers_silenced(self, isolated_logging: Path):
        configure_logging()
        for name in ("botocore", "boto3", "urllib3", "s3transfer"):
            assert logging.getLogger(name).level == logging.WARNING

    def test_file_handler_writes_to_api_log(self, isolated_logging: Path):
        configure_logging()
        logging.getLogger("test").info("hello")
        for h in logging.getLogger().handlers:
            if isinstance(h, RotatingFileHandler):
                h.flush()
        assert (isolated_logging / "logs" / "api.log").exists()
