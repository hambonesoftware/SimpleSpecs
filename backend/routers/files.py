"""File upload and listing endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlmodel import Session

from ..config import Settings, get_settings
from ..database import get_session
from ..models import Document
from ..services.files import delete_document, handle_upload, list_documents
from ..paths import EXPORT_DIR, UPLOAD_DIR

router = APIRouter(prefix="/api", tags=["files"])


@router.post("/upload", response_model=Document)
async def upload_file(
    *,
    file: UploadFile = File(...),
    response: Response,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Document:
    """Handle PDF uploads and return the stored document."""

    document, created = await handle_upload(
        session=session, upload=file, settings=settings
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return document


@router.get("/files", response_model=list[Document])
async def get_files(
    *, session: Session = Depends(get_session), settings: Settings = Depends(get_settings)
) -> list[Document]:
    """Return the list of uploaded documents, tolerating missing storage paths."""

    # Guarantee both legacy (settings-driven) and new defaults exist; return an empty
    # list instead of propagating filesystem errors when the directories are missing.
    for directory in {
        UPLOAD_DIR,
        EXPORT_DIR,
        settings.upload_dir,
        settings.export_dir,
    }:
        Path(directory).mkdir(parents=True, exist_ok=True)

    return list_documents(session=session)


@router.delete("/files/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_file(
    document_id: int,
    *,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Delete a stored document and its associated artifacts."""

    removed = delete_document(
        session=session, document_id=document_id, settings=settings
    )
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
