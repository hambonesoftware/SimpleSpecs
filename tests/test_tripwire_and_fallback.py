"""Tests for normative tripwire and retry ladder."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.spec_search.extractor import extract_buckets
from backend.spec_search.models import AttemptReason
from backend.spec_search.reporting import SpecSearchReporter


EMPTY_PAYLOAD = """```SIMPLEBUCKETS\n{\n  \"mechanical\": {\"requirements\": []},\n  \"electrical\": {\"requirements\": []},\n  \"software\": {\"requirements\": []},\n  \"controls\": {\"requirements\": []}\n}\n```"""

VALID_FALLBACK = """```SIMPLEBUCKETS\n{\n  \"mechanical\": {\"requirements\": [{\"text\": \"The device shall provide redundant power supplies.\", \"level\": \"MUST\", \"page_hint\": 5}]},\n  \"electrical\": {\"requirements\": []},\n  \"software\": {\"requirements\": []},\n  \"controls\": {\"requirements\": []}\n}\n```"""


@pytest.mark.asyncio
async def test_normative_tripwire_escalates_and_uses_fallback(
    mock_llm, sample_text_normative, tmp_path
) -> None:
    mock_llm.enqueue(EMPTY_PAYLOAD)
    mock_llm.enqueue("ABORT")
    mock_llm.enqueue(EMPTY_PAYLOAD)
    mock_llm.enqueue(VALID_FALLBACK)

    log_dir = tmp_path / "spec_logs_normative"
    reporter = SpecSearchReporter(base_dir=log_dir, request_id="normative-test")

    response = await extract_buckets(sample_text_normative, llm_client=mock_llm, reporter=reporter)

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
    assert response.meta.log_path is not None
    log_path = Path(response.meta.log_path)
    if not log_path.is_absolute():
        log_path = Path.cwd() / log_path
    assert log_path.exists()
    assert log_path.stat().st_size > 0
