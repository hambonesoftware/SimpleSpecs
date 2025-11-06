"""Tests for normative tripwire and retry ladder."""
from __future__ import annotations

import pytest

from backend.spec_search.extractor import extract_buckets
from backend.spec_search.models import AttemptReason


EMPTY_PAYLOAD = """```SIMPLEBUCKETS\n{\n  \"mechanical\": {\"requirements\": []},\n  \"electrical\": {\"requirements\": []},\n  \"software\": {\"requirements\": []},\n  \"controls\": {\"requirements\": []}\n}\n```"""

VALID_FALLBACK = """```SIMPLEBUCKETS\n{\n  \"mechanical\": {\"requirements\": [{\"text\": \"The device shall provide redundant power supplies.\", \"level\": \"MUST\", \"page_hint\": 5}]},\n  \"electrical\": {\"requirements\": []},\n  \"software\": {\"requirements\": []},\n  \"controls\": {\"requirements\": []}\n}\n```"""


@pytest.mark.asyncio
async def test_normative_tripwire_escalates_and_uses_fallback(mock_llm, sample_text_normative) -> None:
    mock_llm.enqueue(EMPTY_PAYLOAD)
    mock_llm.enqueue("ABORT")
    mock_llm.enqueue(EMPTY_PAYLOAD)
    mock_llm.enqueue(VALID_FALLBACK)

    response = await extract_buckets(sample_text_normative, llm_client=mock_llm)

    assert response.ok is True
    assert response.data is not None
    attempts = response.meta.attempts
    assert [attempt.rung for attempt in attempts] == ["try-1", "try-2", "chunked", "fallback-model"]
    assert attempts[0].reason == AttemptReason.EMPTY
    assert attempts[1].reason == AttemptReason.ABORT_TOKEN
    assert attempts[2].reason == AttemptReason.EMPTY
    assert attempts[3].reason == AttemptReason.OK
    mechanical = response.data.buckets["mechanical"].requirements
    assert mechanical and mechanical[0].level.value == "MUST"
    models = [attempt.model for attempt in attempts]
    assert models[-1] != models[0]
