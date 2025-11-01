"""LLM-backed header extraction focused on simple JSON outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from fastapi import HTTPException, status

from ..config import Settings
from ..services import openrouter_client
from .lines import get_fulltext

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "headers_simple.txt"


class InvalidLLMJSONError(RuntimeError):
    """Raised when the LLM returns malformed JSON."""


def _load_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except FileNotFoundError as exc:  # pragma: no cover - packaging error
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="LLM prompt template missing",
        ) from exc


def _chunk_document(fulltext: str, max_tokens: int) -> List[str]:
    if max_tokens <= 0:
        return [fulltext]
    approx_chars = max(1, max_tokens * 4)
    return [
        fulltext[index : index + approx_chars]
        for index in range(0, len(fulltext), approx_chars)
    ] or [fulltext]


def _write_log(log_path: Path, payload: str | Dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as handle:
        if isinstance(payload, str):
            handle.write(payload)
        else:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")


def _normalise_headers(
    raw: Dict[str, Any],
    *,
    strict: bool,
) -> Dict[str, List[Dict[str, Any]]]:
    headers_value = raw.get("headers") if isinstance(raw, dict) else None
    if not isinstance(headers_value, list):
        if strict:
            raise InvalidLLMJSONError
        return {"headers": []}

    cleaned: List[Dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    for item in headers_value:
        if not isinstance(item, dict):
            if strict:
                raise InvalidLLMJSONError
            continue
        title = item.get("title")
        level = item.get("level")
        page = item.get("page")
        if not isinstance(title, str):
            if strict:
                raise InvalidLLMJSONError
            continue
        try:
            level_int = int(level)
            page_int = int(page)
        except (TypeError, ValueError):
            if strict:
                raise InvalidLLMJSONError
            continue
        key = (title, level_int)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({"title": title, "level": level_int, "page": page_int})

    if strict and not cleaned:
        raise InvalidLLMJSONError

    return {"headers": cleaned}


def get_headers_llm_json(
    document_id: int,
    session,
    settings: Settings,
) -> Dict[str, List[Dict[str, Any]]]:
    """Call OpenRouter to obtain headers JSON for ``document_id``."""

    fulltext = get_fulltext(session, document_id)
    prompt = _load_prompt()

    chunks = _chunk_document(fulltext, settings.headers_llm_max_input_tokens)
    messages: List[Dict[str, str]] = [{"role": "system", "content": prompt}]
    total_chunks = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
        prefix = "Document text:\n"
        if total_chunks > 1:
            prefix = f"Document text (part {index}/{total_chunks}):\n"
        messages.append({"role": "user", "content": prefix + chunk})

    try:
        response_text = openrouter_client.chat(
            messages,
            model=settings.headers_llm_model,
            temperature=0.0,
            timeout_read=settings.headers_llm_timeout_s,
        )
    except openrouter_client.OpenRouterError as exc:  # pragma: no cover - network failure
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="openrouter_error",
        ) from exc

    log_path = settings.headers_log_dir / f"headers_{document_id}_llm.json"

    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError:
        _write_log(log_path, response_text)
        if settings.headers_llm_strict:
            raise InvalidLLMJSONError
        return {"headers": []}

    _write_log(log_path, parsed)

    try:
        normalised = _normalise_headers(parsed, strict=settings.headers_llm_strict)
    except InvalidLLMJSONError:
        raise

    return normalised


__all__ = ["InvalidLLMJSONError", "get_headers_llm_json"]
