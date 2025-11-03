import pytest

from backend.config import Settings
from backend.services.headers_sequential import (
    SequentialAlignmentConfig,
    align_headers_sequential,
)


@pytest.fixture()
def sequential_config() -> SequentialAlignmentConfig:
    settings = Settings()
    return SequentialAlignmentConfig.from_settings(settings)


def test_sequential_alignment_preserves_llm_order(sequential_config: SequentialAlignmentConfig) -> None:
    llm_headers = [
        {"number": "1", "title": "Introduction", "level": 1},
        {"number": "1.1", "title": "Purpose", "level": 2},
        {"number": "2", "title": "Scope", "level": 1},
    ]

    lines = [
        {"text": "1 Introduction", "page": 2, "global_idx": 10, "line_idx": 0},
        {"text": "1.1 Purpose", "page": 2, "global_idx": 15, "line_idx": 1},
        {"text": "2 Scope", "page": 3, "global_idx": 30, "line_idx": 0},
    ]

    result = align_headers_sequential(llm_headers, lines, config=sequential_config)
    assert [entry["number"] for entry in result] == ["1", "1.1", "2"]
    gids = [entry["global_idx"] for entry in result]
    assert gids == sorted(gids)
    assert [entry.get("source_idx") for entry in result] == [0, 1, 2]


def test_sequential_alignment_skips_toc_pages(sequential_config: SequentialAlignmentConfig) -> None:
    llm_headers = [
        {"number": "3", "title": "Quality Assurance", "level": 1},
    ]

    toc_lines = [
        {
            "text": f"{idx} Heading ........ {idx + 1}",
            "page": 1,
            "global_idx": idx,
            "line_idx": idx,
        }
        for idx in range(6)
    ]
    body_lines = [
        {"text": "3 Quality Assurance", "page": 2, "global_idx": 100, "line_idx": 0}
    ]
    lines = toc_lines + body_lines

    result = align_headers_sequential(llm_headers, lines, config=sequential_config)
    assert len(result) == 1
    entry = result[0]
    assert entry["global_idx"] == 100
    assert entry["page"] == 2
    assert entry.get("source_idx") == 0
