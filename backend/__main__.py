"""Command-line entrypoint for running the SimpleSpecs backend."""

from __future__ import annotations

import uvicorn

from .config import get_settings


def main() -> None:
    """Launch the FastAPI application using configured host/port/log level."""

    settings = get_settings()
    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
