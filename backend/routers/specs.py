"""Specifications extraction endpoints."""
from __future__ import annotations

import hashlib
import re
from typing import List

from fastapi import APIRouter, HTTPException

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

_SPEC_PROMPT_TEMPLATE = """You are extracting mechanical engineering specifications from a single section of a document.

Section number: {section_number}
Section name: {section_name}

Section text:
{section_text}

Task: List ONLY the exact specification statements in this section that define requirements (methods, processes, specific parts, materials, tolerances, ratings, standards, environmental constraints, duty cycles, etc.). Return each specification as its original text (verbatim), one per line. If none, return "NONE".

Output format (fenced):
#specs#
- <spec 1>
- <spec 2>
#specs#
"""


@router.post("/specs", response_model=list[SpecItem])
async def extract_specs(payload: SpecsRequest) -> List[SpecItem]:
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
        text = section_text(lines, headers, header)
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
        match = re.search(r"#specs#(.*?)#specs#", response_text, re.DOTALL | re.IGNORECASE)
        if not match:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"LLM returned unexpected format for section {header.section_number}",
            )
        block = match.group(1).strip()
        if not block or block.strip().upper() == "NONE":
            continue
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
            specs.append(
                SpecItem(
                    spec_id=spec_id,
                    file_id=payload.upload_id,
                    section_id=section_hash,
                    section_number=header.section_number or None,
                    section_title=header.section_name,
                    spec_text=line,
                    source_object_ids=[],
                )
            )

    write_json(
        specs_path(payload.upload_id),
        [spec.model_dump(mode="json") for spec in specs],
    )
    return specs
