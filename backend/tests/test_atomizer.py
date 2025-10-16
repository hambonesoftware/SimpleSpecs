from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.spec_atomizer import atomize_section_text


def _find(items, needle):
    for item in items:
        if needle in item.spec_text:
            return item
    raise AssertionError(f"Spec containing '{needle}' not found")


def test_atomizer_normalizes_units_and_classifies() -> None:
    lines = [
        "- The enclosure shall be rated IP65 for outdoor service.",
        "Spacing shall be 2 cm between mounting holes.",
        "Panel must operate at 24 VDC ±10%.",
        "Software version should be 1.2.0 or later.",
        "Ambient temperature must not exceed 140 °F.",
        "General marketing copy.",
    ]

    items = atomize_section_text(
        file_id="file-1",
        section_id="sec-1",
        section_title="Controls",
        section_number="1.2",
        lines=lines,
        source_object_ids=["obj-1"],
    )

    assert len(items) == 5
    assert len({item.spec_id for item in items}) == len(items)
    assert all(item.spec_id.startswith("spec-") for item in items)
    assert all(item.source_object_ids == ["obj-1"] for item in items)

    spacing = _find(items, "Spacing shall")
    assert spacing.raw_value == "2 cm"
    assert spacing.normalized_unit == "mm"
    assert spacing.normalized_value == 20.0
    assert spacing.category == "dimensional"
    assert spacing.confidence == 1.0

    voltage = _find(items, "24 VDC")
    assert voltage.normalized_unit == "VDC"
    assert voltage.normalized_value == 24.0
    assert voltage.category == "electrical"
    assert voltage.confidence == 1.0

    software = _find(items, "Software version")
    assert software.category == "software"
    assert software.confidence == 0.8

    temperature = _find(items, "140 °F")
    assert temperature.normalized_unit == "degC"
    assert round(temperature.normalized_value or 0.0, 2) == 60.0
    assert temperature.category == "dimensional"
