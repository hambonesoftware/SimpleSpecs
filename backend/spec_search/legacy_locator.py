"""Last-resort heuristic extractor when LLM attempts fail."""
from __future__ import annotations

import re
from typing import Dict, Iterable, List

from .models import BucketResult, Requirement
from .normalize import infer_level_from_text, normalize_requirement_text

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
BUCKET_KEYWORDS = {
    "mechanical": [
        "mount",
        "bolt",
        "housing",
        "calibration",
        "mechanical",
        "enclosure",
    ],
    "electrical": ["voltage", "current", "wiring", "power", "emi", "emc", "ground"],
    "software": ["firmware", "software", "update", "log", "data", "diagnostic"],
    "controls": ["control", "setpoint", "interlock", "hmi", "algorithm", "tuning"],
}


def _sentences(text: str) -> List[str]:
    chunks = SENTENCE_SPLIT.split(text.strip())
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _match_bucket(sentence: str, buckets: Iterable[str]) -> str | None:
    lowered = sentence.lower()
    for bucket in buckets:
        for keyword in BUCKET_KEYWORDS.get(bucket, []):
            if keyword in lowered:
                return bucket
    return None


def legacy_extract(text: str, buckets: Iterable[str]) -> Dict[str, BucketResult]:
    """Return bucket assignments using simple keyword heuristics."""

    results: Dict[str, BucketResult] = {bucket: BucketResult() for bucket in buckets}
    seen_signatures = set()
    for sentence in _sentences(text):
        bucket = _match_bucket(sentence, buckets)
        if not bucket:
            continue
        signature = (bucket, normalize_requirement_text(sentence))
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        requirement = Requirement(
            id="",
            text=sentence,
            level=infer_level_from_text(sentence),
            page_hint=None,
        )
        results[bucket].requirements.append(requirement)
    return results
