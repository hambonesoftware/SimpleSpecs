"""Golden header definitions for sample documents used in tests and reports."""

from __future__ import annotations

from typing import TypedDict


class GoldenHeader(TypedDict):
    """Type definition for a golden header entry."""

    text: str
    number: str
    level: int


MFC_5M_R2001_E1985: list[GoldenHeader] = [
    {"text": "1 General", "number": "1", "level": 1},
    {"text": "1.1 Scope and Field of Application", "number": "1.1", "level": 2},
    {"text": "1.2 References", "number": "1.2", "level": 2},
    {"text": "1.3 Definitions", "number": "1.3", "level": 2},
    {"text": "1.4 Symbols", "number": "1.4", "level": 2},
    {"text": "2 Principles", "number": "2", "level": 1},
    {"text": "2.1 Statement of the Principles", "number": "2.1", "level": 2},
    {"text": "2.1.1 Static Weighing", "number": "2.1.1", "level": 3},
    {"text": "2.1.2 Dynamic Weighing", "number": "2.1.2", "level": 3},
    {
        "text": "2.1.3 Comparison of Instantaneous and Mean Flow Rate",
        "number": "2.1.3",
        "level": 3,
    },
    {"text": "2.2 Accuracy of the Method", "number": "2.2", "level": 2},
    {
        "text": "2.2.1 Overall Uncertainty on the Weighing Measurement",
        "number": "2.2.1",
        "level": 3,
    },
    {
        "text": "2.2.2 Requirements for Accurate Measurements",
        "number": "2.2.2",
        "level": 3,
    },
    {"text": "3 Apparatus", "number": "3", "level": 1},
    {"text": "3.1 Diverter", "number": "3.1", "level": 2},
    {"text": "3.2 Time-Measuring Apparatus", "number": "3.2", "level": 2},
    {"text": "3.3 Weighing Tank", "number": "3.3", "level": 2},
    {"text": "3.4 Weighing Device", "number": "3.4", "level": 2},
    {"text": "3.5 Auxiliary Measurements", "number": "3.5", "level": 2},
    {"text": "4 Procedure", "number": "4", "level": 1},
    {"text": "4.1 Static Weighing Method", "number": "4.1", "level": 2},
    {"text": "4.2 Dynamic Weighing Method", "number": "4.2", "level": 2},
    {"text": "4.3 Common Provisions", "number": "4.3", "level": 2},
    {"text": "5 Calculation of Flow Rate", "number": "5", "level": 1},
    {"text": "5.1 Calculation of Mass Flow Rate", "number": "5.1", "level": 2},
    {"text": "5.2 Calculation of Volume Flow Rate", "number": "5.2", "level": 2},
    {
        "text": "6 Uncertainties in the Measurement of Flow Rate",
        "number": "6",
        "level": 1,
    },
]

__all__ = ["GoldenHeader", "MFC_5M_R2001_E1985"]
