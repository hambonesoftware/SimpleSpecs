"""Tests for header orchestration helpers."""

from backend.services.headers_orchestrator import _enforce_header_sequence


def _line(text: str, global_idx: int, *, page: int = 1, line_idx: int | None = None) -> dict:
    return {
        "text": text,
        "global_idx": global_idx,
        "page": page,
        "line_idx": global_idx if line_idx is None else line_idx,
    }


def _header(
    text: str,
    number: str,
    *,
    global_idx: int,
    level: int = 1,
    page: int = 1,
    line_idx: int | None = None,
) -> dict:
    return {
        "text": text,
        "number": number,
        "level": level,
        "page": page,
        "line_idx": global_idx if line_idx is None else line_idx,
        "global_idx": global_idx,
    }


def test_enforce_header_sequence_recovers_numeric_gap() -> None:
    lines = [
        _line("1. Scope", 0),
        _line("2. Requirements", 1),
        _line("3. Execution", 2),
    ]
    headers = [
        _header("Scope", "1", global_idx=0),
        _header("Execution", "3", global_idx=2),
    ]

    repaired, sections = _enforce_header_sequence(headers, lines)

    numbers = [header.get("number") for header in repaired]
    assert numbers == ["1", "2", "3"]
    assert repaired[1]["text"] == "Requirements"
    assert sections[1]["start_global_idx"] == 1
    assert sections[1]["end_global_idx"] == 1


def test_enforce_header_sequence_recovers_alpha_gap() -> None:
    lines = [
        _line("A) Overview", 0),
        _line("B) Safety", 1),
        _line("C) Maintenance", 2),
    ]
    headers = [
        _header("Overview", "A", global_idx=0),
        _header("Maintenance", "C", global_idx=2),
    ]

    repaired, _ = _enforce_header_sequence(headers, lines)

    numbers = [header.get("number") for header in repaired]
    assert numbers == ["A", "B", "C"]
    assert repaired[1]["text"] == "Safety"


def test_enforce_header_sequence_ignores_missing_when_not_found() -> None:
    lines = [
        _line("1. Scope", 0),
        _line("Random content", 1),
        _line("3. Execution", 2),
    ]
    headers = [
        _header("Scope", "1", global_idx=0),
        _header("Execution", "3", global_idx=2),
    ]

    repaired, _ = _enforce_header_sequence(headers, lines)

    numbers = [header.get("number") for header in repaired]
    assert numbers == ["1", "3"]
