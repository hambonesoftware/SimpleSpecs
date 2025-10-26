"""File service helpers for uploads and listings."""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Tuple

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import desc
from sqlmodel import Session, select

from ..config import Settings
from ..models import Document

CHUNK_SIZE = 1024 * 1024  # 1MB


def _secure_filename(filename: str) -> str:
    """Return a filesystem-safe version of the provided filename."""

    if not filename:
        return f"document-{secrets.token_hex(8)}.pdf"
    name = Path(filename).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return cleaned or f"document-{secrets.token_hex(8)}.pdf"


async def handle_upload(
    *, session: Session, upload: UploadFile, settings: Settings
) -> Tuple[Document, bool]:
    """Persist an uploaded file and return the stored document with a creation flag."""

    if (
        upload.content_type
        and upload.content_type.lower() not in settings.allowed_mimetypes
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported file type"
        )

    filename = _secure_filename(upload.filename or "")
    temp_dir = settings.upload_dir / "_incoming"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"{secrets.token_hex(16)}.tmp"

    file_hash = hashlib.sha256()
    total_bytes = 0

    try:
        with temp_path.open("wb") as buffer:
            while True:
                chunk = await upload.read(CHUNK_SIZE)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > settings.max_upload_size:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="File exceeds maximum allowed size",
                    )
                file_hash.update(chunk)
                buffer.write(chunk)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise
    finally:
        await upload.close()

    checksum = file_hash.hexdigest()
    existing_document = session.exec(
        select(Document).where(Document.checksum == checksum)
    ).first()
    if existing_document:
        if temp_path.exists():
            temp_path.unlink()
        return existing_document, False

    document = Document(
        filename=filename,
        checksum=checksum,
        uploaded_at=datetime.now(UTC),
        status="uploaded",
    )
    session.add(document)
    session.commit()
    session.refresh(document)

    document_dir = settings.upload_dir / str(document.id)
    document_dir.mkdir(parents=True, exist_ok=True)
    final_path = document_dir / filename
    temp_path.replace(final_path)

    return document, True


def list_documents(*, session: Session) -> list[Document]:
    """Return a list of stored documents ordered by upload date (newest first)."""

    statement = select(Document).order_by(
        desc(Document.__table__.c.uploaded_at)  # type: ignore[attr-defined]
    )
    return list(session.exec(statement))
