"""Logging configuration for fx-hybrid-engine."""
from __future__ import annotations

import logging
import sys


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger with a clean format and pytest-safe stream binding."""
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    stream = getattr(sys, "__stdout__", None) or sys.stdout
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:  # noqa: BLE001
            continue
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter(fmt))
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
