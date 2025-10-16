"""CLI helper for querying indexed specifications."""
from __future__ import annotations

import argparse
import sys
from typing import Sequence

from ..services.spec_rag import search_specs


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Query indexed specifications")
    parser.add_argument("--file-id", default="sample1", help="File identifier to query (default: sample1)")
    parser.add_argument("--q", required=True, help="Search query")
    parser.add_argument("--k", type=int, default=5, help="Number of results to return")
    args = parser.parse_args(argv)

    try:
        hits = search_specs(args.file_id, args.q, top_k=args.k)
    except FileNotFoundError as exc:
        code = exc.args[0] if exc.args else "specs_missing"
        print(
            f"No index available for '{args.file_id}' ({code}). Run specs_index with --rebuild first.",
            file=sys.stderr,
        )
        return 1

    if not hits:
        print("No matches found.")
        return 0

    for idx, hit in enumerate(hits, start=1):
        metadata = hit.get("metadata", {})
        header_path = metadata.get("header_path", "")
        print(f"{idx}. [{hit['score']:.3f}] {hit['text']}")
        if header_path:
            print(f"   Section: {header_path}")
        normalized_value = metadata.get("normalized_value")
        if normalized_value is not None:
            unit = metadata.get("normalized_unit") or ""
            print(f"   Normalized: {normalized_value} {unit}".strip())
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
