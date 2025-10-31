from __future__ import annotations

import json

from backend.services.headers_llm_strict import extract_headers_and_sections_strict


class DummyLLMResult:
    def __init__(self, content: str, fenced: str) -> None:
        self.content = content
        self.fenced = fenced
        self.usage = None
        self.cached = False


class DummyLLM:
    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload)

    def generate(self, *, messages, fence):  # type: ignore[override]
        content = f"{fence}\n{self._payload}\n{fence}"
        return DummyLLMResult(content=content, fenced=self._payload)


def test_strict_headers_skip_toc_lines() -> None:
    lines = [
        {
            "text": "1 OVERVIEW ........ 3",
            "global_idx": 0,
            "page": 0,
            "line_idx": 0,
            "is_toc": True,
            "is_index": False,
            "is_running": False,
        },
        {
            "text": "1 OVERVIEW",
            "global_idx": 2,
            "page": 1,
            "line_idx": 5,
            "is_toc": False,
            "is_index": False,
            "is_running": False,
        },
        {
            "text": "Overview details",
            "global_idx": 3,
            "page": 1,
            "line_idx": 6,
            "is_toc": False,
            "is_index": False,
            "is_running": False,
        },
        {
            "text": "1.1 Scope",
            "global_idx": 4,
            "page": 1,
            "line_idx": 7,
            "is_toc": False,
            "is_index": False,
            "is_running": False,
        },
        {
            "text": "Scope details",
            "global_idx": 5,
            "page": 1,
            "line_idx": 8,
            "is_toc": False,
            "is_index": False,
            "is_running": False,
        },
    ]

    payload = {
        "headers": [
            {"text": "1 OVERVIEW", "number": "1", "level": 1},
            {"text": "1.1 Scope", "number": "1.1", "level": 2},
        ]
    }
    llm = DummyLLM(payload)

    result = extract_headers_and_sections_strict(llm=llm, lines=lines)

    assert [header["start_global_index"] for header in result["headers"]] == [2, 4]
    assert result["sections"][0]["start_global_index"] == 2
    assert result["sections"][0]["end_global_index"] == 3
    assert result["sections"][1]["start_global_index"] == 4
    assert result["sections"][1]["end_global_index"] == 5


def test_strict_handles_confusable_numbers_and_spacing() -> None:
    lines = [
        {
            "text": "Intro text",
            "global_idx": 0,
            "page": 0,
            "line_idx": 0,
            "is_toc": False,
            "is_index": False,
            "is_running": False,
        },
        {
            "text": "1 \u2024 I\u00A0Purpose",
            "global_idx": 10,
            "page": 0,
            "line_idx": 1,
            "is_toc": False,
            "is_index": False,
            "is_running": False,
        },
    ]

    payload = {
        "headers": [
            {"text": "1.1 Purpose", "number": "1.1", "level": 2},
        ]
    }

    llm = DummyLLM(payload)
    result = extract_headers_and_sections_strict(llm=llm, lines=lines)

    assert [header["start_global_index"] for header in result["headers"]] == [10]


def test_strict_matches_appendix_split_across_two_lines() -> None:
    lines = [
        {
            "text": "APPENDIX A",
            "global_idx": 20,
            "page": 3,
            "line_idx": 0,
            "is_toc": False,
            "is_index": False,
            "is_running": False,
        },
        {
            "text": "SUBMITTALS AND FORMS",
            "global_idx": 21,
            "page": 3,
            "line_idx": 1,
            "is_toc": False,
            "is_index": False,
            "is_running": False,
        },
    ]

    payload = {
        "headers": [
            {
                "text": "Appendix A Submittals and Forms",
                "number": "APPENDIX A",
                "level": 1,
            }
        ]
    }

    llm = DummyLLM(payload)
    result = extract_headers_and_sections_strict(llm=llm, lines=lines)

    assert [header["start_global_index"] for header in result["headers"]] == [20]


def test_strict_title_only_fallback_when_number_missing() -> None:
    lines = []
    for idx, text in enumerate(
        [
            "Preface",
            "General",
            "Summary",
            "FOREWORD",
            "Details",
            "More details",
            "Closing",
        ]
    ):
        lines.append(
            {
                "text": text,
                "global_idx": idx + 100,
                "page": 0,
                "line_idx": idx,
                "is_toc": False,
                "is_index": False,
                "is_running": False,
            }
        )

    payload = {
        "headers": [
            {"text": "FOREWORD", "number": "1", "level": 1},
        ]
    }

    llm = DummyLLM(payload)
    result = extract_headers_and_sections_strict(llm=llm, lines=lines)

    assert [header["start_global_index"] for header in result["headers"]] == [103]
