"""Tests for the sequential header alignment strategy."""

from __future__ import annotations

import pytest

from backend.services.headers_sequential import align_headers_sequential, normalize


@pytest.fixture
def sample_llm_headers() -> list[dict[str, str]]:
    return [
        {"number": "1", "title": "Introduction"},
        {"number": "1.1", "title": "Background"},
        {"number": "2", "title": "Requirements"},
        {"number": "2.1", "title": "Scope"},
    ]


@pytest.fixture
def sample_lines() -> list[dict[str, object]]:
    return [
        {
            "text": "Table of Contents .......... 1",
            "page": 0,
            "line_idx": 0,
            "global_idx": 0,
        },
        {
            "text": "1 Introduction",
            "page": 1,
            "line_idx": 0,
            "global_idx": 1,
        },
        {
            "text": "Some introductory text",
            "page": 1,
            "line_idx": 1,
            "global_idx": 2,
        },
        {
            "text": "1 . 1 Background",
            "page": 1,
            "line_idx": 2,
            "global_idx": 3,
        },
        {
            "text": "2 Requirements",
            "page": 2,
            "line_idx": 0,
            "global_idx": 4,
        },
        {
            "text": "2.1 Scope",
            "page": 2,
            "line_idx": 1,
            "global_idx": 5,
        },
    ]


def test_normalize_handles_confusables_and_spacing() -> None:
    assert normalize("1 . 1 Scope") == "1.1 scope"
    assert normalize("A I .2 Definitions").endswith("definitions")


def test_sequential_orders_chapters_and_children(
    sample_llm_headers: list[dict[str, str]], sample_lines: list[dict[str, object]]
) -> None:
    out = align_headers_sequential(
        sample_llm_headers,
        sample_lines,
        confusables=True,
        threshold=80,
        window_pad=40,
        tracer=None,
    )

    numbers = [item["number"] for item in out]
    assert numbers == ["1", "1.1", "2", "2.1"]
    assert all(item["page"] != 0 for item in out)


def test_l1_numeric_precedes_children(
    sample_llm_headers: list[dict[str, str]], sample_lines: list[dict[str, object]]
) -> None:
    out = align_headers_sequential(
        sample_llm_headers,
        sample_lines,
        confusables=True,
        threshold=80,
        window_pad=40,
        tracer=None,
    )

    positions = {entry["number"]: idx for idx, entry in enumerate(out)}
    if "1" in positions and "1.1" in positions:
        assert positions["1"] < positions["1.1"]


def test_invariants_parent_before_children(
    sample_llm_headers: list[dict[str, str]], sample_lines: list[dict[str, object]]
) -> None:
    out = align_headers_sequential(
        sample_llm_headers,
        sample_lines,
        confusables=True,
        threshold=78,
        window_pad=40,
        tracer=None,
    )

    positions = {entry["number"]: idx for idx, entry in enumerate(out)}
    for number in positions:
        if "." not in number:
            continue
        parent = ".".join(number.split(".")[:-1])
        if parent in positions:
            assert positions[parent] < positions[number]


def test_no_duplicate_numbers_within_parent(
    sample_llm_headers: list[dict[str, str]], sample_lines: list[dict[str, object]]
) -> None:
    out = align_headers_sequential(
        sample_llm_headers,
        sample_lines,
        confusables=True,
        threshold=78,
        window_pad=40,
        tracer=None,
    )

    from collections import defaultdict

    by_parent: dict[str, list[str]] = defaultdict(list)
    for header in out:
        number = header["number"]
        parent = ".".join(number.split(".")[:-1]) if "." in number else number
        by_parent[parent].append(number)

    for numbers in by_parent.values():
        assert len(numbers) == len(set(numbers))
