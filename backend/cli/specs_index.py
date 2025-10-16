"""CLI entrypoint for indexing specification chunks."""
from __future__ import annotations

import argparse
from pathlib import Path

from ..services.spec_rag import extract_specs, index_specs, load_spec_items


def _determine_file_id(source: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    path = Path(source)
    if path.is_file():
        return path.stem
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description="Index specification chunks for hybrid search")
    parser.add_argument("source", help="File identifier or source document path")
    parser.add_argument("--file-id", help="Explicit file identifier override")
    parser.add_argument("--rebuild", action="store_true", help="Re-run extraction before indexing")
    args = parser.parse_args()

    file_id = _determine_file_id(args.source, args.file_id)

    if args.rebuild:
        specs = extract_specs(file_id)
    else:
        try:
            specs = load_spec_items(file_id)
        except FileNotFoundError:
            specs = extract_specs(file_id)
    index_specs(file_id, specs=specs)
    print(f"Indexed {len(specs)} specifications for '{file_id}'.")


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
