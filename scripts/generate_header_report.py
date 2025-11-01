"""Generate a strict header alignment report for the MFC sample document."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.resources.golden_headers import MFC_5M_R2001_E1985
from backend.services.header_report import generate_header_alignment_report


def main() -> int:
    os.environ.setdefault("HEADERS_LLM_STRICT", "true")

    pdf_path = REPO_ROOT / "MFC-5M_R2001_E1985.pdf"
    if not pdf_path.exists():
        raise SystemExit(f"PDF document not found: {pdf_path}")

    report = generate_header_alignment_report(pdf_path, MFC_5M_R2001_E1985)

    reports_dir = REPO_ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    output_path = reports_dir / "MFC-5M_R2001_E1985_header_report.json"
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Report written to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
