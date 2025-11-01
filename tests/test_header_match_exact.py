"""Unit tests for the exact header matcher helper."""

from backend.services.header_match import _match_on_page_exact


def test_match_on_page_exact_multiline_heading():
    page_lines = [
        {"page": 1, "line_in_page": 1, "text": "Introduction"},
        {"page": 1, "line_in_page": 2, "text": "Scope and"},
        {"page": 1, "line_in_page": 3, "text": "Purpose"},
        {"page": 1, "line_in_page": 4, "text": "Appendix ................ 12"},
    ]

    found, info = _match_on_page_exact("Scope and\nPurpose", page_lines)

    assert found is True
    assert info is not None
    assert info["line_in_page"] == 2
    assert info["matched_text"] == "Scope and\nPurpose"

    toc_found, _ = _match_on_page_exact("Appendix", page_lines)
    assert toc_found is False
