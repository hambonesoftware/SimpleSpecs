"""CLI entrypoint for querying indexed specs."""
from __future__ import annotations

import argparse

from ..services.spec_rag import search_specs


def main() -> None:
    parser = argparse.ArgumentParser(description="Query indexed specifications")
    parser.add_argument("--file-id", default="sample1", help="File identifier to query (default: sample1)")
    parser.add_argument("--q", required=True, help="Search query")
    parser.add_argument("--k", type=int, default=5, help="Number of results to return")
    args = parser.parse_args()

    hits = search_specs(args.file_id, args.q, top_k=args.k)
    if not hits:
        print("No matches found.")
        return
    for idx, hit in enumerate(hits, start=1):
        metadata = hit.get("metadata", {})
        header_path = metadata.get("header_path", "")
        print(f"{idx}. [{hit['score']:.3f}] {hit['text']}")
        if header_path:
            print(f"   Section: {header_path}")
        if metadata.get("normalized_value") is not None:
            unit = metadata.get("normalized_unit") or ""
            print(
                f"   Normalized: {metadata['normalized_value']} {unit}".strip()
            )


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
