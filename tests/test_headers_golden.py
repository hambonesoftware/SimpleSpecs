"""Golden tests validating LLM-driven header extraction and endpoint."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from backend.config import Settings, reset_settings_cache
from backend.database import get_engine, init_db, reset_database_state
from backend.models import Document
from backend.services.headers import HeaderExtractionResult, HeaderNode, extract_headers
from backend.services.pdf_native import ParsedBlock, ParsedPage, ParseResult


def _sample_parse_result() -> ParseResult:
    page0 = ParsedPage(
        page_number=0,
        width=612,
        height=792,
        blocks=[
            ParsedBlock(
                text="1 General Requirements",
                bbox=(36.0, 72.0, 400.0, 88.0),
                font="Helvetica-Bold",
                font_size=14.0,
            ),
            ParsedBlock(
                text="1.1 Scope",
                bbox=(54.0, 96.0, 400.0, 110.0),
                font="Helvetica-Bold",
                font_size=12.0,
            ),
            ParsedBlock(
                text="1.2 References",
                bbox=(54.0, 120.0, 400.0, 134.0),
                font="Helvetica",
                font_size=12.0,
            ),
            ParsedBlock(
                text="Body text that should be ignored for header extraction.",
                bbox=(72.0, 144.0, 400.0, 160.0),
                font="Helvetica",
                font_size=10.0,
            ),
        ],
    )
    page1 = ParsedPage(
        page_number=1,
        width=612,
        height=792,
        blocks=[
            ParsedBlock(
                text="2 Materials",
                bbox=(36.0, 72.0, 400.0, 88.0),
                font="Helvetica-Bold",
                font_size=14.0,
            ),
            ParsedBlock(
                text="2.1 Steel Alloys",
                bbox=(54.0, 96.0, 400.0, 112.0),
                font="Helvetica",
                font_size=12.0,
            ),
            ParsedBlock(
                text="2.2 Aluminum",
                bbox=(54.0, 120.0, 400.0, 134.0),
                font="Helvetica",
                font_size=12.0,
            ),
        ],
    )
    return ParseResult(pages=[page0, page1])


def _toc_parse_result() -> ParseResult:
    toc_page = ParsedPage(
        page_number=0,
        width=612,
        height=792,
        blocks=[
            ParsedBlock(
                text="Table of Contents",
                bbox=(36.0, 72.0, 400.0, 88.0),
                font="Helvetica-Bold",
                font_size=16.0,
            ),
            ParsedBlock(
                text="1 General Requirements",
                bbox=(54.0, 96.0, 400.0, 112.0),
                font="Helvetica",
                font_size=12.0,
            ),
        ],
        is_toc=True,
    )
    return ParseResult(pages=[toc_page])


@pytest.fixture(autouse=True)
def _isolate_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Generator[None, None, None]:
    db_path = tmp_path / "headers.db"
    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("LLM_PROVIDER", "disabled")
    reset_settings_cache()
    reset_database_state()
    yield
    reset_settings_cache()
    reset_database_state()


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    from backend.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_extract_headers_generates_expected_outline(tmp_path: Path) -> None:
    parse_result = _sample_parse_result()
    class StubLLM:
        is_enabled = True

        def refine_outline(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            root1 = HeaderNode(title="General Requirements", numbering="1", page=0)
            root1.children.extend(
                [
                    HeaderNode(title="Scope", numbering="1.1", page=0),
                    HeaderNode(title="References", numbering="1.2", page=0),
                ]
            )
            root2 = HeaderNode(title="Materials", numbering="2", page=1)
            root2.children.extend(
                [
                    HeaderNode(title="Steel Alloys", numbering="2.1", page=1),
                    HeaderNode(title="Aluminum", numbering="2.2", page=1),
                ]
            )
            outline = [root1, root2]
            fenced = "#headers#\n{\"headers\": []}\n#/headers#"
            return HeaderExtractionResult(outline=outline, fenced_text=fenced, source="openrouter")

    settings = Settings(upload_dir=tmp_path)
    result = extract_headers(parse_result, settings=settings, llm_client=StubLLM())

    expected_outline = [
        {
            "title": "General Requirements",
            "numbering": "1",
            "page": 0,
            "children": [
                {"title": "Scope", "numbering": "1.1", "page": 0, "children": []},
                {"title": "References", "numbering": "1.2", "page": 0, "children": []},
            ],
        },
        {
            "title": "Materials",
            "numbering": "2",
            "page": 1,
            "children": [
                {
                    "title": "Steel Alloys",
                    "numbering": "2.1",
                    "page": 1,
                    "children": [],
                },
                {"title": "Aluminum", "numbering": "2.2", "page": 1, "children": []},
            ],
        },
    ]

    assert result.to_json() == expected_outline
    assert result.fenced_text.splitlines()[0] == "#headers#"
    assert result.fenced_text.splitlines()[-1] == "#/headers#"


def test_toc_pages_are_ignored(tmp_path: Path) -> None:
    parse_result = _toc_parse_result()
    settings = Settings(upload_dir=tmp_path)
    result = extract_headers(parse_result, settings=settings, llm_client=None)
    assert result.outline == []
    assert "disabled" in result.messages[0].lower()


def test_headers_endpoint_returns_outline(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = get_engine()
    init_db()

    with Session(engine) as session:
        document = Document(
            filename="sample.pdf", checksum=hashlib.sha256(b"sample").hexdigest()
        )
        session.add(document)
        session.commit()
        session.refresh(document)

        doc_dir = Path(tmp_path / "uploads" / str(document.id))
        doc_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = doc_dir / document.filename
        pdf_path.write_bytes(b"%PDF-1.4\n%%EOF")

    sample_result = _sample_parse_result()

    def _mock_parse(document_path, *, settings):  # noqa: ANN001 - test helper
        return sample_result

    async def _mock_extract_headers_and_chunks(
        document_bytes: bytes,
        *,
        settings,
        native_headers,
        metadata,
        want_trace=False,
    ) -> tuple[dict, None]:
        lines = [
            {
                "text": "General Requirements",
                "page": 0,
                "line_idx": 0,
                "global_idx": 0,
                "is_running": False,
                "is_toc": False,
                "is_index": False,
            },
            {
                "text": "Scope",
                "page": 0,
                "line_idx": 1,
                "global_idx": 1,
                "is_running": False,
                "is_toc": False,
                "is_index": False,
            },
        ]
        payload = {
            "headers": [
                {
                    "text": "General Requirements",
                    "number": "1",
                    "level": 1,
                    "page": 0,
                    "line_idx": 0,
                    "global_idx": 0,
                },
                {
                    "text": "Scope",
                    "number": "1.1",
                    "level": 2,
                    "page": 0,
                    "line_idx": 1,
                    "global_idx": 1,
                },
            ],
            "sections": [
                {
                    "header_text": "General Requirements",
                    "header_number": "1",
                    "level": 1,
                    "start_global_idx": 0,
                    "end_global_idx": 0,
                    "start_page": 0,
                    "end_page": 0,
                },
                {
                    "header_text": "Scope",
                    "header_number": "1.1",
                    "level": 2,
                    "start_global_idx": 1,
                    "end_global_idx": 1,
                    "start_page": 0,
                    "end_page": 0,
                },
            ],
            "mode": "llm_full",
            "lines": lines,
            "doc_hash": "abc123",
            "excluded_pages": [],
        }
        return payload, None

    class StubHeadersClient:
        def __init__(self, *_args, **_kwargs) -> None:
            self.is_enabled = True

        def refine_outline(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            root = HeaderNode(title="General Requirements", numbering="1", page=0)
            root.children.append(
                HeaderNode(title="Scope", numbering="1.1", page=0)
            )
            fenced = "#headers#\n{\"headers\": []}\n#/headers#"
            return HeaderExtractionResult(
                outline=[root], fenced_text=fenced, source="openrouter"
            )

    monkeypatch.setattr("backend.routers.headers.parse_pdf", _mock_parse)
    monkeypatch.setattr(
        "backend.routers.headers.extract_headers_and_chunks",
        _mock_extract_headers_and_chunks,
    )
    monkeypatch.setattr(
        "backend.routers.headers.HeadersLLMClient", lambda settings: StubHeadersClient()
    )

    response = client.post(f"/api/headers/{document.id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["documentId"] == document.id
    assert payload["meta"]["sourceHash"] == "abc123"
    assert payload["meta"]["model"] == "anthropic/claude-3.5-sonnet"
    assert payload["outline"][0]["title"] == "General Requirements"
    assert payload["outline"][0]["children"][0]["title"] == "Scope"
    assert payload["mode"] == "llm_full"
    assert payload["simpleheaders"][0]["text"] == "General Requirements"
    assert payload["simpleheaders"][0]["section_key"]
    section = payload["sections"][0]
    assert section["start_global_idx"] == 0
    assert section["end_global_idx"] == 0
    assert section["section_key"] == payload["simpleheaders"][0]["section_key"]
