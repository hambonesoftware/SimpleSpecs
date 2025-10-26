"""Integration tests for the native PDF parser using bundled samples."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.config import Settings
from backend.services.pdf_native import ParseResult, parse_pdf

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DOCS = [
    REPO_ROOT / "Epf, Co.pdf",
    REPO_ROOT / "MFC-5M_R2001_E1985.pdf",
]


@pytest.mark.parametrize("sample_path", SAMPLE_DOCS)
def test_parse_samples_yield_blocks(sample_path: Path, tmp_path: Path) -> None:
    """Each bundled sample document should produce non-empty parse results."""

    if not sample_path.exists():
        pytest.skip(f"Sample document {sample_path.name} missing")

    settings = Settings(
        upload_dir=tmp_path,
        parser_multi_column=True,
        parser_enable_ocr=False,
        headers_suppress_toc=True,
        headers_suppress_running=True,
        mineru_fallback=False,
    )

    result: ParseResult = parse_pdf(sample_path, settings=settings)
    assert result.pages, "Parser returned no pages"
    assert any(page.blocks for page in result.pages), "Parser returned no text blocks"

    # Ensure page metadata looks sane
    for page in result.pages:
        assert page.width > 0
        assert page.height > 0
