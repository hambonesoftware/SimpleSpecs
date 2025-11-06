"""Tests for chunking and stitching utilities."""
from __future__ import annotations

from backend.spec_search.chunk import stitch_chunk_results
from backend.spec_search.models import BucketResult, Level, Requirement


def test_stitch_deduplicates_and_preserves_order() -> None:
    original = "Mount bracket shall be stainless. Calibrate sensors annually."
    chunk_results = [
        {
            "mechanical": BucketResult(
                requirements=[
                    Requirement(id="", text="Mount bracket shall be stainless.", level=Level.MUST, page_hint=1)
                ]
            ),
            "software": BucketResult(requirements=[]),
        },
        {
            "mechanical": BucketResult(
                requirements=[
                    Requirement(id="", text="Mount bracket shall be stainless.", level=Level.MUST, page_hint=1),
                    Requirement(id="", text="Calibrate sensors annually.", level=Level.SHOULD, page_hint=2),
                ]
            ),
            "software": BucketResult(requirements=[]),
        },
    ]

    stitched = stitch_chunk_results(original, chunk_results, ["mechanical", "software"])
    mechanical_reqs = stitched["mechanical"].requirements
    assert len(mechanical_reqs) == 2
    assert mechanical_reqs[0].text == "Mount bracket shall be stainless."
    assert mechanical_reqs[1].text == "Calibrate sensors annually."
