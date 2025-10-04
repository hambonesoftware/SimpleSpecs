from __future__ import annotations

from backend.text.toc_filters import (
    is_probably_toc_line,
    is_real_header_line,
    mark_toc_pages,
)


def test_probably_toc_line_detects_dot_leaders():
    assert is_probably_toc_line("1.2 Scope ............ 7", in_toc_region=False)
    assert not is_probably_toc_line("Chapter 1 Scope", in_toc_region=False)


def test_probably_toc_line_detects_roman_in_toc_region():
    assert is_probably_toc_line("Preface xv", in_toc_region=True)
    assert not is_probably_toc_line("Preface xv", in_toc_region=False)


def test_mark_toc_pages_and_real_header_lines():
    pages = [
        [
            "Table of Contents",
            "1 Overview ........ 3",
            "2 Design .......... 7",
        ],
        [
            "1 Overview",
            "Purpose",
        ],
    ]
    toc_pages = mark_toc_pages(pages)
    assert toc_pages == {0}

    assert not is_real_header_line("1 Overview ........ 3", page_idx=0, toc_pages=toc_pages)
    assert is_real_header_line("1 Overview", page_idx=1, toc_pages=toc_pages)
    assert is_real_header_line("Summary ... details", page_idx=1, toc_pages=toc_pages)
