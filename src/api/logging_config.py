"""Centralized logging configuration for the API."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging():
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    fmt = "%(asctime)s %(levelname)-8s %(name)s — %(message)s"
    formatter = logging.Formatter(fmt)

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)

    file_handler = RotatingFileHandler(logs_dir / "api.log", maxBytes=5_000_000, backupCount=3)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(console)
    root.addHandler(file_handler)

    # Silence noisy third-party libraries
    for name in ("botocore", "boto3", "urllib3", "s3transfer"):
        logging.getLogger(name).setLevel(logging.WARNING)
