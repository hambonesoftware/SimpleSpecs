"""Generate a strict header alignment report for the MFC sample document."""

from __future__ import annotations

import json
import os
import sys
from importlib import import_module
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    golden_headers = import_module("backend.resources.golden_headers")
    services_header_report = import_module("backend.services.header_report")

    mfc_headers = getattr(golden_headers, "MFC_5M_R2001_E1985")
    generate_header_alignment_report = getattr(
        services_header_report, "generate_header_alignment_report"
    )

    os.environ.setdefault("HEADERS_LLM_STRICT", "true")

    pdf_path = repo_root / "MFC-5M_R2001_E1985.pdf"
    if not pdf_path.exists():
        raise SystemExit(f"PDF document not found: {pdf_path}")

    report = generate_header_alignment_report(pdf_path, mfc_headers)

    reports_dir = repo_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    output_path = reports_dir / "MFC-5M_R2001_E1985_header_report.json"
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Report written to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
