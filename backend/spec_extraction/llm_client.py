"""LLM adapter for per-section spec extraction."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Sequence

from backend.config import get_settings
from backend.services.llm import (
    LLMCircuitOpenError,
    LLMProviderError,
    LLMRetryableError,
    LLMService,
)

from . import agents

LOGGER = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    payload: Dict[str, Any]
    confidence: float | None = None


class LLMClient:
    """High-level adapter that orchestrates prompting, retries, and validation."""

    def __init__(
        self,
        *,
        primary_model: str | None = None,
        fallback_model: str | None = None,
        timeout_s: int | None = None,
        retry_max: int | None = None,
        backoff_s: float | None = None,
        llm_service: LLMService | None = None,
    ) -> None:
        settings = get_settings()
        self._primary_model = primary_model or settings.specs_primary_model
        self._fallback_model = fallback_model or settings.specs_fallback_model
        self._timeout_s = timeout_s or settings.specs_timeout_s
        self._retry_max = retry_max if retry_max is not None else settings.specs_retry_max
        self._backoff_s = backoff_s if backoff_s is not None else settings.specs_backoff_s
        self._service = llm_service or LLMService(settings)

    @property
    def timeout(self) -> int:
        return self._timeout_s

    async def extract_specs(self, text: str, agent_code: str, timeout_s: int | None = None) -> ExtractionResult:
        """Return the structured extraction payload for ``agent_code``."""

        section_title, section_text, page_start, page_end = self._coerce_payload(text)
        timeout = timeout_s or self._timeout_s
        normative = agents.contains_normative_language(section_text)

        attempt = 0
        messages: Sequence[Mapping[str, str]]
        retry_hint: str | None = None
        errors: list[str] = []
        payload: Dict[str, Any] | None = None

        while attempt <= self._retry_max:
            attempt += 1
            messages = agents.build_messages(
                agent_code=agent_code,
                section_title=section_title,
                section_text=section_text,
                page_start=page_start,
                page_end=page_end,
                retry_hint=retry_hint,
            )
            raw = await self._call_model(messages=messages, model=self._primary_model, timeout=timeout)
            payload, retry_hint = self._validate_or_retry(raw, errors)
            if payload is not None:
                break
            if self._backoff_s:
                await asyncio.sleep(self._backoff_s)

        if payload is None:
            raise RuntimeError(
                f"LLM failed to produce valid SIMPLEBUCKETS output after {attempt} attempts"
            )

        if normative and not payload.get("requirements") and self._fallback_model:
            LOGGER.info(
                "Normative tripwire triggered for agent=%s; invoking fallback model %s",
                agent_code,
                self._fallback_model,
            )
            fallback_messages = agents.build_messages(
                agent_code=agent_code,
                section_title=section_title,
                section_text=section_text,
                page_start=page_start,
                page_end=page_end,
                retry_hint="Source text contains normative language; ensure requirements are captured.",
            )
            raw = await self._call_model(
                messages=fallback_messages,
                model=self._fallback_model,
                timeout=timeout,
            )
            payload, _ = self._validate_or_retry(raw, errors=[], allow_retry=False)
            if payload is None:
                raise RuntimeError("Fallback model failed to produce valid SIMPLEBUCKETS output")

        confidence = self._estimate_confidence(payload)
        return ExtractionResult(payload=payload, confidence=confidence)

    async def _call_model(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        model: str,
        timeout: int,
    ) -> str:
        """Invoke the configured LLM provider asynchronously."""

        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: self._service.generate(
                    messages=messages,
                    model=model,
                    params={"temperature": 0, "timeout": timeout},
                ),
            )
        except (LLMRetryableError, LLMProviderError, LLMCircuitOpenError) as exc:
            LOGGER.error("LLM provider error model=%s: %s", model, exc)
            raise RuntimeError(str(exc)) from exc
        return result.content.strip()

    def _validate_or_retry(
        self,
        raw: str,
        errors: Iterable[str],
        *,
        allow_retry: bool = True,
    ) -> tuple[Dict[str, Any] | None, str | None]:
        """Validate ``raw`` and return payload plus retry hint if needed."""

        stripped = raw.strip()
        if stripped.upper() == "ABORT":
            raise RuntimeError("Agent returned ABORT")

        payload_text = agents.extract_payload(stripped)
        if payload_text is None:
            if not allow_retry:
                return None, None
            extended_errors = list(errors) + ["missing SIMPLEBUCKETS fence"]
            return None, agents.build_format_retry_hint(extended_errors)

        try:
            payload = agents.parse_payload(payload_text)
        except ValueError as exc:
            if not allow_retry:
                return None, None
            extended_errors = list(errors) + [str(exc)]
            return None, agents.build_format_retry_hint(extended_errors)
        return payload, None

    def _coerce_payload(self, raw: str) -> tuple[str, str, int | None, int | None]:
        """Return (title, text, page_start, page_end) from the caller input."""

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return "", raw, None, None
        if not isinstance(data, Mapping):
            return "", raw, None, None
        title = str(data.get("title") or "")
        text = str(data.get("text") or "")
        page_start = self._coerce_int(data.get("page_start"))
        page_end = self._coerce_int(data.get("page_end"))
        if not text:
            text = raw
        return title, text, page_start, page_end

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _estimate_confidence(self, payload: Mapping[str, Any]) -> float | None:
        requirements = payload.get("requirements")
        if not isinstance(requirements, list):
            return None
        if not requirements:
            return 0.0
        # Simple heuristic: more requirements => higher confidence capped at 0.95.
        score = min(0.5 + 0.1 * len(requirements), 0.95)
        return round(score, 3)


class MockLLMClient(LLMClient):
    """Deterministic client used for unit tests."""

    def __init__(self, responses: Mapping[tuple[str, str], Sequence[str]] | None = None) -> None:
        # Parent initialisation requires settings; we bypass service usage.
        super().__init__(llm_service=LLMService(get_settings()))  # type: ignore[arg-type]
        self._responses: dict[tuple[str, str], list[str]] = {
            key: list(value)
            for key, value in (responses or {}).items()
        }

    async def extract_specs(self, text: str, agent_code: str, timeout_s: int | None = None) -> ExtractionResult:
        key_primary = (agent_code, "primary")
        key_fallback = (agent_code, "fallback")
        if key_primary in self._responses and self._responses[key_primary]:
            raw = self._responses[key_primary].pop(0)
        else:
            raw = "ABORT"
        payload, retry_hint = self._validate_or_retry(raw, errors=[])
        if payload is None and retry_hint is not None:
            # simulate retry path using fallback list
            if key_primary in self._responses and self._responses[key_primary]:
                raw_retry = self._responses[key_primary].pop(0)
            else:
                raw_retry = "ABORT"
            payload, _ = self._validate_or_retry(raw_retry, errors=[], allow_retry=False)
        if payload is None and key_fallback in self._responses and self._responses[key_fallback]:
            raw_fb = self._responses[key_fallback].pop(0)
            payload, _ = self._validate_or_retry(raw_fb, errors=[], allow_retry=False)
        if payload is None:
            raise RuntimeError("Mock LLM produced no payload")
        return ExtractionResult(payload=payload, confidence=self._estimate_confidence(payload))
