"""Ensure prompt templates capture required guidance."""
from __future__ import annotations

from backend.spec_search import prompt


def test_system_prompt_contains_contract() -> None:
    assert "SIMPLEBUCKETS" in prompt.SYSTEM_PROMPT
    assert "ABORT" in prompt.SYSTEM_PROMPT


def test_user_prompt_mentions_buckets() -> None:
    rendered = prompt.build_user_prompt("example text", ["mechanical", "software"])
    assert "Mechanical" in rendered
    assert "Software" in rendered
    assert "shall" in rendered.lower()
