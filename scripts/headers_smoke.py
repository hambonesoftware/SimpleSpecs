"""CLI helper to run the hardened headers extractor on a local PDF."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from backend.config import get_settings
from backend.headers.extract_headers import HeadersConfig, extract_headers
from backend.services.pdf_native import parse_pdf


def _page_texts(parse_result) -> list[str]:
    pages: list[str] = []
    for page in parse_result.pages:
        text = "\n".join(block.text for block in page.blocks if block.text.strip())
        pages.append(text)
    return pages


async def _run(path: Path) -> None:
    settings = get_settings()
    parse_result = parse_pdf(path, settings=settings)
    pages = _page_texts(parse_result)
    config = HeadersConfig.from_settings(settings)
    result = await extract_headers(pages, config=config)
    print("Attempts:")
    for attempt in result.attempts:
        payload = {
            "rung": attempt.rung,
            "status": attempt.status,
            "reason": attempt.reason,
            "retries": attempt.retries,
        }
        print(f"  - {payload}")
    print("\nHeaders:")
    for item in result.headers:
        number = item.number or ""
        print(f"  {number}\t{item.title}")
    if not result.ok:
        print("\nExtraction failed:", result.error)
        if result.meta:
            print("Meta:", result.meta)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="Path to a local PDF file")
    args = parser.parse_args()
    asyncio.run(_run(args.pdf))


if __name__ == "__main__":  # pragma: no cover - manual tool
    main()
