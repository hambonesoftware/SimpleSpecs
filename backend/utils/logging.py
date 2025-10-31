from __future__ import annotations

import logging
import os
import sys

TRACE_LEVEL = 5
logging.addLevelName(TRACE_LEVEL, "TRACE")


def trace(self: logging.Logger, msg: str, *args, **kwargs) -> None:  # type: ignore[override]
    if self.isEnabledFor(TRACE_LEVEL):
        self._log(TRACE_LEVEL, msg, args, **kwargs)


logging.Logger.trace = trace  # type: ignore[attr-defined]


def configure_logging(default_level: str = "DEBUG") -> logging.Logger:
    level_name = os.getenv("HEADERS_LOG_LEVEL", default_level).upper()
    level = getattr(logging, level_name, logging.DEBUG)
    logging.basicConfig(
        level=level,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    return logging.getLogger("simplespecs")


__all__ = ["TRACE_LEVEL", "configure_logging"]
