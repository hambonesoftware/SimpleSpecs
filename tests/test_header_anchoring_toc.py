from __future__ import annotations

from backend.models import HeaderItem
from backend.routers import _headers_common
from backend.services.text_blocks import LineEntry


def test_parse_and_store_headers_skips_toc_lines(monkeypatch):
    upload_id = "file-123"
    response_text = """#headers#\n1. Introduction\n  1.1 Scope\n#headers#"""

    entries = [
        LineEntry(text="Table of Contents", page_index=0, line_index=0),
        LineEntry(text="1 Introduction ........ 3", page_index=0, line_index=1),
        LineEntry(text="1.1 Scope ........ 4", page_index=0, line_index=2),
        LineEntry(text="1 Introduction", page_index=2, line_index=10),
        LineEntry(text="Project overview details", page_index=2, line_index=11),
        LineEntry(text="1.1 Scope", page_index=3, line_index=5),
        LineEntry(text="Scope specifics", page_index=3, line_index=6),
    ]

    objects = [
        {
            "kind": "line",
            "text": entry.text,
            "page_index": entry.page_index,
            "line_index": entry.line_index,
        }
        for entry in entries
    ]

    captured_headers: list[list[dict[str, object]]] = []

    monkeypatch.setattr(_headers_common, "read_jsonl", lambda path: objects)
    monkeypatch.setattr(
        _headers_common,
        "document_line_entries",
        lambda _objects: entries,
    )
    monkeypatch.setattr(_headers_common, "write_json", lambda path, payload: captured_headers.append(payload))

    headers = _headers_common.parse_and_store_headers(upload_id, response_text)
    assert headers

    intro = headers[0]
    assert isinstance(intro, HeaderItem)
    assert intro.section_number == "1"
    assert intro.section_name.lower() == "introduction"
    assert intro.page_number == 3  # actual body page, not TOC
    assert intro.line_number == 11  # original line index is zero-based 10
    assert intro.chunk_text.startswith("1 Introduction")

    scope = headers[1]
    assert scope.page_number == 4
    assert scope.line_number == 6

    assert captured_headers and captured_headers[0]
