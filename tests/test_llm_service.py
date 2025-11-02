"""Tests for the shared LLM service abstraction."""

from __future__ import annotations

from pathlib import Path
import pytest
from pytest import CaptureFixture

from backend.config import Settings
from backend.services.llm import (
    LLMCircuitOpenError,
    LLMRetryableError,
    LLMService,
    LLMTransportRequest,
    LLMTransportResponse,
)


def build_settings(tmp_path: Path) -> Settings:
    return Settings(
        upload_dir=tmp_path,
        llm_provider="openrouter",
        openrouter_api_key="test-key",
        openrouter_model="openrouter/test-model",
    )


def test_llm_service_uses_cache(tmp_path: Path) -> None:
    """Repeated calls with the same payload should hit the cache."""

    calls: dict[str, int] = {"count": 0}

    def fake_transport(request: LLMTransportRequest) -> LLMTransportResponse:
        calls["count"] += 1
        assert int(request.params["max_tokens"]) >= 120_000
        content = "#headers#\nMechanical\n#headers#"
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        return LLMTransportResponse(content=content, usage=usage)

    settings = build_settings(tmp_path)
    service = LLMService(
        settings,
        transport_overrides={"openrouter": fake_transport},
        sleep=lambda _: None,
        time_func=lambda: 0.0,
    )

    result_first = service.generate(
        messages=[{"role": "user", "content": "hello"}], fence="#headers#"
    )
    assert result_first.fenced == "Mechanical"
    assert not result_first.cached

    result_second = service.generate(
        messages=[{"role": "user", "content": "hello"}], fence="#headers#"
    )
    assert result_second.cached
    assert result_second.fenced == "Mechanical"
    assert calls["count"] == 1


def test_llm_service_retries_missing_fence(tmp_path: Path) -> None:
    """Missing fences should trigger a retry with an explicit preamble."""

    responses = [
        LLMTransportResponse(content="no fences here"),
        LLMTransportResponse(content='#classes#\n["mechanical"]\n#classes#'),
    ]
    requests: list[LLMTransportRequest] = []

    def fake_transport(request: LLMTransportRequest) -> LLMTransportResponse:
        requests.append(request)
        return responses[len(requests) - 1]

    settings = build_settings(tmp_path)
    service = LLMService(
        settings,
        transport_overrides={"openrouter": fake_transport},
        sleep=lambda _: None,
        time_func=lambda: 0.0,
    )

    result = service.generate(
        messages=[{"role": "user", "content": "classify"}], fence="#classes#"
    )
    assert result.fenced == '["mechanical"]'
    assert len(requests) == 2
    assert "ONLY FENCED OUTPUT" in requests[1].messages[0]["content"]


def test_llm_service_circuit_breaker(tmp_path: Path) -> None:
    """Repeated retryable failures should trip the circuit breaker."""

    attempts: dict[str, int] = {"count": 0}
    current_time = {"value": 0.0}

    def fake_time() -> float:
        return current_time["value"]

    def failing_transport(request: LLMTransportRequest) -> LLMTransportResponse:
        attempts["count"] += 1
        raise LLMRetryableError("rate limited")

    settings = build_settings(tmp_path)
    service = LLMService(
        settings,
        transport_overrides={"openrouter": failing_transport},
        sleep=lambda _: None,
        time_func=fake_time,
    )

    with pytest.raises(LLMRetryableError):
        service.generate(
            messages=[{"role": "user", "content": "outline"}], fence="#headers#"
        )
    assert attempts["count"] == service._max_retries + 1  # type: ignore[attr-defined]

    with pytest.raises(LLMCircuitOpenError):
        service.generate(
            messages=[{"role": "user", "content": "outline"}], fence="#headers#"
        )

    current_time["value"] = 100.0
    with pytest.raises(LLMRetryableError):
        service.generate(
            messages=[{"role": "user", "content": "outline"}], fence="#headers#"
        )
    assert attempts["count"] == 2 * (service._max_retries + 1)  # type: ignore[attr-defined]


def test_llm_service_echo_response_prints_full_message(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """The stdout echo should include the complete response without truncation."""

    settings = build_settings(tmp_path)
    service = LLMService(
        settings,
        transport_overrides={},
        sleep=lambda _: None,
        time_func=lambda: 0.0,
    )

    message = "First line of response\nSecond line with unicode ✓"
    service._echo_response(message)

    captured = capsys.readouterr()
    assert captured.out == message + "\n"
    assert captured.err == ""
