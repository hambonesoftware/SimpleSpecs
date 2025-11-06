"""Integration-style tests with mocked LLM responses."""
from __future__ import annotations

import pytest

from backend.spec_search.extractor import extract_buckets
from backend.spec_search.models import AttemptReason

VALID_CHUNK = """```SIMPLEBUCKETS\n{\n  \"mechanical\": {\"requirements\": [{\"text\": \"The enclosure shall be stainless steel.\", \"level\": \"MUST\", \"page_hint\": null}]},\n  \"electrical\": {\"requirements\": []},\n  \"software\": {\"requirements\": []},\n  \"controls\": {\"requirements\": []}\n}\n```"""


@pytest.mark.asyncio
async def test_retry_ladder_eventual_success(mock_llm, sample_text_simple) -> None:
    mock_llm.enqueue("json []")
    mock_llm.enqueue("ABORT")
    mock_llm.enqueue(VALID_CHUNK)

    response = await extract_buckets(sample_text_simple, llm_client=mock_llm)

    assert response.ok is True
    assert response.data is not None
    attempts = response.meta.attempts
    assert [attempt.rung for attempt in attempts] == ["try-1", "try-2", "chunked"]
    assert attempts[0].reason == AttemptReason.BAD_LABEL
    assert attempts[1].reason == AttemptReason.ABORT_TOKEN
    assert attempts[2].reason == AttemptReason.OK
    mech = response.data.buckets["mechanical"].requirements
    assert mech and mech[0].text.startswith("The enclosure shall")
    assert mech[0].id.startswith("m-")
