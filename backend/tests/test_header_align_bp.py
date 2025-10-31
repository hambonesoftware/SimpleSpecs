import pytest

pytest.importorskip("rapidfuzz")

from backend.services.header_align_bp import align_headers_best


def _mk_line(text: str, page: int, global_idx: int, *, size: float = 12.0, bold: bool = False):
    return {
        "text": text,
        "page": page,
        "global_idx": global_idx,
        "font_size": size,
        "bold": bold,
    }


def test_toc_suppression_and_after_anchor():
    llm_headers = [
        {"number": "1", "title": "GENERAL", "level": 1},
        {"number": "1.1", "title": "Scope and Field of Application", "level": 2},
        {"number": "2", "title": "METHODS", "level": 1},
    ]
    lines = [
        _mk_line("1 GENERAL .... 3", 1, 0, size=10),
        _mk_line("1.1 Scope and Field of Application .... 4", 1, 1, size=10),
        _mk_line("Preface text", 2, 2, size=10),
        _mk_line("1 GENERAL", 3, 3, size=14, bold=True),
        _mk_line("1 .I Scope and Field of Application", 4, 4, size=13, bold=True),
        _mk_line("2 METHODS", 10, 5, size=14, bold=True),
    ]

    resolved = align_headers_best(llm_headers, lines, tracer=None)
    numbers = [entry["number"] for entry in resolved]
    assert numbers == ["1", "1.1", "2"]

    lookup = {entry["number"]: entry["global_idx"] for entry in resolved}
    assert lookup["1.1"] == 4


def test_monotonic_parent_before_child():
    llm_headers = [
        {"number": "1", "title": "A", "level": 1},
        {"number": "1.1", "title": "B", "level": 2},
    ]
    lines = [
        _mk_line("1 A", 3, 3, size=14, bold=True),
        _mk_line("1.1 B", 4, 4, size=13, bold=True),
    ]

    resolved = align_headers_best(llm_headers, lines, tracer=None)
    assert [entry["number"] for entry in resolved] == ["1", "1.1"]
    assert resolved[0]["global_idx"] < resolved[1]["global_idx"]
