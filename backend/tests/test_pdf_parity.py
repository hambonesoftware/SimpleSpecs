from __future__ import annotations

import importlib.util
from io import BytesIO
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.models import FIGURE_KIND, LINE_KIND, PARAGRAPH_KIND, TABLE_KIND


client = TestClient(create_app())
MINERU_AVAILABLE = any(
    importlib.util.find_spec(name) is not None
    for name in ("magic_pdf", "mineru", "mineru_core")
)


def _build_pdf_bytes() -> bytes:
    if importlib.util.find_spec("fitz") is not None:
        import fitz  # type: ignore

        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 720), "Parity Check")
        data = document.tobytes()
        document.close()
        return data

    if importlib.util.find_spec("reportlab.pdfgen") is not None:
        from reportlab.pdfgen import canvas  # type: ignore
        from reportlab.lib.pagesizes import letter  # type: ignore

        buffer = BytesIO()
        canv = canvas.Canvas(buffer, pagesize=letter)
        canv.drawString(72, 720, "Parity Check")
        canv.showPage()
        canv.save()
        buffer.seek(0)
        return buffer.read()

    return (
        b"%PDF-1.4\n1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n"
        b"2 0 obj<< /Type /Pages /Count 1 /Kids [3 0 R] >>endobj\n"
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
        b"4 0 obj<< /Length 48 >>stream\nBT /F1 18 Tf 72 700 Td (Parity Check) Tj ET\nendstream\nendobj\n"
        b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n"
        b"xref\n0 6\n0000000000 65535 f \n0000000010 00000 n \n0000000060 00000 n \n0000000114 00000 n \n"
        b"0000000276 00000 n \n0000000385 00000 n \ntrailer<< /Root 1 0 R /Size 6 >>\nstartxref\n476\n%%EOF"
    )


def _collect_objects(file_id: str) -> list[dict[str, Any]]:
    response = client.get(f"/parsed/{file_id}")
    assert response.status_code == 200, response.text
    objects = response.json()
    assert isinstance(objects, list)
    return objects


@pytest.mark.skipif(not MINERU_AVAILABLE, reason="MinerU not importable")
def test_native_vs_mineru_parity() -> None:
    pdf_bytes = _build_pdf_bytes()
    files = {"file": ("parity.pdf", BytesIO(pdf_bytes), "application/pdf")}

    native_response = client.post("/ingest", files=files, data={"engine": "native"})
    assert native_response.status_code == 200, native_response.text
    native_payload = native_response.json()

    mineru_response = client.post(
        "/ingest",
        files={"file": ("parity.pdf", BytesIO(pdf_bytes), "application/pdf")},
        data={"engine": "mineru"},
    )
    assert mineru_response.status_code == 200, mineru_response.text
    mineru_payload = mineru_response.json()

    native_objects = _collect_objects(native_payload["file_id"])
    mineru_objects = _collect_objects(mineru_payload["file_id"])

    assert native_objects and mineru_objects

    native_kinds = {obj["kind"] for obj in native_objects}
    mineru_kinds = {obj["kind"] for obj in mineru_objects}
    canonical_kinds = {LINE_KIND, PARAGRAPH_KIND, TABLE_KIND, FIGURE_KIND}
    assert native_kinds & canonical_kinds
    assert mineru_kinds & canonical_kinds
    assert (native_kinds & canonical_kinds) == (mineru_kinds & canonical_kinds)

    assert abs(len(native_objects) - len(mineru_objects)) <= max(2, len(native_objects) // 2)
