
"""
specs_worker: runs the Specs "buckets" in parallel against an LLM.
This module is intentionally self-contained so it can be dropped into the project
without touching the rest of the pipeline. It will:

- Load the parsed text for a document from the artifact_store if available (PARSED_TEXT).
  If not available, it will try to locate the uploaded PDF bytes and parse them here.
- Fire off multiple prompt calls concurrently (one per bucket) to the configured LLM.
- Return a dictionary with per-bucket results and light metadata.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import Session

# Attempt project-local imports; keep soft fallbacks so this stays drop-in.
from backend.models import Document, DocumentArtifactType  # type: ignore
from backend.services.artifact_store import (
    get_cached_artifact,
    store_artifact,
)  # type: ignore

# ---------- Configuration (env-driven so we don't edit config module) ----------
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
SPECS_LLM_MODEL = os.getenv("SPECS_LLM_MODEL", os.getenv("HEADERS_LLM_MODEL", "anthropic/claude-3.5-sonnet"))
SPECS_LLM_TIMEOUT_S = float(os.getenv("SPECS_LLM_TIMEOUT_S", "120"))
SPECS_MAX_CONCURRENCY = int(os.getenv("SPECS_MAX_CONCURRENCY", "4"))

# Artifact constants
PARSED_TEXT_ARTIFACT_TYPE = getattr(DocumentArtifactType, "PARSED_TEXT", DocumentArtifactType.HEADER_TREE)
SPEC_BUCKET_ARTIFACT_TYPE = getattr(DocumentArtifactType, "SPEC_BUCKETS", DocumentArtifactType.JSON if hasattr(DocumentArtifactType, "JSON") else DocumentArtifactType.HEADER_TREE)
BUCKET_ARTIFACT_KEY = "spec_buckets"

# ------------- Bucket definitions (minimal examples; extend as needed) ---------
# Each bucket has a "name" and a "prompt" template. The document text is appended.
# You can add your own prompts or swap these for your existing ones.
BUCKETS: List[Dict[str, str]] = [
    {"name": "mechanical", "prompt": "Extract a JSON list of mechanical specifications and units relevant to this document. Be concise and structured.\n\n-- Document --\n"},
    {"name": "electrical", "prompt": "Extract a JSON list of electrical specifications (voltages, currents, interfaces). Be concise and structured.\n\n-- Document --\n"},
    {"name": "controls", "prompt": "Extract a JSON list of PLC/HMI/controls-related specs and signals. Be concise and structured.\n\n-- Document --\n"},
    {"name": "software", "prompt": "Extract a JSON list of software-related requirements (APIs, protocols, versions). Be concise and structured.\n\n-- Document --\n"},
]

# ---------- Utilities ----------------------------------------------------------
async def _openrouter_chat(prompt: str) -> str:
    """
    Minimal OpenRouter client using the unofficial fetch via httpx for a single-turn chat.
    We keep it inline to avoid adding dependencies elsewhere in the repo.
    """
    import httpx  # SimpleSpecs already depends on httpx via other paths

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://github.com/hambonesoftware/SimpleSpecs",
        "X-Title": "SimpleSpecs",
        "Content-Type": "application/json",
    }

    body = {
        "model": SPECS_LLM_MODEL,
        "messages": [
            {"role": "system", "content": "You are a precise specifications extraction assistant. Reply with JSON only."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
    }

    timeout = httpx.Timeout(SPECS_LLM_TIMEOUT_S)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=body)
        r.raise_for_status()
        data = r.json()
        try:
            return data["choices"][0]["message"]["content"]
        except Exception:
            return json.dumps({"error": "Unexpected response", "raw": data})


def _best_doc_text_from_cache(session: Session, document: Document) -> Tuple[str, Optional[str]]:
    """
    Try to obtain the best available "full text" for the document from the artifact store.
    Returns (text, doc_hash?|None).
    """
    # Prefer a dedicated PARSED_TEXT artifact if your repo writes one.
    for key in ("parsed_text", "fulltext", "plain_text"):
        cached = get_cached_artifact(
            session=session,
            document_id=document.id,
            artifact_type=PARSED_TEXT_ARTIFACT_TYPE,
            key=key,
            inputs=None,
        )
        if cached and isinstance(cached.body, dict):
            text = cached.body.get("text") or cached.body.get("content") or ""
            if text:
                return text, cached.body.get("doc_hash")

    # Fall back to reading the PDF and extracting on the fly (basic PyMuPDF approach).
    # We avoid adding new heavy deps; SimpleSpecs likely already uses PyMuPDF elsewhere.
    try:
        import fitz  # PyMuPDF
        # Document is typically saved in uploads/ by filename; try that.
        from backend.paths import UPLOAD_DIR  # type: ignore
        import os
        pdf_path = os.path.join(UPLOAD_DIR, document.filename)  # type: ignore[attr-defined]
        text_parts: List[str] = []
        with fitz.open(pdf_path) as doc:
            for page in doc:
                text_parts.append(page.get_text("text"))
        return "\n".join(text_parts), None
    except Exception:
        return "", None


async def _run_single_bucket(bucket: Dict[str, str], doc_text: str) -> Dict[str, Any]:
    name = bucket["name"]
    prompt = bucket["prompt"] + doc_text
    try:
        raw = await _openrouter_chat(prompt)
        # Try to coerce to JSON when possible
        try:
            data = json.loads(raw)
        except Exception:
            data = {"raw": raw}
        return {"name": name, "ok": True, "data": data}
    except Exception as exc:
        return {"name": name, "ok": False, "error": str(exc)}


async def run_all_buckets_concurrently(
    *, session: Session, document: Document, settings: Any = None
) -> Dict[str, Any]:
    """
    Orchestrates a single concurrent run of all BUCKETS for one document.
    Returns a dictionary with "buckets" (mapping) and light run metadata.
    """
    doc_text, doc_hash = _best_doc_text_from_cache(session, document)
    if not doc_text:
        # We don't fail hard; return an informative structure
        return {
            "doc_id": document.id,
            "doc_hash": doc_hash,
            "buckets": {},
            "messages": ["No parsed text available for document; unable to run buckets."],
        }

    sem = asyncio.Semaphore(SPECS_MAX_CONCURRENCY)

    async def guarded(bucket):
        async with sem:
            return await _run_single_bucket(bucket, doc_text)

    results = await asyncio.gather(*(guarded(b) for b in BUCKETS))

    buckets_out: Dict[str, Any] = {}
    messages: List[str] = []
    for item in results:
        name = item["name"]
        if item.get("ok"):
            buckets_out[name] = item.get("data")
        else:
            buckets_out[name] = {"error": item.get("error", "unknown")}
            messages.append(f"Bucket {name} failed: {item.get('error')}")

    return {
        "doc_id": document.id,
        "doc_hash": doc_hash,
        "buckets": buckets_out,
        "messages": messages,
    }
