"""Helpers for persisting and retrieving document artifacts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from sqlalchemy import delete, select
from sqlmodel import Session

from ..models import (
    Document,
    DocumentArtifact,
    DocumentArtifactType,
    DocumentPage,
    DocumentTable,
)
from ..services.pdf_native import ParseResult

PARSER_VERSION = "2025.01"
PARSE_RESULT_ARTIFACT_KEY = "parse-result"


def _now() -> datetime:
    """Return the current UTC timestamp."""

    return datetime.now(UTC)


def _normalise_inputs(inputs: Mapping[str, Any]) -> str:
    """Return a deterministic JSON serialisation for hashing purposes."""

    def _default(value: Any) -> Any:  # noqa: ANN401 - json fallback hook
        if isinstance(value, set):
            return sorted(value)
        if isinstance(value, (datetime,)):
            return value.isoformat()
        if isinstance(value, Path):
            return str(value)
        return value

    packed = json.dumps(inputs, sort_keys=True, default=_default, separators=(",", ":"))
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


def persist_parse_result(
    *, session: Session, document: Document, parse_result: ParseResult
) -> None:
    """Persist parsed pages and tables for a document."""

    if document.id is None:
        raise ValueError("Document must be persisted before storing artifacts")

    document_id = document.id

    session.exec(delete(DocumentPage).where(DocumentPage.document_id == document_id))
    session.exec(delete(DocumentTable).where(DocumentTable.document_id == document_id))

    for page in parse_result.pages:
        layout = [
            {
                "text": block.text,
                "bbox": list(block.bbox),
                "font": block.font,
                "font_size": block.font_size,
                "source": block.source,
            }
            for block in page.blocks
        ]
        text_content = "\n".join(block.text for block in page.blocks if block.text)
        session.add(
            DocumentPage(
                document_id=document_id,
                page_index=page.page_number,
                width=page.width,
                height=page.height,
                text_raw=text_content,
                layout=layout,
            )
        )

    for page in parse_result.pages:
        for marker in page.tables:
            session.add(
                DocumentTable(
                    document_id=document_id,
                    page_index=marker.page_number,
                    bbox=list(marker.bbox),
                    flavor=marker.flavor,
                    accuracy=marker.accuracy,
                )
            )

    document.page_count = len(parse_result.pages)
    document.has_ocr = parse_result.has_ocr
    document.used_mineru = parse_result.used_mineru
    document.parser_version = PARSER_VERSION
    document.last_parsed_at = _now()
    document.status = "parsed"
    session.add(document)
    session.commit()

    cache_parse_result(
        session=session, document=document, parse_result=parse_result
    )


def _cache_inputs_for_document(document: Document) -> Mapping[str, Any]:
    checksum = document.checksum or ""
    doc_hash = hashlib.sha256(checksum.encode("utf-8")).hexdigest()
    return {"doc_hash": doc_hash, "parser_version": PARSER_VERSION}


def get_cached_parse_payload(
    *, session: Session, document: Document
) -> Mapping[str, Any] | None:
    """Return a cached parse payload for the provided document if available."""

    if document.id is None:
        return None

    artifact = get_cached_artifact(
        session=session,
        document_id=document.id,
        artifact_type=DocumentArtifactType.PAGE_LAYOUT,
        key=PARSE_RESULT_ARTIFACT_KEY,
        inputs=_cache_inputs_for_document(document),
    )
    if artifact is None:
        return None
    return artifact.body


def cache_parse_result(
    *, session: Session, document: Document, parse_result: ParseResult
) -> None:
    """Store the parse result payload keyed by the document hash."""

    if document.id is None:
        raise ValueError("Document must be persisted before caching parse result")

    store_artifact(
        session=session,
        document_id=document.id,
        artifact_type=DocumentArtifactType.PAGE_LAYOUT,
        key=PARSE_RESULT_ARTIFACT_KEY,
        inputs=_cache_inputs_for_document(document),
        body=parse_result.to_dict(),
    )


def get_cached_artifact(
    *,
    session: Session,
    document_id: int,
    artifact_type: DocumentArtifactType,
    key: str,
    inputs: Mapping[str, Any],
) -> DocumentArtifact | None:
    """Return a cached artifact if the hashed inputs match."""

    sha_inputs = _normalise_inputs(inputs)
    statement = select(DocumentArtifact).where(
        DocumentArtifact.document_id == document_id,
        DocumentArtifact.artifact_type == artifact_type,
        DocumentArtifact.artifact_key == key,
        DocumentArtifact.sha_inputs == sha_inputs,
    )
    result = session.exec(statement).first()
    if result is None:
        return None
    if isinstance(result, DocumentArtifact):
        return result
    if hasattr(result, "__getitem__"):
        try:
            candidate = result[0]
            if isinstance(candidate, DocumentArtifact):
                return candidate
        except (IndexError, KeyError, TypeError):
            pass
    return result


def store_artifact(
    *,
    session: Session,
    document_id: int,
    artifact_type: DocumentArtifactType,
    key: str,
    inputs: Mapping[str, Any],
    body: Mapping[str, Any] | Iterable[Mapping[str, Any]],
    text: str | None = None,
    blob_path: str | None = None,
) -> DocumentArtifact:
    """Persist an artifact payload keyed by the hashed inputs."""

    sha_inputs = _normalise_inputs(inputs)
    existing = get_cached_artifact(
        session=session,
        document_id=document_id,
        artifact_type=artifact_type,
        key=key,
        inputs=inputs,
    )
    if existing is not None:
        return existing

    payload: dict[str, Any]
    if isinstance(body, Mapping):
        payload = dict(body)
    else:
        payload = {"items": list(body)}

    artifact = DocumentArtifact(
        document_id=document_id,
        artifact_type=artifact_type,
        artifact_key=key,
        sha_inputs=sha_inputs,
        body=payload,
        text=text,
        blob_path=blob_path,
    )
    session.add(artifact)
    session.commit()
    session.refresh(artifact)
    return artifact


__all__ = [
    "PARSER_VERSION",
    "PARSE_RESULT_ARTIFACT_KEY",
    "cache_parse_result",
    "get_cached_artifact",
    "get_cached_parse_payload",
    "persist_parse_result",
    "store_artifact",
]

