"""Logging configuration: console (stdout) + rotating file, configured once."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging(level: str = "INFO", log_dir: str | Path = "logs") -> None:
    """Configure the root logger once. Safe to call more than once (no-op after the first)."""
    global _configured
    if _configured:
        return

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_path / "bot.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level.upper())
    root.addHandler(console_handler)
    root.addHandler(file_handler)

    # aiogram/aiohttp are chatty at INFO about every update; keep them at WARNING
    # unless the operator explicitly asked for DEBUG.
    if level.upper() != "DEBUG":
        logging.getLogger("aiohttp").setLevel(logging.WARNING)

    _configured = True
