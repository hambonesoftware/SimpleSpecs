#!/usr/bin/env python3
"""Development launcher for the unified SimpleSpecs application."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import uvicorn

BACKEND_APP = "backend.main:app"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 7600
PROJECT_ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    """Parse command line arguments for the launcher script."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host",
        default=os.getenv("HOST", DEFAULT_HOST),
        help="Host interface for the SimpleSpecs server.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PORT", DEFAULT_PORT)),
        help="Port for the SimpleSpecs server.",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("LOG_LEVEL", "info"),
        help="Log level passed to Uvicorn.",
    )
    parser.add_argument(
        "--reload",
        dest="reload",
        action="store_true",
        default=os.getenv("RELOAD", "true").lower() not in {"0", "false", "no"},
        help="Enable autoreload (default: on).",
    )
    parser.add_argument(
        "--no-reload",
        dest="reload",
        action="store_false",
        help="Disable autoreload.",
    )
    return parser.parse_args()


def main() -> None:
    """Launch a single Uvicorn server that serves API and frontend."""

    args = parse_args()
    sys.path.insert(0, str(PROJECT_ROOT))

    reload_dirs: list[str] | None = None
    if args.reload:
        reload_dirs = [
            str(PROJECT_ROOT / "backend"),
            str(PROJECT_ROOT / "frontend"),
        ]

    uvicorn.run(
        BACKEND_APP,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        reload=args.reload,
        reload_dirs=reload_dirs,
    )


if __name__ == "__main__":
    main()
