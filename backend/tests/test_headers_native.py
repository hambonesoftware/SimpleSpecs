from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from backend.services.document_pipeline import run_header_pipeline

GOLDEN = Path("backend/tests/golden")


def _running_header(page: fitz.Page, text: str) -> None:
    page.insert_text((72, 48), text, fontsize=9, fontname="helv")
    page.insert_text((72, 760), "Company Confidential" if "Sample" in text else "Draft", fontsize=9, fontname="helv")


def _create_sample1(path: Path) -> None:
    doc = fitz.open()

    # Page 1: table of contents
    page = doc.new_page()
    _running_header(page, "Sample Specification")
    page.insert_text((72, 120), "TABLE OF CONTENTS", fontsize=18, fontname="helv")
    toc_entries = [
        "1 Introduction ........ 2",
        "1.1 Background ........ 2",
        "1.1.1 Scope ........ 2",
        "II Materials ........ 3",
        "A Metals ........ 3",
        "A.1 Alloy Steel ........ 3",
        "A.1.1 Heat Treatment ........ 3",
        "III Conclusion ........ 3",
    ]
    y = 160
    for entry in toc_entries:
        page.insert_text((72, y), entry, fontsize=12, fontname="helv")
        y += 24

    # Page 2: numeric hierarchy
    page = doc.new_page()
    _running_header(page, "Sample Specification")
    page.insert_text((72, 140), "1 Introduction", fontsize=18, fontname="helv")
    page.insert_text((90, 180), "1.1 Background", fontsize=14, fontname="helv")
    page.insert_text((108, 216), "1.1.1 Scope", fontsize=12, fontname="helv")
    body = (
        "This section outlines the overall intent of the specification and provides context for subsequent sections.\n"
        "Text is intentionally verbose to create distinct line boxes for the parser."
    )
    page.insert_textbox(fitz.Rect(72, 240, 540, 720), body, fontsize=10, fontname="helv")

    # Page 3: roman + alphabetic hierarchy
    page = doc.new_page()
    _running_header(page, "Sample Specification")
    page.insert_text((72, 140), "II Materials", fontsize=18, fontname="helv")
    page.insert_text((90, 180), "A Metals", fontsize=14, fontname="helv")
    page.insert_text((108, 216), "A.1 Alloy Steel", fontsize=12, fontname="helv")
    page.insert_text((126, 252), "A.1.1 Heat Treatment", fontsize=12, fontname="helv")
    page.insert_text((72, 320), "III Conclusion", fontsize=18, fontname="helv")
    body = (
        "Metals are grouped by alloy characteristics with emphasis on processing considerations.\n"
        "The conclusion reiterates requirements."
    )
    page.insert_textbox(fitz.Rect(72, 360, 540, 720), body, fontsize=10, fontname="helv")

    doc.save(path)
    doc.close()


def _create_sample2(path: Path) -> None:
    doc = fitz.open()

    # Page 1: multi-column mix of numbering schemes
    page = doc.new_page()
    _running_header(page, "Dual Column Manual")
    left_x = 72
    right_x = 320
    page.insert_text((left_x, 120), "1 Overview", fontsize=18, fontname="helv")
    page.insert_text((left_x + 18, 160), "1.1 Layout", fontsize=14, fontname="helv")
    page.insert_text((left_x + 18, 200), "1.2 Electrical", fontsize=14, fontname="helv")
    page.insert_text((right_x, 120), "B Mechanical", fontsize=14, fontname="helv")
    page.insert_text((right_x + 18, 160), "B.1 Fasteners", fontsize=12, fontname="helv")
    body_left = (
        "Overview text describing the system layout in one column to exercise column detection."
    )
    body_right = "Mechanical notes reside in a secondary column to verify ordering logic."
    page.insert_textbox(fitz.Rect(left_x, 220, left_x + 180, 720), body_left, fontsize=10, fontname="helv")
    page.insert_textbox(fitz.Rect(right_x, 220, right_x + 180, 720), body_right, fontsize=10, fontname="helv")

    # Page 2: continuation with numeric + alphabetic headings
    page = doc.new_page()
    _running_header(page, "Dual Column Manual")
    page.insert_text((72, 140), "2 Testing", fontsize=18, fontname="helv")
    page.insert_text((90, 180), "2.1 Bench Tests", fontsize=14, fontname="helv")
    page.insert_text((108, 216), "2.1.1 Voltage Sweep", fontsize=12, fontname="helv")
    page.insert_text((90, 260), "C Field Trials", fontsize=14, fontname="helv")
    page.insert_text((108, 296), "C.1 Terrain", fontsize=12, fontname="helv")
    page.insert_textbox(
        fitz.Rect(72, 330, 540, 720),
        "Testing summaries appear on the second page and should maintain hierarchy integrity.",
        fontsize=10,
        fontname="helv",
    )

    doc.save(path)
    doc.close()


@pytest.fixture(scope="session")
def sample_pdfs(tmp_path_factory):
    base = tmp_path_factory.mktemp("pdf_samples")
    paths = {}
    sample1 = base / "sample1.pdf"
    sample2 = base / "sample2.pdf"
    _create_sample1(sample1)
    _create_sample2(sample2)
    paths["sample1"] = sample1
    paths["sample2"] = sample2
    return paths


def _titles(tree):
    names: list[str] = []

    def walk(nodes):
        for node in nodes:
            names.append(node["title"])
            walk(node.get("children", []))

    walk(tree)
    return names


def _max_depth(tree) -> int:
    depth = 0

    def walk(nodes, level):
        nonlocal depth
        for node in nodes:
            depth = max(depth, level)
            walk(node.get("children", []), level + 1)

    walk(tree, 1)
    return depth


@pytest.mark.parametrize(
    "sample, expected_top, expected_depth, forbidden",
    [
        (
            "sample1",
            ["1 Introduction", "II Materials", "III Conclusion"],
            3,
            {"Sample Specification", "Company Confidential", "TABLE OF CONTENTS"},
        ),
        ("sample2", ["1 Overview", "2 Testing"], 3, {"Dual Column Manual", "Draft"}),
    ],
)
def test_header_pipeline_matches_golden(
    sample_pdfs, sample: str, expected_top: list[str], expected_depth: int, forbidden: set[str]
) -> None:
    pdf_path = sample_pdfs[sample]
    golden_path = GOLDEN / f"{sample}_headers.json"
    assert golden_path.exists(), golden_path

    result = run_header_pipeline(str(pdf_path), debug=False)
    payload = result.to_dict()
    with golden_path.open("r", encoding="utf-8") as handle:
        golden = json.load(handle)

    assert payload == golden

    titles = [header.section_name for header in result.headers]
    numbered_titles = [f"{header.section_number} {header.section_name}".strip() for header in result.headers]
    for marker in forbidden:
        assert marker not in titles

    for expected in expected_top:
        assert expected in numbered_titles

    tree_titles = _titles(payload["tree"])
    for marker in forbidden:
        assert marker not in tree_titles

    assert _max_depth(payload["tree"]) >= expected_depth

    if sample == "sample1":
        assert any(item.section_number.startswith("II") for item in result.headers)
        assert any(item.section_number.startswith("A.1") for item in result.headers)
        assert any(item.section_number.startswith("A.1.1") for item in result.headers)
    if sample == "sample2":
        assert any(item.section_number.startswith("B") for item in result.headers)
        assert any(item.section_number.startswith("2.1.1") for item in result.headers)
