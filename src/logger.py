"""
Shared logger factory for the Canon Engine.

Usage in any module:
    from logger import get_logger
    log = get_logger(__name__)
    log.info("Doing something useful")
    log.warning("Something looks off")

Log level is INFO by default.
Set environment variable LOG_LEVEL=DEBUG to see debug output.
Set LOG_FILE=logs/canon.log to also write to a file.
"""
from __future__ import annotations

import logging
import os
import sys


def get_logger(name: str) -> logging.Logger:
    """
    Return a logger for the given module name.
    Configures a StreamHandler on first call for each name.
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # already configured

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Console handler
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(level)
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)

    # Optional file handler
    log_file = os.environ.get("LOG_FILE", "")
    if log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)

    # Don't propagate to root logger (avoids duplicate messages)
    logger.propagate = False
    return logger
