from __future__ import annotations

from typing import Dict, List

import pypdfium2 as pdfium

from ._normalize import normalize_numeric_artifacts


def extract_lines_pdfium(pdf_path: str) -> List[Dict[str, object]]:
    output: List[Dict[str, object]] = []
    global_idx = 0
    document = pdfium.PdfDocument(pdf_path)
    try:
        for page_index in range(len(document)):
            page = document.get_page(page_index)
            text_page = page.get_textpage()
            try:
                text_all = text_page.get_text_range()
            finally:
                text_page.close()
                page.close()
            for raw in (text_all.splitlines() if text_all else []):
                text = normalize_numeric_artifacts(raw)
                output.append(
                    {
                        "text": text,
                        "page": page_index + 1,
                        "global_idx": global_idx,
                        "bbox": None,
                    }
                )
                global_idx += 1
    finally:
        document.close()
    return output


def extract_page_text_pdfium(pdf_path: str) -> str:
    document = pdfium.PdfDocument(pdf_path)
    chunks: List[str] = []
    try:
        for page_index in range(len(document)):
            page = document.get_page(page_index)
            text_page = page.get_textpage()
            try:
                chunks.append(text_page.get_text_range() or "")
            finally:
                text_page.close()
                page.close()
    finally:
        document.close()
    return "\n".join(chunks)


__all__ = ["extract_lines_pdfium", "extract_page_text_pdfium"]
