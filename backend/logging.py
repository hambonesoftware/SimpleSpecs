"""Logging utilities for SimpleSpecs."""
from __future__ import annotations

import logging
from typing import Optional


def setup_logging(level: int = logging.INFO) -> None:
    """Configure basic logging for the application."""

    if logging.getLogger().handlers:
        return

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a logger instance, ensuring logging is configured."""

    setup_logging()
    return logging.getLogger(name)
