"""Tests for appendix-aware header extraction heuristics and prompts."""

from backend.config import Settings
from backend.services.headers import (
    HeaderExtractionResult,
    extract_headers,
    _render_prompt,
    _split_numbering,
)
from backend.services.pdf_native import ParsedBlock, ParsedPage, ParseResult


def _settings(tmp_path) -> Settings:
    """Return settings with isolated filesystem paths for tests."""

    return Settings(
        upload_dir=tmp_path / "uploads",
        spec_terms_dir=tmp_path / "terms",
        risk_baselines_path=tmp_path / "baselines.json",
        export_dir=tmp_path / "export",
        headers_llm_cache_dir=tmp_path / "headers-cache",
    )


def test_split_numbering_handles_appendix_label() -> None:
    """Appendix headings should expose numbering and trimmed titles."""

    number, title = _split_numbering("Appendix A - Data Tables")

    assert number == "APPENDIX A"
    assert title == "Data Tables"

    number_b, title_b = _split_numbering("Appendix B")
    assert number_b == "APPENDIX B"
    assert title_b == "Appendix B"


def test_extract_headers_includes_appendix(tmp_path) -> None:
    """Heuristic extraction should emit appendix headers without LLM help."""

    parse_result = ParseResult(
        pages=[
            ParsedPage(
                page_number=0,
                width=612,
                height=792,
                blocks=[
                    ParsedBlock(
                        text="1 Introduction",
                        bbox=(36.0, 72.0, 540.0, 90.0),
                        font_size=14.0,
                    ),
                ],
            ),
            ParsedPage(
                page_number=5,
                width=612,
                height=792,
                blocks=[
                    ParsedBlock(
                        text="Appendix A Data Tables",
                        bbox=(36.0, 72.0, 540.0, 90.0),
                        font_size=14.5,
                    ),
                    ParsedBlock(
                        text="Additional context",
                        bbox=(36.0, 96.0, 540.0, 112.0),
                        font_size=11.0,
                    ),
                ],
            ),
        ]
    )

    settings = _settings(tmp_path)
    result = extract_headers(parse_result, settings=settings, llm_client=None)

    appendix_nodes = [
        node
        for node in result.outline
        if node.numbering.upper().startswith("APPENDIX")
    ]

    assert appendix_nodes, "Expected at least one appendix header"
    assert any("Data Tables" in node.title for node in appendix_nodes)


def test_render_prompt_highlights_appendix_context(tmp_path) -> None:
    """LLM prompt should emphasise appendix handling and context."""

    pages = [
        ParsedPage(
            page_number=index,
            width=612,
            height=792,
            blocks=[
                ParsedBlock(
                    text=f"{index + 1}. Section {index + 1}",
                    bbox=(36.0, 72.0, 540.0, 90.0),
                    font_size=13.0,
                )
            ],
        )
        for index in range(3)
    ]
    pages.append(
        ParsedPage(
            page_number=3,
            width=612,
            height=792,
            blocks=[
                ParsedBlock(
                    text="Appendix A - Reference Data",
                    bbox=(36.0, 72.0, 540.0, 90.0),
                    font_size=14.0,
                ),
                ParsedBlock(
                    text="Detailed appendix material",
                    bbox=(36.0, 96.0, 540.0, 112.0),
                    font_size=11.0,
                ),
            ],
        )
    )

    parse_result = ParseResult(pages=pages)
    heuristic_result = HeaderExtractionResult(
        outline=[], fenced_text="#headers#\n#/headers#", source="heuristic"
    )

    prompt = _render_prompt(parse_result, heuristic_result)

    assert "Do not omit appendices" in prompt
    assert "Appendix preview (Page 3)" in prompt
