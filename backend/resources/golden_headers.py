"""Golden header definitions for sample documents used in tests and reports."""

from __future__ import annotations

from typing import TypedDict


class GoldenHeader(TypedDict):
    """Type definition for a golden header entry."""

    text: str
    number: str
    level: int


MFC_5M_R2001_E1985: list[GoldenHeader] = [
    {"text": "1 GENERAL", "number": "1", "level": 1},
    {"text": "1.1 Scope", "number": "1.1", "level": 2},
    {"text": "1.2 Purpose", "number": "1.2", "level": 2},
    {"text": "1.3 Terminology, Symbols, and Definitions", "number": "1.3", "level": 2},
    {"text": "2 FLOWMETER DESCRIPTION", "number": "2", "level": 1},
    {"text": "2.1 Operating Principles", "number": "2.1", "level": 2},
    {"text": "2.1.1 Introduction", "number": "2.1.1", "level": 3},
    {"text": "2.1.2 Fluid Velocity Measurement", "number": "2.1.2", "level": 3},
    {"text": "2.1.3 Transducer Considerations", "number": "2.1.3", "level": 3},
    {"text": "2.2 Implementation", "number": "2.2", "level": 2},
    {"text": "2.2.1 Primary Device", "number": "2.2.1", "level": 3},
    {"text": "2.2.2 Secondary Device", "number": "2.2.2", "level": 3},
    {
        "text": "3 ERROR SOURCES AND THEIR REDUCTION",
        "number": "3",
        "level": 1,
    },
    {"text": "3.1 Axial Velocity Estimate", "number": "3.1", "level": 2},
    {"text": "3.2 Integration", "number": "3.2", "level": 2},
    {"text": "3.3 Computation", "number": "3.3", "level": 2},
    {"text": "3.4 Calibration", "number": "3.4", "level": 2},
    {"text": "3.5 Equipment Degradation", "number": "3.5", "level": 2},
    {
        "text": "4 APPLICATION GUIDELINES",
        "number": "4",
        "level": 1,
    },
    {"text": "4.1 Performance Parameters", "number": "4.1", "level": 2},
    {"text": "4.2 Installation Considerations", "number": "4.2", "level": 2},
    {
        "text": "5 METER FACTOR DETERMINATION\nAND VERIFICATION",
        "number": "5",
        "level": 1,
    },
    {"text": "5.1 Laboratory Calibration", "number": "5.1", "level": 2},
    {"text": "5.2 Field Calibration", "number": "5.2", "level": 2},
    {
        "text": "6 A Typical Cross Path Ultrasonic Flowmeter Configuration",
        "number": "6",
        "level": 1,
    },
]

__all__ = ["GoldenHeader", "MFC_5M_R2001_E1985"]
