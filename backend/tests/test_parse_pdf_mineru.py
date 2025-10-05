from __future__ import annotations

import importlib.util
from io import BytesIO
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.services import pdf_mineru


client = TestClient(create_app())
MINERU_AVAILABLE = importlib.util.find_spec("mineru") is not None


def _build_pdf_bytes() -> bytes:
    if importlib.util.find_spec("fitz") is not None:
        import fitz  # type: ignore

        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 720), "Hello MinerU Parser")
        data = document.tobytes()
        document.close()
        return data

    if importlib.util.find_spec("reportlab.pdfgen") is not None:
        from reportlab.pdfgen import canvas  # type: ignore
        from reportlab.lib.pagesizes import letter  # type: ignore

        buffer = BytesIO()
        canv = canvas.Canvas(buffer, pagesize=letter)
        canv.drawString(72, 720, "Hello MinerU Parser")
        canv.showPage()
        canv.save()
        buffer.seek(0)
        return buffer.read()

    return (
        b"%PDF-1.4\n1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n"
        b"2 0 obj<< /Type /Pages /Count 1 /Kids [3 0 R] >>endobj\n"
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
        b"4 0 obj<< /Length 55 >>stream\nBT /F1 24 Tf 72 700 Td (Hello MinerU Parser) Tj ET\nendstream\nendobj\n"
        b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n"
        b"xref\n0 6\n0000000000 65535 f \n0000000010 00000 n \n0000000060 00000 n \n0000000114 00000 n \n"
        b"0000000276 00000 n \n0000000385 00000 n \ntrailer<< /Root 1 0 R /Size 6 >>\nstartxref\n482\n%%EOF"
    )


def _assert_objects_shape(objects: list[dict[str, Any]]) -> None:
    assert isinstance(objects, list) and objects, "Expected parsed objects"
    required_keys = {"object_id", "file_id", "kind", "order_index", "metadata"}
    for obj in objects:
        assert required_keys.issubset(obj.keys())
        assert isinstance(obj["metadata"], dict)
    orders = [obj["order_index"] for obj in objects]
    assert orders == sorted(orders)
    assert len(set(orders)) == len(orders)
    ordering_keys = [((obj.get("page_index") or 0), obj["order_index"]) for obj in objects]
    assert ordering_keys == sorted(ordering_keys)


@pytest.mark.skipif(not MINERU_AVAILABLE, reason="MinerU not importable")
def test_pdf_mineru_golden() -> None:
    files = {"file": ("mineru.pdf", BytesIO(_build_pdf_bytes()), "application/pdf")}
    response = client.post("/ingest", files=files, data={"engine": "mineru"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["object_count"] >= 1

    parsed = client.get(f"/parsed/{payload['file_id']}")
    assert parsed.status_code == 200, parsed.text
    objects: list[dict[str, Any]] = parsed.json()
    _assert_objects_shape(objects)


def test_mineru_import_error_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMPLS_MINERU_ENABLED", "true")

    def fake_loader() -> tuple[None, str, str]:
        return None, "mineru", "boom"

    monkeypatch.setattr(pdf_mineru, "_load_mineru_module", fake_loader)

    with pytest.raises(pdf_mineru.MinerUUnavailableError) as excinfo:
        pdf_mineru.MinerUPdfParser(settings=pdf_mineru.Settings(MINERU_ENABLED=True))

    assert "boom" in str(excinfo.value)
