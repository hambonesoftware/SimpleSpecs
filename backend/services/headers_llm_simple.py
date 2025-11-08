"""LLM-backed header extraction focused on simple JSON outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import anyio

from fastapi import HTTPException

from ..config import Settings
from ..services import openrouter_client
from .lines import get_fulltext

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "headers_simple.txt"


def _load_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except FileNotFoundError as exc:  # pragma: no cover - packaging error
        raise HTTPException(
            status_code=500,
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


class InvalidLLMJSONError(RuntimeError):
    """Raised when the LLM returns malformed JSON."""


def _write_log(log_path: Path, payload: str | Dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as handle:
        if isinstance(payload, str):
            handle.write(payload)
        else:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")


def _normalise_headers(raw: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    if not isinstance(raw, dict):
        raise InvalidLLMJSONError

    headers_value = raw.get("headers")
    if not isinstance(headers_value, list):
        raise InvalidLLMJSONError

    cleaned: List[Dict[str, Any]] = []
    for item in headers_value:
        if not isinstance(item, dict):
            raise InvalidLLMJSONError
        title = item.get("title")
        level = item.get("level")
        page = item.get("page")
        if not isinstance(title, str):
            raise InvalidLLMJSONError
        try:
            level_int = int(level)
            page_int = int(page)
        except (TypeError, ValueError):
            raise InvalidLLMJSONError
        cleaned.append({"title": title, "level": level_int, "page": page_int})

    return {"headers": cleaned}


def _strip_fences(payload: str) -> str:
    text = payload.strip()
    if text.startswith("```"):
        text = text[3:]
        stripped = text.lstrip()
        if stripped.lower().startswith("json"):
            text = stripped[4:]
        else:
            text = stripped
        if text.endswith("```"):
            text = text[: -3]
    return text.strip()


async def get_headers_llm_json(
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
        response_text = await anyio.to_thread.run_sync(
            lambda: openrouter_client.chat(
                messages,
                model=settings.headers_llm_model,
                temperature=0.0,
                timeout_read=settings.headers_llm_timeout_s,
            ),
        )
    except openrouter_client.OpenRouterError as exc:  # pragma: no cover - network failure
        raise HTTPException(
            status_code=502,
            detail="openrouter_error",
        ) from exc

    log_path = settings.headers_log_dir / f"headers_{document_id}_llm.json"

    try:
        parsed = json.loads(_strip_fences(response_text))
    except json.JSONDecodeError:
        _write_log(log_path, response_text)
        if settings.headers_llm_strict:
            raise InvalidLLMJSONError
        return {"headers": []}

    try:
        normalised = _normalise_headers(parsed)
    except InvalidLLMJSONError:
        _write_log(log_path, response_text)
        if settings.headers_llm_strict:
            raise
        return {"headers": []}

    _write_log(log_path, normalised)

    return normalised


__all__ = ["InvalidLLMJSONError", "get_headers_llm_json"]
