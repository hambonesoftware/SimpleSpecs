"""Main orchestration for the spec-search pipeline."""
from __future__ import annotations

import asyncio
from typing import Dict, List, Optional, Sequence

from backend.config import spec_search_settings
from backend.llm_client import LLMClient, LLMRequest, create_default_client

from .chunk import approximate_tokens, chunk_text, stitch_chunk_results
from .legacy_locator import legacy_extract
from .models import (
    AttemptReason,
    AttemptTelemetry,
    BucketResult,
    SpecSearchData,
    SpecSearchMeta,
    SpecSearchResponse,
)
from .normalize import detect_normative_terms, next_requirement_id
from .prompt import SYSTEM_PROMPT, build_user_prompt
from .validators import AbortSignal, ValidationError, dedupe_requirements, validate_schema

DEFAULT_BUCKETS = ["mechanical", "electrical", "software", "controls"]


def _build_attempt(
    rung: str, model: str, input_tokens: int, response_bytes: int, parsed: bool, reason: AttemptReason
) -> AttemptTelemetry:
    return AttemptTelemetry(
        rung=rung, model=model, input_tokens_est=input_tokens, response_bytes=response_bytes, parsed=parsed, reason=reason
    )


def _assign_ids(bucket_results: Dict[str, BucketResult]) -> Dict[str, BucketResult]:
    for bucket, result in bucket_results.items():
        for index, requirement in enumerate(result.requirements, start=1):
            requirement.id = next_requirement_id(bucket, index)
    return bucket_results


async def _sleep_backoff(attempt_index: int) -> None:
    delay = spec_search_settings.BACKOFF_S * (2 ** attempt_index)
    if delay <= 0:
        return
    await asyncio.sleep(min(delay, 0.05))


async def _call_model(
    client: LLMClient,
    model: str,
    user_prompt: str,
    max_tokens: int,
    timeout: int,
) -> str:
    request = LLMRequest(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        timeout=timeout,
        max_tokens=max_tokens,
    )
    return await client.complete(request)


async def extract_buckets(
    text: str,
    buckets: Sequence[str] | None = None,
    llm_client: Optional[LLMClient] = None,
) -> SpecSearchResponse:
    """Run the extraction retry ladder and return a stable response."""

    if buckets is None:
        buckets = DEFAULT_BUCKETS
    bucket_list = list(dict.fromkeys(bucket.lower() for bucket in buckets))
    client = llm_client or create_default_client()
    meta = SpecSearchMeta()
    normative_hits = detect_normative_terms(text)

    success_payload: Optional[Dict[str, BucketResult]] = None
    rung_plan = [
        "try-1",
        "try-2",
        "chunked",
        "fallback-model",
        "legacy",
    ]

    async def record_and_wait(attempt: AttemptTelemetry, attempt_index: int) -> None:
        meta.attempts.append(attempt)
        if attempt.rung != "legacy" and attempt.reason != AttemptReason.OK:
            await _sleep_backoff(attempt_index)

    for attempt_index, rung in enumerate(rung_plan):
        if rung == "try-1":
            prompt = build_user_prompt(text, bucket_list)
            try:
                raw = await _call_model(
                    client,
                    spec_search_settings.PRIMARY_MODEL,
                    prompt,
                    spec_search_settings.MAX_TOKENS,
                    spec_search_settings.TIMEOUT_S,
                )
                validated = validate_schema(raw, bucket_list)
                dedupe_requirements(validated)
                validated = _assign_ids(validated)
                total_requirements = sum(len(b.requirements) for b in validated.values())
                parsed = True
                reason = AttemptReason.OK
                if normative_hits > 0 and total_requirements == 0:
                    reason = AttemptReason.EMPTY
                attempt = _build_attempt(
                    rung,
                    spec_search_settings.PRIMARY_MODEL,
                    approximate_tokens(prompt),
                    len(raw.encode("utf-8")),
                    parsed,
                    reason,
                )
                await record_and_wait(attempt, attempt_index)
                if reason is AttemptReason.OK:
                    success_payload = validated
                    break
                continue
            except AbortSignal:
                attempt = _build_attempt(
                    rung,
                    spec_search_settings.PRIMARY_MODEL,
                    approximate_tokens(prompt),
                    0,
                    False,
                    AttemptReason.ABORT_TOKEN,
                )
                await record_and_wait(attempt, attempt_index)
                continue
            except ValidationError as exc:
                mapped = AttemptReason.MISSING_FENCE
                if exc.reason == "bad_label_or_shape":
                    mapped = AttemptReason.BAD_LABEL
                elif exc.reason == "invalid_json":
                    mapped = AttemptReason.INVALID_JSON
                attempt = _build_attempt(
                    rung,
                    spec_search_settings.PRIMARY_MODEL,
                    approximate_tokens(prompt),
                    0,
                    False,
                    mapped,
                )
                await record_and_wait(attempt, attempt_index)
                continue
            except Exception:
                attempt = _build_attempt(
                    rung,
                    spec_search_settings.PRIMARY_MODEL,
                    approximate_tokens(prompt),
                    0,
                    False,
                    AttemptReason.OTHER,
                )
                await record_and_wait(attempt, attempt_index)
                continue
        elif rung == "try-2":
            prompt = build_user_prompt(text, bucket_list) + "\nFormat reminder: respond only with the SIMPLEBUCKETS fence."
            try:
                raw = await _call_model(
                    client,
                    spec_search_settings.PRIMARY_MODEL,
                    prompt,
                    max(spec_search_settings.MAX_TOKENS // 2, 4096),
                    spec_search_settings.TIMEOUT_S,
                )
                validated = validate_schema(raw, bucket_list)
                dedupe_requirements(validated)
                validated = _assign_ids(validated)
                total_requirements = sum(len(b.requirements) for b in validated.values())
                reason = AttemptReason.OK
                if normative_hits > 0 and total_requirements == 0:
                    reason = AttemptReason.EMPTY
                attempt = _build_attempt(
                    rung,
                    spec_search_settings.PRIMARY_MODEL,
                    approximate_tokens(prompt),
                    len(raw.encode("utf-8")),
                    True,
                    reason,
                )
                await record_and_wait(attempt, attempt_index)
                if reason is AttemptReason.OK:
                    success_payload = validated
                    break
                continue
            except AbortSignal:
                attempt = _build_attempt(
                    rung,
                    spec_search_settings.PRIMARY_MODEL,
                    approximate_tokens(prompt),
                    0,
                    False,
                    AttemptReason.ABORT_TOKEN,
                )
                await record_and_wait(attempt, attempt_index)
                continue
            except ValidationError as exc:
                mapped = AttemptReason.MISSING_FENCE
                if exc.reason == "bad_label_or_shape":
                    mapped = AttemptReason.BAD_LABEL
                elif exc.reason == "invalid_json":
                    mapped = AttemptReason.INVALID_JSON
                attempt = _build_attempt(
                    rung,
                    spec_search_settings.PRIMARY_MODEL,
                    approximate_tokens(prompt),
                    0,
                    False,
                    mapped,
                )
                await record_and_wait(attempt, attempt_index)
                continue
            except Exception:
                attempt = _build_attempt(
                    rung,
                    spec_search_settings.PRIMARY_MODEL,
                    approximate_tokens(prompt),
                    0,
                    False,
                    AttemptReason.OTHER,
                )
                await record_and_wait(attempt, attempt_index)
                continue
        elif rung == "chunked":
            chunks = chunk_text(text, spec_search_settings.CHUNK_TARGET_TOKENS)
            chunk_payloads: List[Dict[str, BucketResult]] = []
            total_bytes = 0
            failure_reason: AttemptReason | None = None
            for chunk_index, chunk in enumerate(chunks, start=1):
                prompt = build_user_prompt(chunk, bucket_list) + f"\n(Chunk {chunk_index}/{len(chunks)})"
                try:
                    raw = await _call_model(
                        client,
                        spec_search_settings.PRIMARY_MODEL,
                        prompt,
                        spec_search_settings.MAX_TOKENS,
                        spec_search_settings.TIMEOUT_S,
                    )
                    total_bytes += len(raw.encode("utf-8"))
                    validated = validate_schema(raw, bucket_list)
                    dedupe_requirements(validated)
                    chunk_payloads.append(validated)
                except AbortSignal:
                    failure_reason = AttemptReason.ABORT_TOKEN
                    break
                except ValidationError as exc:
                    if exc.reason == "bad_label_or_shape":
                        failure_reason = AttemptReason.BAD_LABEL
                    elif exc.reason == "invalid_json":
                        failure_reason = AttemptReason.INVALID_JSON
                    else:
                        failure_reason = AttemptReason.MISSING_FENCE
                    break
                except Exception:
                    failure_reason = AttemptReason.OTHER
                    break
            token_estimate = sum(
                approximate_tokens(build_user_prompt(chunk, bucket_list)) for chunk in chunks
            )
            if failure_reason is None:
                stitched = stitch_chunk_results(text, chunk_payloads, bucket_list)
                stitched = _assign_ids(stitched)
                total_requirements = sum(len(b.requirements) for b in stitched.values())
                reason = AttemptReason.OK
                if normative_hits > 0 and total_requirements == 0:
                    reason = AttemptReason.EMPTY
                attempt = _build_attempt(
                    rung,
                    spec_search_settings.PRIMARY_MODEL,
                    token_estimate,
                    total_bytes,
                    True,
                    reason,
                )
                await record_and_wait(attempt, attempt_index)
                if reason is AttemptReason.OK:
                    success_payload = stitched
                    break
            else:
                attempt = _build_attempt(
                    rung,
                    spec_search_settings.PRIMARY_MODEL,
                    token_estimate,
                    total_bytes,
                    False,
                    failure_reason,
                )
                await record_and_wait(attempt, attempt_index)
            continue
        elif rung == "fallback-model":
            prompt = build_user_prompt(text, bucket_list)
            try:
                raw = await _call_model(
                    client,
                    spec_search_settings.FALLBACK_MODEL,
                    prompt,
                    spec_search_settings.MAX_TOKENS,
                    spec_search_settings.TIMEOUT_S,
                )
                validated = validate_schema(raw, bucket_list)
                dedupe_requirements(validated)
                validated = _assign_ids(validated)
                total_requirements = sum(len(b.requirements) for b in validated.values())
                reason = AttemptReason.OK
                if normative_hits > 0 and total_requirements == 0:
                    reason = AttemptReason.EMPTY
                attempt = _build_attempt(
                    rung,
                    spec_search_settings.FALLBACK_MODEL,
                    approximate_tokens(prompt),
                    len(raw.encode("utf-8")),
                    True,
                    reason,
                )
                await record_and_wait(attempt, attempt_index)
                if reason is AttemptReason.OK:
                    success_payload = validated
                    break
                continue
            except AbortSignal:
                attempt = _build_attempt(
                    rung,
                    spec_search_settings.FALLBACK_MODEL,
                    approximate_tokens(prompt),
                    0,
                    False,
                    AttemptReason.ABORT_TOKEN,
                )
                await record_and_wait(attempt, attempt_index)
                continue
            except ValidationError as exc:
                mapped = AttemptReason.MISSING_FENCE
                if exc.reason == "bad_label_or_shape":
                    mapped = AttemptReason.BAD_LABEL
                elif exc.reason == "invalid_json":
                    mapped = AttemptReason.INVALID_JSON
                attempt = _build_attempt(
                    rung,
                    spec_search_settings.FALLBACK_MODEL,
                    approximate_tokens(prompt),
                    0,
                    False,
                    mapped,
                )
                await record_and_wait(attempt, attempt_index)
                continue
            except Exception:
                attempt = _build_attempt(
                    rung,
                    spec_search_settings.FALLBACK_MODEL,
                    approximate_tokens(prompt),
                    0,
                    False,
                    AttemptReason.OTHER,
                )
                await record_and_wait(attempt, attempt_index)
                continue
        elif rung == "legacy":
            legacy_payload = legacy_extract(text, bucket_list)
            legacy_payload = _assign_ids(legacy_payload)
            total_requirements = sum(len(b.requirements) for b in legacy_payload.values())
            reason = AttemptReason.OK
            if normative_hits > 0 and total_requirements == 0:
                reason = AttemptReason.EMPTY
                meta.warnings.append("normative_tripwire_triggered_empty_result")
            attempt = _build_attempt(
                rung,
                "legacy",
                approximate_tokens(text),
                0,
                True,
                reason,
            )
            await record_and_wait(attempt, attempt_index)
            success_payload = legacy_payload
            break

    if success_payload is not None:
        response = SpecSearchResponse(ok=True, data=SpecSearchData(success_payload), meta=meta)
        return response

    return SpecSearchResponse(
        ok=False,
        error="Failed to extract requirements",
        data=SpecSearchData.empty(bucket_list),
        meta=meta,
    )
