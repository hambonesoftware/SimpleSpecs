"""Tests for appendix-aware header extraction prompts and helpers."""

from backend.config import Settings
from backend.services.headers import (
    HeaderExtractionResult,
    HeaderNode,
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


def test_extract_headers_returns_llm_outline(tmp_path) -> None:
    """The extractor should return outlines supplied by the LLM client."""

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
        ]
    )

    appendix_node = HeaderNode(title="Appendix A", numbering="APPENDIX A", page=5)
    llm_result = HeaderExtractionResult(
        outline=[appendix_node],
        fenced_text="#headers#\n{\"headers\": []}\n#/headers#",
        source="openrouter",
    )

    class StubClient:
        is_enabled = True

        def refine_outline(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return llm_result

    settings = _settings(tmp_path)
    result = extract_headers(parse_result, settings=settings, llm_client=StubClient())

    assert result is llm_result


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

    prompt = _render_prompt(parse_result)

    assert "Do not omit appendices" in prompt
    assert "Appendix preview (Page 3)" in prompt
