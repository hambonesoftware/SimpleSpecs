"""Specifications extraction endpoints."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any, List

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from ..models import HeaderItem, SpecItem, SpecsRequest
from ..services.llm import get_provider
from ..services.text_blocks import document_lines, section_text
from ..store import (
    headers_path,
    read_json,
    read_jsonl,
    specs_path,
    upload_objects_path,
    write_json,
)

router = APIRouter(prefix="/api")

_SPEC_PROMPT_TEMPLATE = """You are an expert mechanical engineering specification extraction system. Your task is to analyze the provided document section and identify ONLY mechanical engineering specifications.

SECTION CONTEXT:
Section Number: {section_number}
Section Name: {section_name}

INPUT TEXT:
{section_text}

CRITICAL INSTRUCTIONS:
1. Extract ONLY specifications that define REQUIREMENTS - these are mandatory, measurable, or verifiable statements
2. Focus exclusively on MECHANICAL ENGINEERING domains including:
   - Materials and metallurgy
   - Manufacturing processes and methods
   - Mechanical components and assemblies
   - Tolerances, fits, and dimensional constraints
   - Surface treatments and coatings
   - Fasteners and joining methods
   - Mechanical properties (strength, hardness, durability)
   - Thermal management and heat transfer
   - Fluid systems and hydraulics
   - Structural requirements and load ratings
   - Mechanical interfaces and connections
   - Wear resistance and service life
   - Corrosion protection
   - Mechanical testing methods
   - Duty cycles and operational limits
   - Environmental operating conditions
   - Mechanical safety factors
   - Industry standards (ASME, ASTM, ISO, SAE, etc.)

EXTRACTION CRITERIA:
- Must be a complete requirement statement
- Must contain measurable/verifiable criteria
- Must use original text VERBATIM - no paraphrasing
- Must be mechanically relevant (exclude electrical, software, etc.)
- Include standards references ONLY if mechanically relevant

OUTPUT FORMAT:
#specs#
- [Exact verbatim specification 1]
- [Exact verbatim specification 2]
- [Exact verbatim specification 3]
#specs#

If no mechanical engineering specifications are found, return:
#specs#
NONE
#specs#

EXAMPLES OF WHAT TO EXTRACT:
✓ "All structural steel shall comply with ASTM A36"
✓ "Surface finish shall be 32 μin Ra maximum"
✓ "Maximum operating temperature: 150°C"
✓ "Duty cycle: 50% continuous operation"
✓ "Tolerance: ±0.005 inches"
✓ "Material: 6061-T6 aluminum alloy"
✓ "Thread specification: UNC 1/4-20"
✓ "Safety factor: 4:1 minimum"

EXAMPLES OF WHAT TO EXCLUDE:
✗ "The system should be reliable" (vague, not measurable)
✗ "Electrical input: 120V AC" (electrical, not mechanical)
✗ "Software shall interface with PLC" (software-related)
✗ General descriptions without requirements
"""


SpecEvent = dict[str, Any]
NotifyCallback = Callable[[SpecEvent], Awaitable[None] | None]


def _ensure_status(event: SpecEvent) -> SpecEvent:
    """Return a shallow copy of an event with serializable data."""

    if "specs" in event:
        specs = event["specs"]
        if isinstance(specs, list):
            event = {**event, "specs": [spec for spec in specs]}
    return event


async def _notify(callback: NotifyCallback | None, event: SpecEvent) -> None:
    if not callback:
        return
    result = callback(_ensure_status(event))
    if asyncio.iscoroutine(result):
        await result


async def _collect_specs(payload: SpecsRequest, notify: NotifyCallback | None = None) -> list[SpecItem]:
    raw_objects = read_jsonl(upload_objects_path(payload.upload_id))
    if not raw_objects:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")

    headers_raw = read_json(headers_path(payload.upload_id))
    if not headers_raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Headers must be extracted before specifications",
        )

    headers = [HeaderItem.model_validate(item) for item in headers_raw]
    lines = document_lines(raw_objects)
    provider = get_provider(
        payload.provider,
        model=payload.model,
        params=payload.params,
        api_key=payload.api_key,
        base_url=payload.base_url,
    )

    specs: list[SpecItem] = []
    for header in headers:
        await _notify(
            notify,
            {
                "event": "request",
                "section_number": header.section_number,
                "section_name": header.section_name,
            },
        )
        text = header.chunk_text or section_text(lines, headers, header)
        prompt = _SPEC_PROMPT_TEMPLATE.format(
            section_number=header.section_number,
            section_name=header.section_name,
            section_text=text or "No additional text found for this section.",
        )
        messages = [
            {"role": "system", "content": "You extract mechanical engineering specifications."},
            {"role": "user", "content": prompt},
        ]
        response_text = await provider.chat(messages)
        await _notify(
            notify,
            {
                "event": "response",
                "section_number": header.section_number,
                "section_name": header.section_name,
            },
        )
        match = re.search(r"#specs#(.*?)#specs#", response_text, re.DOTALL | re.IGNORECASE)
        if not match:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"LLM returned unexpected format for section {header.section_number}",
            )
        block = match.group(1).strip()
        if not block or block.strip().upper() == "NONE":
            await _notify(
                notify,
                {
                    "event": "processed",
                    "section_number": header.section_number,
                    "section_name": header.section_name,
                    "specs": [],
                },
            )
            continue
        new_specs: list[SpecItem] = []
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line or line.upper() == "NONE":
                continue
            if line.startswith("-"):
                line = line[1:].strip()
            if not line:
                continue
            section_identifier = f"{payload.upload_id}|{header.section_number}|{header.section_name}"
            section_hash = hashlib.sha1(section_identifier.encode("utf-8")).hexdigest()
            spec_id_seed = f"{section_hash}|{line}"
            spec_id = hashlib.sha1(spec_id_seed.encode("utf-8")).hexdigest()
            spec_item = SpecItem(
                spec_id=spec_id,
                file_id=payload.upload_id,
                section_id=section_hash,
                section_number=header.section_number or None,
                section_title=header.section_name,
                spec_text=line,
                source_object_ids=[],
            )
            specs.append(spec_item)
            new_specs.append(spec_item)
        await _notify(
            notify,
            {
                "event": "processed",
                "section_number": header.section_number,
                "section_name": header.section_name,
                "specs": [spec.model_dump(mode="json") for spec in new_specs],
            },
        )

    serialized = [spec.model_dump(mode="json") for spec in specs]
    write_json(specs_path(payload.upload_id), serialized)
    await _notify(
        notify,
        {
            "event": "complete",
            "specs": serialized,
        },
    )
    return specs


@router.post("/specs", response_model=list[SpecItem])
async def extract_specs(payload: SpecsRequest) -> List[SpecItem]:
    return await _collect_specs(payload)


@router.post("/specs/stream")
async def stream_specs(payload: SpecsRequest) -> StreamingResponse:
    async def event_stream() -> Any:
        queue: asyncio.Queue[SpecEvent | None] = asyncio.Queue()

        async def emit(event: SpecEvent) -> None:
            await queue.put(event)

        async def producer() -> None:
            try:
                await _collect_specs(payload, emit)
            except HTTPException as exc:  # pragma: no cover - passthrough for clients
                await queue.put(
                    {
                        "event": "error",
                        "status": exc.status_code,
                        "message": exc.detail,
                    }
                )
            except Exception as exc:  # pragma: no cover - safety net for clients
                await queue.put(
                    {
                        "event": "error",
                        "status": status.HTTP_500_INTERNAL_SERVER_ERROR,
                        "message": str(exc),
                    }
                )
            finally:
                await queue.put(None)

        producer_task = asyncio.create_task(producer())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield json.dumps(item) + "\n"
        finally:
            await producer_task

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")
