import io
import os
import zipfile
from pathlib import Path

from docx import Document as DocxDocument
from fastapi.testclient import TestClient

PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"
)


def _upload_sample(client: TestClient) -> int:
    response = client.post(
        "/api/upload",
        files={"file": ("sample.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
    )
    assert response.status_code in {200, 201}
    payload = response.json()
    return payload["id"]


def _spec_payload(document_id: int) -> dict:
    return {
        "document_id": document_id,
        "buckets": {
            "mechanical": [
                {
                    "text": "Pump shall be rated for 100 psi.",
                    "page": 0,
                    "header_path": ["Section 1", "Pumps"],
                    "source": "rule",
                    "scores": {"mechanical": 1.0},
                    "provenance": {
                        "page": 0,
                        "block_index": 0,
                        "line_index": 0,
                        "bbox": None,
                    },
                }
            ],
            "unknown": [],
        },
    }


def test_spec_approval_flow_and_exports(client: TestClient) -> None:
    document_id = _upload_sample(client)

    payload = _spec_payload(document_id)

    first = client.post(
        f"/api/specs/{document_id}/approve",
        json={
            "reviewer": "qa@example.com",
            "payload": payload,
            "notes": "Initial pass",
        },
        headers={"X-Request-ID": "approve-1"},
    )
    assert first.status_code == 200
    assert first.headers["X-Request-ID"] == "approve-1"
    first_data = first.json()
    assert first_data["record"]["state"] == "approved"
    assert first_data["record"]["approved_at"] is not None
    hash_one = first_data["record"]["content_hash"]
    assert hash_one

    second = client.post(
        f"/api/specs/{document_id}/approve",
        json={"reviewer": "qa@example.com", "payload": payload},
        headers={"X-Request-ID": "approve-2"},
    )
    assert second.status_code == 200
    assert second.headers["X-Request-ID"] == "approve-2"
    second_data = second.json()
    assert second_data["record"]["content_hash"] == hash_one
    assert second_data["record"]["id"] == first_data["record"]["id"]

    status = client.get(
        f"/api/specs/{document_id}", headers={"X-Request-ID": "status-1"}
    )
    assert status.status_code == 200
    snapshot = status.json()
    assert snapshot["record"]["content_hash"] == hash_one
    assert len(snapshot["audit"]) >= 2
    assert snapshot["audit"][0]["action"] == "approve"
    assert snapshot["audit"][-1]["detail"]["changed"] is False
    assert snapshot["audit"][0]["detail"]["request_id"] == "approve-1"
    assert snapshot["audit"][1]["detail"]["request_id"] == "approve-2"

    csv_response = client.get(
        f"/api/specs/{document_id}/export",
        params={"fmt": "csv"},
        headers={"X-Request-ID": "export-csv"},
    )
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("application/zip")
    assert csv_response.headers["X-Request-ID"] == "export-csv"
    with zipfile.ZipFile(io.BytesIO(csv_response.content)) as archive:
        members = archive.namelist()
        assert "mechanical.csv" in members
        csv_payload = archive.read("mechanical.csv").decode()
        assert "Pump shall be rated for 100 psi." in csv_payload

    docx_response = client.get(
        f"/api/specs/{document_id}/export",
        params={"fmt": "docx"},
        headers={"X-Request-ID": "export-docx"},
    )
    assert docx_response.status_code == 200
    assert docx_response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert docx_response.headers["X-Request-ID"] == "export-docx"
    document = DocxDocument(io.BytesIO(docx_response.content))
    combined_text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "Pump shall be rated for 100 psi." in combined_text

    export_dir = Path(os.environ["EXPORT_DIR"])
    saved = list(export_dir.glob("spec-*.docx"))
    assert saved, "DOCX export should be written to disk"

    final_status = client.get(
        f"/api/specs/{document_id}", headers={"X-Request-ID": "status-2"}
    )
    assert final_status.status_code == 200
    audit_entries = final_status.json()["audit"]
    export_entries = [entry for entry in audit_entries if entry["action"] == "export"]
    assert export_entries[-2]["detail"]["request_id"] == "export-csv"
    assert export_entries[-1]["detail"]["request_id"] == "export-docx"
