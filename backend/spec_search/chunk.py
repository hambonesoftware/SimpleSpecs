"""Chunking utilities for large LLM prompts."""
from __future__ import annotations

from typing import Dict, Iterable, List

from .models import BucketResult, Requirement
from .normalize import normalize_requirement_text


def approximate_tokens(text: str) -> int:
    """Rough token estimation using a 4-characters-per-token heuristic."""

    if not text:
        return 0
    return max(1, len(text) // 4)


def chunk_text(text: str, target_tokens: int, overlap_ratio: float = 0.05) -> List[str]:
    """Split text into manageable windows that respect the token budget."""

    if approximate_tokens(text) <= target_tokens:
        return [text]
    chunk_size = max(1, int(target_tokens * 4))
    overlap = int(chunk_size * overlap_ratio)
    overlap = min(overlap, chunk_size // 2)
    windows: List[str] = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(text_len, start + chunk_size)
        window = text[start:end]
        windows.append(window.strip())
        if end >= text_len:
            break
        start = max(0, end - overlap)
    return [w for w in windows if w]


def stitch_chunk_results(
    original_text: str,
    chunk_results: List[Dict[str, BucketResult]],
    bucket_order: Iterable[str],
) -> Dict[str, BucketResult]:
    """Merge chunk payloads while deduplicating overlapping requirements."""

    aggregated: Dict[str, BucketResult] = {bucket: BucketResult() for bucket in bucket_order}
    for bucket in aggregated:
        aggregated[bucket].requirements = []
    seen = {}
    original_lower = original_text.lower()
    for result in chunk_results:
        for bucket, bucket_payload in result.items():
            target_list = aggregated.setdefault(bucket, BucketResult())
            if not bucket_payload.requirements:
                continue
            for requirement in bucket_payload.requirements:
                signature = (
                    normalize_requirement_text(requirement.text),
                    requirement.page_hint,
                )
                if signature in seen:
                    continue
                seen[signature] = requirement
                target_list.requirements.append(requirement)
    # Ensure deterministic order by source location fallback
    for bucket, bucket_payload in aggregated.items():
        def sort_key(req: Requirement) -> int:
            snippet = req.text[:64].lower()
            idx = original_lower.find(snippet)
            if idx >= 0:
                return idx
            first_token = req.text.split()
            if first_token:
                idx = original_lower.find(first_token[0].lower())
                if idx >= 0:
                    return idx
            return len(original_lower) + 1

        bucket_payload.requirements.sort(key=sort_key)
    return aggregated
