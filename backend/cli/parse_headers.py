"""Developer CLI for running the header parsing pipeline locally."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..logging import setup_logging
from ..services.document_pipeline import run_header_pipeline


def _configure_logging(debug: bool) -> None:
    if debug:
        setup_logging(level=logging.DEBUG)
    else:
        setup_logging()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parse a PDF and emit header JSON")
    parser.add_argument("pdf_path", type=Path, help="Path to the PDF to parse")
    parser.add_argument("--json", dest="json_path", type=Path, help="Destination for JSON output")
    parser.add_argument("--debug", action="store_true", help="Enable verbose parser logging")
    args = parser.parse_args(argv)

    _configure_logging(args.debug)
    settings = get_settings()
    result = run_header_pipeline(str(args.pdf_path), debug=args.debug)
    payload: dict[str, Any] = result.to_dict()
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    else:
        print(json.dumps(payload, indent=2))
    if args.debug:
        print("\n--- Parser Flags ---")
        print(
            json.dumps(
                {
                    "PARSER_MULTI_COLUMN": settings.PARSER_MULTI_COLUMN,
                    "HEADERS_SUPPRESS_TOC": settings.HEADERS_SUPPRESS_TOC,
                    "HEADERS_SUPPRESS_RUNNING": settings.HEADERS_SUPPRESS_RUNNING,
                    "PARSER_ENABLE_OCR": settings.PARSER_ENABLE_OCR,
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
