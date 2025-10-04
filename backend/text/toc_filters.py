from __future__ import annotations

import re
from typing import List, Set

# Common dot/leader glyphs: "." "․" "…" "⋯" "·" "‧"
_LEADERS = r".\u2024\u2026\u22EF\u00B7\u2027"

# e.g., "5.2 Transformer connections ......... 4" or "Annex A — ... 32"
TOC_DOT_LEADER_LINE = re.compile(
    rf"""
    ^\s*
    (?P<title>.+?)                              # title-like text
    (?=[\s{_LEADERS}]*[{_LEADERS}])[\s{_LEADERS}]+    # run of leaders
    (?P<page>
        (?:\d{{1,4}}|[ivxlcdm]{{1,8}})
    )\s*$                                       # page number at end
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Canonical TOC page heading
TOC_HEADING = re.compile(r"^\s*(table\s+of\s+)?contents\s*$", re.IGNORECASE)

# Roman-only page number at line end (for preface pages); apply only in TOC regions
TOC_TRAILING_PAGE_ONLY = re.compile(r"\b[ivxlcdm]{1,8}\s*$", re.IGNORECASE)


def is_probably_toc_line(line: str, *, in_toc_region: bool) -> bool:
    s = (line or "").strip()
    if not s:
        return False
    if TOC_DOT_LEADER_LINE.search(s):
        return True
    if in_toc_region and TOC_TRAILING_PAGE_ONLY.search(s):
        return True
    return False


def mark_toc_pages(pages: List[List[str]], *, search_window: int = 10) -> Set[int]:
    """
    Detect TOC pages in the first `search_window` pages using headings and density of dot-leader lines.
    Returns the set of page indices considered TOC.
    """

    toc_pages: Set[int] = set()
    in_toc = False
    for i, lines in enumerate(pages[: max(1, search_window)]):
        # enter TOC region on heading or density of dot-leaders
        if any(TOC_HEADING.match(ln or "") for ln in lines):
            in_toc = True
        if not in_toc:
            dotleader_hits = sum(1 for ln in lines if ln and TOC_DOT_LEADER_LINE.search(ln))
            if dotleader_hits >= 3:  # heuristic entry
                in_toc = True
        if in_toc:
            # remain TOC while page remains TOC-ish
            dotleader_hits = sum(1 for ln in lines if ln and TOC_DOT_LEADER_LINE.search(ln))
            if dotleader_hits >= 2 or any(TOC_HEADING.match(ln or "") for ln in lines):
                toc_pages.add(i)
            else:
                in_toc = False
    return toc_pages


def is_real_header_line(line: str, page_idx: int, toc_pages: Set[int]) -> bool:
    """Quick predicate to allow lines that are not in TOC and not leader+page lines."""

    if page_idx in toc_pages:
        return False
    if is_probably_toc_line(line, in_toc_region=False):
        return False
    return True


__all__ = [
    "is_probably_toc_line",
    "is_real_header_line",
    "mark_toc_pages",
    "TOC_DOT_LEADER_LINE",
    "TOC_HEADING",
    "TOC_TRAILING_PAGE_ONLY",
]
