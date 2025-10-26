#!/usr/bin/env python3
"""Utility for processing a PDF document through the SimpleSpecs API stack."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _set_environment(work_dir: Path) -> None:
    """Configure environment variables so the API writes into ``work_dir``."""

    upload_dir = work_dir / "uploads"
    export_dir = work_dir / "exports"
    upload_dir.mkdir(parents=True, exist_ok=True)
    export_dir.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("UPLOAD_DIR", str(upload_dir))
    os.environ.setdefault("EXPORT_DIR", str(export_dir))
    os.environ.setdefault(
        "DB_URL", f"sqlite:///{(work_dir / 'simplespecs.db').resolve()}"
    )


def _initialise_app() -> TestClient:
    """Return a ``TestClient`` configured with freshly initialised settings."""

    from backend.config import reset_settings_cache
    from backend.database import reset_database_state
    from backend.main import app

    reset_settings_cache()
    reset_database_state()

    return TestClient(app)


def _raise_for_status(response) -> None:
    """Raise a descriptive error if the response indicates failure."""

    if response.status_code >= 400:
        detail: str | None = None
        try:
            payload = response.json()
        except Exception:  # pragma: no cover - diagnostic path
            payload = None
        if isinstance(payload, dict):
            detail = payload.get("detail") or payload.get("message")
        raise RuntimeError(
            f"Request failed with status {response.status_code}: {detail or response.text}"
        )


def _write_json(target: Path, payload: Any) -> None:
    """Serialise *payload* to ``target`` with UTF-8 encoding."""

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="Path to the PDF document to process")
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path("runtime_artifacts"),
        help="Directory where uploads, exports, and JSON artefacts will be stored",
    )
    parser.add_argument(
        "--skip-risk",
        action="store_true",
        help="Skip the risk comparison step (faster, produces parse + extraction only)",
    )
    args = parser.parse_args(argv)

    pdf_path = args.pdf.expanduser().resolve()
    if not pdf_path.exists():
        parser.error(f"PDF file not found: {pdf_path}")

    work_dir = args.work_dir.expanduser().resolve()
    _set_environment(work_dir)

    client = _initialise_app()

    with client as api_client:
        with pdf_path.open("rb") as handle:
            response = api_client.post(
                "/api/upload",
                files={"file": (pdf_path.name, handle, "application/pdf")},
            )
        _raise_for_status(response)
        document = response.json()
        document_id = document["id"]

        parse_response = api_client.post(f"/api/parse/{document_id}")
        _raise_for_status(parse_response)
        parse_payload = parse_response.json()

        extraction_response = api_client.post(f"/api/specs/extract/{document_id}")
        _raise_for_status(extraction_response)
        extraction_payload = extraction_response.json()

        risk_payload = None
        if not args.skip_risk:
            risk_response = api_client.post(f"/api/specs/compare/{document_id}")
            _raise_for_status(risk_response)
            risk_payload = risk_response.json()

    artefact_dir = work_dir / "artefacts" / f"document-{document_id}"
    _write_json(artefact_dir / "upload.json", document)
    _write_json(artefact_dir / "parse.json", parse_payload)
    _write_json(artefact_dir / "specs.json", extraction_payload)
    if risk_payload is not None:
        _write_json(artefact_dir / "risk.json", risk_payload)

    summary_lines = [
        f"Processed document {document_id} ({pdf_path.name})",
        f"- Stored uploads in: {os.environ['UPLOAD_DIR']}",
        f"- Parse pages: {len(parse_payload.get('pages', []))}",
        f"- Disciplines extracted: {', '.join(sorted(extraction_payload.get('buckets', {}).keys()))}",
    ]
    if risk_payload is not None:
        summary_lines.append(
            f"- Risk overall score: {risk_payload.get('overall_score', 'n/a')}"
        )

    print("\n".join(summary_lines))
    print(f"Artefacts written to {artefact_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
