"""Unit tests for the specification extraction service."""

from __future__ import annotations

from pathlib import Path

from backend.config import Settings
from backend.services.pdf_native import ParsedBlock, ParsedPage, ParseResult
from backend.services.spec_extraction import extract_specifications

TERMS_DIR = Path("backend/resources/terms").resolve()


def build_sample_parse_result() -> ParseResult:
    """Construct an in-memory parse result representing a mini spec document."""

    blocks = [
        ParsedBlock(
            text=(
                "1.0 Mechanical Requirements\n"
                "- Maintain pressure at 120 psi.\n"
                "- Motor shall deliver torque not less than 300 Nm.\n"
                "- Coordinate mechanical and electrical interfaces.\n"
            ),
            bbox=(0.0, 0.0, 200.0, 50.0),
        ),
        ParsedBlock(
            text=(
                "Electrical Requirements:\n"
                "- Provide 24V supply to the control cabinet.\n"
                "- Route wiring through shielded cable.\n"
            ),
            bbox=(0.0, 60.0, 200.0, 110.0),
        ),
        ParsedBlock(
            text=(
                "Controls and Software\n"
                "1) PLC shall coordinate the PID loop.\n"
                "2) Update firmware and HMI screens quarterly.\n"
            ),
            bbox=(0.0, 120.0, 200.0, 170.0),
        ),
        ParsedBlock(
            text=(
                "Project Management\n"
                "- Submit monthly progress report to stakeholders.\n"
                "- Review schedule and risk register.\n"
            ),
            bbox=(0.0, 180.0, 200.0, 230.0),
        ),
        ParsedBlock(
            text="- General instructions apply.",
            bbox=(0.0, 240.0, 200.0, 260.0),
        ),
    ]

    page = ParsedPage(page_number=0, width=612.0, height=792.0, blocks=blocks)
    return ParseResult(pages=[page])


def test_spec_extraction_precision_recall(tmp_path) -> None:
    """The rule-based classifier should achieve a high F1 score on the sample."""

    parse_result = build_sample_parse_result()
    settings = Settings(
        upload_dir=tmp_path,
        spec_terms_dir=TERMS_DIR,
        spec_rule_min_hits=1,
        spec_multi_label_margin=0.0,
    )

    extraction = extract_specifications(parse_result, settings=settings)

    expected_labels = {
        "Maintain pressure at 120 psi.": {"mechanical"},
        "Motor shall deliver torque not less than 300 Nm.": {"mechanical"},
        "Coordinate mechanical and electrical interfaces.": {
            "mechanical",
            "electrical",
        },
        "Provide 24V supply to the control cabinet.": {"electrical"},
        "Route wiring through shielded cable.": {"electrical"},
        "PLC shall coordinate the PID loop.": {"controls"},
        "Update firmware and HMI screens quarterly.": {"controls", "software"},
        "Submit monthly progress report to stakeholders.": {"project_management"},
        "Review schedule and risk register.": {"project_management"},
    }

    predictions: dict[str, set[str]] = {}
    for line in extraction.lines:
        if line.text in expected_labels:
            predictions[line.text] = set(line.disciplines or {"unknown"})

    missing = set(expected_labels) - set(predictions)
    assert not missing, f"Expected lines missing from predictions: {missing}"

    tp = fp = fn = 0
    for text, expected in expected_labels.items():
        predicted = predictions.get(text, {"unknown"})
        tp += len(expected & predicted)
        fp += len(predicted - expected)
        fn += len(expected - predicted)

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0

    assert precision >= 0.9
    assert recall >= 0.9
    assert f1 >= 0.9

    unknown_bucket = extraction.to_dict()["unknown"]
    unknown_texts = {item["text"] for item in unknown_bucket}
    assert "General instructions apply." in unknown_texts


def test_spec_extraction_cross_discipline(tmp_path) -> None:
    """Cross-discipline phrases should retain multiple labels when applicable."""

    parse_result = build_sample_parse_result()
    settings = Settings(
        upload_dir=tmp_path,
        spec_terms_dir=TERMS_DIR,
        spec_rule_min_hits=1,
        spec_multi_label_margin=0.0,
    )

    extraction = extract_specifications(parse_result, settings=settings)
    target_text = "Coordinate mechanical and electrical interfaces."
    target_line = next(line for line in extraction.lines if line.text == target_text)

    assert {"mechanical", "electrical"}.issubset(set(target_line.disciplines))
